from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
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
    for secret_name in ("CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET"):
        value = str(getattr(settings, secret_name, "") or "")
        if value:
            message = message.replace(value, "[REDACTED]")
    return message[:800]


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    actual = getattr(value, "actual_instance", None)
    if actual is not None and actual is not value:
        return _plain(actual)
    for name in ("model_dump", "to_dict"):
        method = getattr(value, name, None)
        if callable(method):
            try:
                return _plain(method())
            except TypeError:
                pass
    data = getattr(value, "data", None)
    if data is not None and data is not value:
        return _plain(data)
    if hasattr(value, "__dict__"):
        return {
            str(key): _plain(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _extract_transaction(value: Any) -> dict[str, Any]:
    plain = _plain(value)
    candidates = []
    for mapping in _walk(plain):
        if mapping.get("id") and mapping.get("state"):
            candidates.append(mapping)
    if not candidates:
        raise ContractAuthorisationError("Circle returned an invalid contract transaction response.")
    payload = candidates[0]
    tx_id = str(payload.get("id") or "").strip()
    state = str(payload.get("state") or "UNKNOWN").upper().strip()
    tx_hash = str(payload.get("txHash") or payload.get("tx_hash") or "").strip()
    failure = str(
        payload.get("errorReason")
        or payload.get("error_reason")
        or payload.get("error")
        or ""
    ).strip()
    return {"id": tx_id, "state": state, "tx_hash": tx_hash, "failure": failure}


class CircleContractOwnerClient:
    """Circle adapter for the contract owner's setAgentAuthorised call."""

    def __init__(self):
        api_key = str(getattr(settings, "CIRCLE_API_KEY", "") or "").strip()
        entity_secret = str(getattr(settings, "CIRCLE_ENTITY_SECRET", "") or "").strip()
        if not api_key:
            raise ContractAuthorisationError("CIRCLE_API_KEY is not configured.")
        if not entity_secret:
            raise ContractAuthorisationError("CIRCLE_ENTITY_SECRET is not configured.")
        try:
            from circle.web3 import developer_controlled_wallets, utils
        except ImportError as exc:
            raise ContractAuthorisationError(
                "Circle developer-controlled wallet SDK is not installed."
            ) from exc
        self._sdk = developer_controlled_wallets
        try:
            client = utils.init_developer_controlled_wallets_client(
                api_key=api_key,
                entity_secret=entity_secret,
            )
            self._transactions = developer_controlled_wallets.TransactionsApi(client)
        except Exception as exc:
            raise ContractAuthorisationError(
                f"Circle contract-owner client initialization failed: {_safe_message(exc)}"
            ) from exc

    def create_contract_call(
        self,
        *,
        owner_wallet_id: str,
        function_signature: str,
        abi_parameters: list[str],
        idempotency_key: uuid.UUID,
    ) -> dict[str, Any]:
        wallet_id = str(owner_wallet_id or "").strip()
        if not wallet_id:
            raise ContractAuthorisationError(
                "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID is not configured."
            )
        payload = {
            "idempotencyKey": str(idempotency_key),
            "walletId": wallet_id,
            "blockchain": settings.ARC_BLOCKCHAIN,
            "contractAddress": settings.VEYRA_CONTRACT_ADDRESS,
            "abiFunctionSignature": function_signature,
            "abiParameters": abi_parameters,
            "feeLevel": getattr(
                settings,
                "VEYRA_CONTRACT_AUTHORISATION_FEE_LEVEL",
                "MEDIUM",
            ),
        }
        try:
            request = self._sdk.CreateContractExecutionTransactionForDeveloperRequest.from_dict(
                payload
            )
            response = self._transactions.create_developer_transaction_contract_execution(
                request
            )
            return _extract_transaction(response)
        except ContractAuthorisationError:
            raise
        except Exception as exc:
            raise ContractAuthorisationError(
                f"Circle contract-owner transaction failed: {_safe_message(exc)}"
            ) from exc

    def create_authorisation(
        self,
        *,
        owner_wallet_id: str,
        agent_address: str,
        idempotency_key: uuid.UUID,
    ) -> dict[str, Any]:
        return self.create_contract_call(
            owner_wallet_id=owner_wallet_id,
            function_signature="setAgentAuthorised(address,bool)",
            abi_parameters=[agent_address, "true"],
            idempotency_key=idempotency_key,
        )

    def get_transaction(self, transaction_id: str) -> dict[str, Any]:
        try:
            return _extract_transaction(self._transactions.get_transaction(id=transaction_id))
        except ContractAuthorisationError:
            raise
        except Exception as exc:
            raise ContractAuthorisationError(
                f"Circle agent-authorisation lookup failed: {_safe_message(exc)}"
            ) from exc


def _contract_owner_address(arc: ArcClient) -> str:
    try:
        owner = arc.contract.functions.owner().call()
    except Exception as exc:
        raise ContractAuthorisationError(
            "Veyra could not read the deployed contract owner address."
        ) from exc
    if not Web3.is_address(owner):
        raise ContractAuthorisationError("The deployed contract returned an invalid owner address.")

    onchain_owner = Web3.to_checksum_address(owner)
    configured = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS", "") or ""
    ).strip()
    if not configured:
        raise ContractAuthorisationError(
            "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS is not configured. "
            f"The current on-chain owner is {onchain_owner}."
        )
    if not Web3.is_address(configured):
        raise ContractAuthorisationError(
            "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS is not a valid EVM address."
        )

    configured_owner = Web3.to_checksum_address(configured)
    if configured_owner != onchain_owner:
        raise ContractAuthorisationError(
            "The configured Circle platform owner wallet does not yet own the "
            f"Veyra contract. On-chain owner: {onchain_owner}; configured owner: "
            f"{configured_owner}. Complete the two-step ownership transfer first."
        )
    return onchain_owner


def _contract_owner_circle_wallet_id() -> str:
    wallet_id = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID", "") or ""
    ).strip()
    if not wallet_id:
        raise ContractAuthorisationError(
            "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID is not configured."
        )
    return wallet_id


def _persist_transaction(worker: WorkerAgent, snapshot: dict[str, Any]) -> None:
    with transaction.atomic():
        locked = WorkerAgent.objects.select_for_update().get(pk=worker.pk)
        locked.contract_authorisation_circle_transaction_id = snapshot["id"]
        if snapshot.get("tx_hash"):
            locked.contract_authorisation_tx_hash = snapshot["tx_hash"]
        locked.status = WorkerAgent.Status.AUTHORISATION_PENDING
        locked.save(
            update_fields=[
                "contract_authorisation_circle_transaction_id",
                "contract_authorisation_tx_hash",
                "status",
                "updated_at",
            ]
        )


def authorise_worker_contract(
    worker: WorkerAgent,
    *,
    arc_client: ArcClient | None = None,
    circle_client: CircleContractOwnerClient | None = None,
) -> ContractAuthorisationResult:
    """Idempotently authorize one agent wallet on VeyraJobEscrow."""

    worker.refresh_from_db()
    if not worker.worker_wallet_address:
        raise ContractAuthorisationError("The dedicated agent wallet is missing.")

    arc = arc_client or ArcClient()
    try:
        arc.assert_chain()
        if arc.is_agent_authorised(worker.worker_wallet_address):
            worker.contract_authorised = True
            worker.status = (
                WorkerAgent.Status.ACTIVE
                if worker.test_assignment_passed
                else WorkerAgent.Status.READY_FOR_QUALIFICATION
            )
            worker.save(update_fields=["contract_authorised", "status", "updated_at"])
            return ContractAuthorisationResult(
                authorised=True,
                created_transaction=False,
                circle_transaction_id=worker.contract_authorisation_circle_transaction_id,
                transaction_hash=worker.contract_authorisation_tx_hash,
            )
    except ContractAuthorisationError:
        raise
    except Exception as exc:
        raise ContractAuthorisationError(
            f"Veyra could not read Arc contract state: {_safe_message(exc)}"
        ) from exc

    _contract_owner_address(arc)
    owner_wallet_id = _contract_owner_circle_wallet_id()
    circle = circle_client or CircleContractOwnerClient()

    if not worker.contract_authorisation_idempotency_key:
        worker.contract_authorisation_idempotency_key = uuid.uuid4()
        worker.save(
            update_fields=["contract_authorisation_idempotency_key", "updated_at"]
        )

    created = False
    if worker.contract_authorisation_circle_transaction_id:
        snapshot = circle.get_transaction(
            worker.contract_authorisation_circle_transaction_id
        )
    else:
        snapshot = circle.create_authorisation(
            owner_wallet_id=owner_wallet_id,
            agent_address=Web3.to_checksum_address(worker.worker_wallet_address),
            idempotency_key=worker.contract_authorisation_idempotency_key,
        )
        created = True
        _persist_transaction(worker, snapshot)

    pending_states = {"INITIATED", "PENDING", "QUEUED", "SENT", "CONFIRMED"}
    failure_states = {"FAILED", "CANCELLED", "DENIED"}
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
    deadline = time.monotonic() + timeout

    while snapshot["state"] in pending_states and time.monotonic() < deadline:
        time.sleep(interval)
        snapshot = circle.get_transaction(snapshot["id"])
        _persist_transaction(worker, snapshot)

    if snapshot["state"] in failure_states:
        raise ContractAuthorisationError(
            snapshot.get("failure") or f"Circle ended in state {snapshot['state']}."
        )
    if snapshot["state"] != "COMPLETE":
        raise ContractAuthorisationPending(
            f"Contract authorisation is still {snapshot['state']}. Veyra will reuse the same transaction on retry."
        )

    tx_hash = str(snapshot.get("tx_hash") or "").strip()
    if tx_hash and Web3.is_hex(tx_hash) and len(tx_hash) == 66:
        worker.contract_authorisation_tx_hash = tx_hash
        worker.save(update_fields=["contract_authorisation_tx_hash", "updated_at"])

    receipt_deadline = time.monotonic() + int(
        getattr(settings, "WORKER_ARC_RECEIPT_TIMEOUT_SECONDS", 120)
    )
    while time.monotonic() < receipt_deadline:
        try:
            if arc.is_agent_authorised(worker.worker_wallet_address):
                worker.contract_authorised = True
                worker.status = (
                    WorkerAgent.Status.ACTIVE
                    if worker.test_assignment_passed
                    else WorkerAgent.Status.READY_FOR_QUALIFICATION
                )
                worker.save(
                    update_fields=["contract_authorised", "status", "updated_at"]
                )
                return ContractAuthorisationResult(
                    authorised=True,
                    created_transaction=created,
                    circle_transaction_id=snapshot["id"],
                    transaction_hash=tx_hash,
                )
        except Exception:
            pass
        time.sleep(interval)

    raise ContractAuthorisationPending(
        "The Circle transaction completed, but Arc has not confirmed agent authorisation yet."
    )
