from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction

from workers.models import WorkerAgent


EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class WorkerWalletProvisioningError(RuntimeError):
    """Raised when a Circle worker wallet cannot be created, recovered, or validated."""


@dataclass(frozen=True)
class WorkerWalletProvisioningResult:
    worker_id: str
    wallet_set_id: str
    wallet_id: str
    address: str
    blockchain: str
    account_type: str
    created: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "wallet_set_id": self.wallet_set_id,
            "wallet_id": self.wallet_id,
            "address": self.address,
            "blockchain": self.blockchain,
            "account_type": self.account_type,
            "created": self.created,
        }


def _to_plain(value: Any) -> Any:
    """Convert Circle SDK response objects, including enums, into plain values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return _to_plain(value.value)

    enum_value = getattr(value, "value", None)
    if enum_value is not None and enum_value is not value:
        return _to_plain(enum_value)

    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item) for item in value]

    actual_instance = getattr(value, "actual_instance", None)
    if actual_instance is not None and actual_instance is not value:
        return _to_plain(actual_instance)

    for method_name in ("model_dump", "to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _to_plain(method())
            except TypeError:
                continue

    data = getattr(value, "data", None)
    if data is not None and data is not value:
        return {"data": _to_plain(data)}

    if hasattr(value, "__dict__"):
        return {
            str(key): _to_plain(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }

    return str(value)


def _normalise_circle_code(value: Any) -> str:
    """Normalise Circle SDK enum representations.

    Examples:
    - Blockchain.ARC_MINUS_TESTNET -> ARC-TESTNET
    - BLOCKCHAIN.ARC_MINUS_TESTNET -> ARC-TESTNET
    - ARC_TESTNET -> ARC-TESTNET
    - AccountType.SCA -> SCA
    """

    plain = _to_plain(value)
    text = str(plain or "").strip()
    if not text:
        return ""

    if "." in text:
        text = text.rsplit(".", 1)[-1]

    text = text.upper()
    text = text.replace("_MINUS_", "-")
    text = text.replace("_", "-")
    return text


def _walk_mappings(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_mappings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_mappings(item)


def _value(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _extract_wallet_set_id(response: Any) -> str:
    plain = _to_plain(response)

    for mapping in _walk_mappings(plain):
        nested = _value(mapping, "walletSet", "wallet_set")
        if isinstance(nested, dict):
            identifier = _value(nested, "id")
            if identifier:
                return str(identifier)

    for mapping in _walk_mappings(plain):
        identifier = _value(mapping, "id")
        name = _value(mapping, "name")
        address = _value(mapping, "address")
        if identifier and name and not address:
            return str(identifier)

    raise WorkerWalletProvisioningError(
        "Circle created no usable wallet-set identifier. No wallet was stored locally."
    )


def _extract_wallet(response: Any) -> dict[str, str]:
    plain = _to_plain(response)
    candidates: list[dict[str, Any]] = []

    for mapping in _walk_mappings(plain):
        identifier = _value(mapping, "id")
        address = _value(mapping, "address")
        if identifier and address:
            candidates.append(mapping)

    if not candidates:
        raise WorkerWalletProvisioningError(
            "Circle created no usable wallet record. No wallet was stored locally."
        )

    expected_chain = _normalise_circle_code(settings.ARC_BLOCKCHAIN)
    chosen = next(
        (
            item
            for item in candidates
            if _normalise_circle_code(_value(item, "blockchain")) == expected_chain
        ),
        candidates[0],
    )

    wallet_id = str(_value(chosen, "id") or "").strip()
    address = str(_value(chosen, "address") or "").strip()
    blockchain = _normalise_circle_code(
        _value(chosen, "blockchain") or expected_chain
    )
    account_type = _normalise_circle_code(
        _value(chosen, "accountType", "account_type") or "SCA"
    )

    if not wallet_id:
        raise WorkerWalletProvisioningError("Circle wallet ID was missing.")
    if not EVM_ADDRESS_RE.fullmatch(address):
        raise WorkerWalletProvisioningError("Circle returned an invalid worker wallet address.")
    if blockchain != expected_chain:
        raise WorkerWalletProvisioningError(
            f"Circle returned {blockchain}, but Veyra requires {expected_chain}."
        )
    if account_type != "SCA":
        raise WorkerWalletProvisioningError(
            f"Circle returned account type {account_type}, but Veyra requires SCA."
        )

    return {
        "id": wallet_id,
        "address": address,
        "blockchain": blockchain,
        "account_type": account_type,
    }


def _create_circle_resources() -> tuple[str, dict[str, str]]:
    api_key = str(getattr(settings, "CIRCLE_API_KEY", "") or "").strip()
    entity_secret = str(
        getattr(settings, "CIRCLE_ENTITY_SECRET", "") or ""
    ).strip()

    if not api_key:
        raise WorkerWalletProvisioningError("CIRCLE_API_KEY is not configured.")
    if not entity_secret:
        raise WorkerWalletProvisioningError("CIRCLE_ENTITY_SECRET is not configured.")

    try:
        from circle.web3 import developer_controlled_wallets, utils
    except ImportError as exc:
        raise WorkerWalletProvisioningError(
            "Circle developer-controlled wallet SDK is not installed. "
            "Run: pip install circle-developer-controlled-wallets"
        ) from exc

    try:
        client = utils.init_developer_controlled_wallets_client(
            api_key=api_key,
            entity_secret=entity_secret,
        )
        wallet_sets_api = developer_controlled_wallets.WalletSetsApi(client)
        wallets_api = developer_controlled_wallets.WalletsApi(client)

        wallet_set_response = wallet_sets_api.create_wallet_set(
            developer_controlled_wallets.CreateWalletSetRequest.from_dict(
                {
                    "name": settings.WORKER_CIRCLE_WALLET_SET_NAME,
                }
            )
        )
        wallet_set_id = _extract_wallet_set_id(wallet_set_response)

        wallet_response = wallets_api.create_wallet(
            developer_controlled_wallets.CreateWalletRequest.from_dict(
                {
                    "walletSetId": wallet_set_id,
                    "blockchains": [settings.ARC_BLOCKCHAIN],
                    "count": 1,
                    "accountType": "SCA",
                }
            )
        )
        wallet = _extract_wallet(wallet_response)
        return wallet_set_id, wallet
    except WorkerWalletProvisioningError:
        raise
    except Exception as exc:
        safe_message = str(exc).replace(api_key, "[REDACTED]").replace(
            entity_secret, "[REDACTED]"
        )
        raise WorkerWalletProvisioningError(
            f"Circle worker-wallet creation failed: {safe_message}"
        ) from exc


def _validate_existing_wallet_values(
    *,
    wallet_set_id: str,
    wallet_id: str,
    address: str,
    blockchain: str,
    account_type: str,
) -> dict[str, str]:
    wallet_set_id = str(wallet_set_id or "").strip()
    wallet_id = str(wallet_id or "").strip()
    address = str(address or "").strip()
    blockchain = _normalise_circle_code(blockchain)
    account_type = _normalise_circle_code(account_type)

    if not wallet_set_id:
        raise WorkerWalletProvisioningError("Wallet set ID is required.")
    if not wallet_id:
        raise WorkerWalletProvisioningError("Wallet ID is required.")
    if not EVM_ADDRESS_RE.fullmatch(address):
        raise WorkerWalletProvisioningError("Enter a valid EVM worker wallet address.")
    if blockchain != "ARC-TESTNET":
        raise WorkerWalletProvisioningError("The recovered wallet must use ARC-TESTNET.")
    if account_type != "SCA":
        raise WorkerWalletProvisioningError("The recovered wallet must be an SCA.")

    return {
        "wallet_set_id": wallet_set_id,
        "wallet_id": wallet_id,
        "address": address,
        "blockchain": blockchain,
        "account_type": account_type,
    }


def attach_existing_worker_wallet(
    worker: WorkerAgent,
    *,
    wallet_set_id: str,
    wallet_id: str,
    address: str,
    blockchain: str = "ARC-TESTNET",
    account_type: str = "SCA",
) -> WorkerWalletProvisioningResult:
    """Attach an already-created Circle wallet without creating another one."""

    values = _validate_existing_wallet_values(
        wallet_set_id=wallet_set_id,
        wallet_id=wallet_id,
        address=address,
        blockchain=blockchain,
        account_type=account_type,
    )

    # Agent operational wallets must never reuse a user-controlled client or
    # sign-in wallet.
    from wallets.models import WalletAccount

    if WalletAccount.objects.filter(
        blockchain=values["blockchain"],
        address__iexact=values["address"],
    ).exists():
        raise WorkerWalletProvisioningError(
            "This address belongs to a user-controlled Veyra account wallet. "
            "Create a dedicated agent operational wallet instead."
        )

    worker.refresh_from_db()
    if not worker.engine_connected:
        raise WorkerWalletProvisioningError(
            "Connect the coding engine before attaching the worker wallet."
        )

    with transaction.atomic():
        locked_worker = WorkerAgent.objects.select_for_update().get(pk=worker.pk)

        existing = {
            "wallet_set_id": locked_worker.circle_wallet_set_id or "",
            "wallet_id": locked_worker.circle_wallet_id or "",
            "address": locked_worker.worker_wallet_address or "",
        }
        has_existing = any(existing.values())

        if has_existing:
            same_wallet = (
                existing["wallet_set_id"] == values["wallet_set_id"]
                and existing["wallet_id"] == values["wallet_id"]
                and existing["address"].lower() == values["address"].lower()
            )
            if not same_wallet:
                raise WorkerWalletProvisioningError(
                    "This worker already has different Circle wallet metadata. "
                    "Refusing to overwrite it."
                )

        locked_worker.circle_wallet_set_id = values["wallet_set_id"]
        locked_worker.circle_wallet_id = values["wallet_id"]
        locked_worker.worker_wallet_address = values["address"]
        locked_worker.payout_wallet_address = values["address"]
        locked_worker.wallet_blockchain = values["blockchain"]
        locked_worker.wallet_account_type = values["account_type"]

        if locked_worker.status in {
            WorkerAgent.Status.PROFILE_READY,
            WorkerAgent.Status.ENGINE_CONNECTED,
        }:
            locked_worker.status = WorkerAgent.Status.WALLET_READY

        locked_worker.save(
            update_fields=[
                "circle_wallet_set_id",
                "circle_wallet_id",
                "worker_wallet_address",
                "payout_wallet_address",
                "wallet_blockchain",
                "wallet_account_type",
                "status",
                "updated_at",
            ]
        )

    return WorkerWalletProvisioningResult(
        worker_id=str(locked_worker.id),
        wallet_set_id=values["wallet_set_id"],
        wallet_id=values["wallet_id"],
        address=values["address"],
        blockchain=values["blockchain"],
        account_type=values["account_type"],
        created=False,
    )


def provision_worker_wallet(worker: WorkerAgent) -> WorkerWalletProvisioningResult:
    """Create and attach one Arc Testnet SCA wallet to a Veyra worker."""

    worker.refresh_from_db()

    if worker.circle_wallet_id and worker.worker_wallet_address:
        update_fields = []
        if not worker.payout_wallet_address:
            worker.payout_wallet_address = worker.worker_wallet_address
            update_fields.append("payout_wallet_address")
        if worker.status in {
            WorkerAgent.Status.PROFILE_READY,
            WorkerAgent.Status.ENGINE_CONNECTED,
        }:
            worker.status = WorkerAgent.Status.WALLET_READY
            update_fields.append("status")
        if update_fields:
            worker.save(update_fields=[*update_fields, "updated_at"])

        return WorkerWalletProvisioningResult(
            worker_id=str(worker.id),
            wallet_set_id=worker.circle_wallet_set_id,
            wallet_id=worker.circle_wallet_id,
            address=worker.worker_wallet_address,
            blockchain=worker.wallet_blockchain,
            account_type=worker.wallet_account_type,
            created=False,
        )

    if not worker.engine_connected:
        raise WorkerWalletProvisioningError(
            "Connect the coding engine before creating the worker wallet."
        )

    wallet_set_id, wallet = _create_circle_resources()

    with transaction.atomic():
        locked_worker = WorkerAgent.objects.select_for_update().get(pk=worker.pk)

        if locked_worker.circle_wallet_id and locked_worker.worker_wallet_address:
            return WorkerWalletProvisioningResult(
                worker_id=str(locked_worker.id),
                wallet_set_id=locked_worker.circle_wallet_set_id,
                wallet_id=locked_worker.circle_wallet_id,
                address=locked_worker.worker_wallet_address,
                blockchain=locked_worker.wallet_blockchain,
                account_type=locked_worker.wallet_account_type,
                created=False,
            )

        locked_worker.circle_wallet_set_id = wallet_set_id
        locked_worker.circle_wallet_id = wallet["id"]
        locked_worker.worker_wallet_address = wallet["address"]
        locked_worker.payout_wallet_address = wallet["address"]
        locked_worker.wallet_blockchain = wallet["blockchain"]
        locked_worker.wallet_account_type = wallet["account_type"]
        locked_worker.status = WorkerAgent.Status.WALLET_READY
        locked_worker.save(
            update_fields=[
                "circle_wallet_set_id",
                "circle_wallet_id",
                "worker_wallet_address",
                "payout_wallet_address",
                "wallet_blockchain",
                "wallet_account_type",
                "status",
                "updated_at",
            ]
        )

    return WorkerWalletProvisioningResult(
        worker_id=str(locked_worker.id),
        wallet_set_id=wallet_set_id,
        wallet_id=wallet["id"],
        address=wallet["address"],
        blockchain=wallet["blockchain"],
        account_type=wallet["account_type"],
        created=True,
    )
