from __future__ import annotations

import time
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from web3 import Web3

from blockchain.client import ArcClient
from workers.models import WorkerAgent


class ContractAuthorisationError(RuntimeError):
    """Raised when Veyra cannot authorize an agent wallet safely."""


class ContractAuthorisationPending(ContractAuthorisationError):
    """The transaction exists and should be reconciled instead of resubmitted."""


@dataclass(frozen=True)
class ContractAuthorisationResult:
    authorised: bool
    created_transaction: bool
    circle_transaction_id: str
    transaction_hash: str


def _safe_message(exc: Exception) -> str:
    message = str(exc or "").strip() or exc.__class__.__name__
    private_key = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_PRIVATE_KEY", "") or ""
    ).strip()
    if private_key:
        message = message.replace(private_key, "[REDACTED]")
        message = message.replace(private_key.removeprefix("0x"), "[REDACTED]")
    return message[:800]


def _owner_signer(arc: ArcClient):
    private_key = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_PRIVATE_KEY", "") or ""
    ).strip()
    if not private_key:
        raise ContractAuthorisationError(
            "VEYRA_CONTRACT_OWNER_PRIVATE_KEY is not configured."
        )
    try:
        account = arc.w3.eth.account.from_key(private_key)
    except Exception as exc:
        raise ContractAuthorisationError(
            "The configured contract-owner private key is invalid."
        ) from exc

    try:
        onchain_owner = Web3.to_checksum_address(
            arc.contract.functions.owner().call()
        )
    except Exception as exc:
        raise ContractAuthorisationError(
            "Veyra could not read the deployed contract owner address."
        ) from exc

    signer_address = Web3.to_checksum_address(account.address)
    configured_address = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS", "") or ""
    ).strip()
    if configured_address:
        if not Web3.is_address(configured_address):
            raise ContractAuthorisationError(
                "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS is not a valid EVM address."
            )
        if Web3.to_checksum_address(configured_address) != signer_address:
            raise ContractAuthorisationError(
                "The configured contract-owner address does not match the private key."
            )

    if signer_address != onchain_owner:
        raise ContractAuthorisationError(
            f"The configured signer {signer_address} is not the deployed contract "
            f"owner {onchain_owner}."
        )
    return account


def _mark_authorised(worker: WorkerAgent) -> ContractAuthorisationResult:
    worker.contract_authorised = True
    worker.status = (
        WorkerAgent.Status.ACTIVE
        if worker.test_assignment_passed
        else WorkerAgent.Status.READY_FOR_QUALIFICATION
    )
    worker.contract_authorisation_circle_transaction_id = ""
    worker.save(
        update_fields=[
            "contract_authorised",
            "status",
            "contract_authorisation_circle_transaction_id",
            "updated_at",
        ]
    )
    return ContractAuthorisationResult(
        authorised=True,
        created_transaction=False,
        circle_transaction_id="",
        transaction_hash=worker.contract_authorisation_tx_hash,
    )


def _wait_for_existing_transaction(
    worker: WorkerAgent,
    arc: ArcClient,
) -> ContractAuthorisationResult | None:
    tx_hash = str(worker.contract_authorisation_tx_hash or "").strip()
    if not tx_hash:
        return None

    try:
        receipt = arc.transaction_receipt_or_none(tx_hash)
    except Exception as exc:
        raise ContractAuthorisationError(
            f"Veyra could not inspect the existing Arc transaction: {_safe_message(exc)}"
        ) from exc

    if receipt is None:
        raise ContractAuthorisationPending(
            "Contract authorisation is still pending on Arc. Veyra will reuse the "
            "same transaction on retry."
        )

    status = int(receipt.get("status", 0) if isinstance(receipt, dict) else receipt.status)
    if status != 1:
        worker.contract_authorisation_tx_hash = ""
        worker.save(
            update_fields=["contract_authorisation_tx_hash", "updated_at"]
        )
        raise ContractAuthorisationError(
            "The previous contract-authorisation transaction reverted. Retry will "
            "submit a new transaction."
        )

    if arc.is_agent_authorised(worker.worker_wallet_address):
        return _mark_authorised(worker)

    raise ContractAuthorisationPending(
        "The Arc transaction succeeded, but the agent-authorisation state has not "
        "been indexed yet."
    )


def _submit_authorisation(
    worker: WorkerAgent,
    arc: ArcClient,
) -> str:
    signer = _owner_signer(arc)
    agent_address = Web3.to_checksum_address(worker.worker_wallet_address)

    function = arc.contract.functions.setAgentAuthorised(agent_address, True)
    try:
        nonce = arc.w3.eth.get_transaction_count(signer.address, "pending")
        transaction_data = {
            "from": signer.address,
            "nonce": nonce,
            "chainId": settings.ARC_CHAIN_ID,
        }
        try:
            gas_estimate = function.estimate_gas({"from": signer.address})
            transaction_data["gas"] = max(100_000, int(gas_estimate * 1.2))
        except Exception:
            transaction_data["gas"] = 250_000

        try:
            transaction_data["gasPrice"] = int(arc.w3.eth.gas_price)
        except Exception:
            pass

        unsigned = function.build_transaction(transaction_data)
        signed = signer.sign_transaction(unsigned)
        raw = getattr(signed, "raw_transaction", None)
        if raw is None:
            raw = getattr(signed, "rawTransaction", None)
        if raw is None:
            raise ContractAuthorisationError(
                "The Web3 signer did not return a raw transaction."
            )
        tx_hash = arc.w3.eth.send_raw_transaction(raw).hex()
    except ContractAuthorisationError:
        raise
    except Exception as exc:
        raise ContractAuthorisationError(
            f"Arc agent-authorisation transaction failed: {_safe_message(exc)}"
        ) from exc

    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    return tx_hash


def authorise_worker_contract(
    worker: WorkerAgent,
    *,
    arc_client: ArcClient | None = None,
    circle_client=None,
) -> ContractAuthorisationResult:
    """Idempotently authorize one agent wallet using the deployed owner EOA.

    circle_client is accepted only for backward-compatible tests/call sites and
    is deliberately ignored. Owner-level contract administration is not a
    Circle wallet action for this deployment.
    """

    worker.refresh_from_db()
    if not worker.worker_wallet_address:
        raise ContractAuthorisationError("The dedicated agent wallet is missing.")

    arc = arc_client or ArcClient()
    try:
        arc.assert_chain()
        if arc.is_agent_authorised(worker.worker_wallet_address):
            return _mark_authorised(worker)
    except ContractAuthorisationError:
        raise
    except Exception as exc:
        raise ContractAuthorisationError(
            f"Veyra could not read Arc contract state: {_safe_message(exc)}"
        ) from exc

    existing = _wait_for_existing_transaction(worker, arc)
    if existing is not None:
        return existing

    created = False
    with transaction.atomic():
        locked = WorkerAgent.objects.select_for_update().get(pk=worker.pk)
        if locked.contract_authorisation_tx_hash:
            worker = locked
        else:
            tx_hash = _submit_authorisation(locked, arc)
            locked.contract_authorisation_tx_hash = tx_hash
            locked.contract_authorisation_circle_transaction_id = ""
            locked.status = WorkerAgent.Status.AUTHORISATION_PENDING
            locked.save(
                update_fields=[
                    "contract_authorisation_tx_hash",
                    "contract_authorisation_circle_transaction_id",
                    "status",
                    "updated_at",
                ]
            )
            worker = locked
            created = True

    if not created:
        existing = _wait_for_existing_transaction(worker, arc)
        if existing is not None:
            return existing

    timeout = int(
        getattr(settings, "VEYRA_CONTRACT_AUTHORISATION_TIMEOUT_SECONDS", 180)
    )
    interval = max(
        1,
        int(
            getattr(
                settings,
                "VEYRA_CONTRACT_AUTHORISATION_POLL_INTERVAL_SECONDS",
                3,
            )
        ),
    )
    try:
        receipt = arc.w3.eth.wait_for_transaction_receipt(
            worker.contract_authorisation_tx_hash,
            timeout=timeout,
            poll_latency=interval,
        )
    except Exception as exc:
        raise ContractAuthorisationPending(
            "The Arc authorisation transaction was submitted and will be reused "
            f"on retry: {_safe_message(exc)}"
        ) from exc

    status = int(receipt.get("status", 0) if isinstance(receipt, dict) else receipt.status)
    if status != 1:
        worker.contract_authorisation_tx_hash = ""
        worker.save(
            update_fields=["contract_authorisation_tx_hash", "updated_at"]
        )
        raise ContractAuthorisationError(
            "The Arc contract-authorisation transaction reverted."
        )

    receipt_deadline = time.monotonic() + int(
        getattr(settings, "WORKER_ARC_RECEIPT_TIMEOUT_SECONDS", 120)
    )
    while time.monotonic() < receipt_deadline:
        try:
            if arc.is_agent_authorised(worker.worker_wallet_address):
                result = _mark_authorised(worker)
                return ContractAuthorisationResult(
                    authorised=True,
                    created_transaction=created,
                    circle_transaction_id="",
                    transaction_hash=result.transaction_hash,
                )
        except Exception:
            pass
        time.sleep(interval)

    raise ContractAuthorisationPending(
        "The Arc transaction succeeded, but the agent authorisation has not been "
        "confirmed by the RPC yet."
    )
