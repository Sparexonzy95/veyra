from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings

from workers.circle_wallet import _extract_wallet, _extract_wallet_set_id


class PlatformOwnerWalletError(RuntimeError):
    """Raised when the Veyra platform owner wallet cannot be provisioned safely."""


@dataclass(frozen=True)
class PlatformOwnerWalletResult:
    wallet_set_id: str
    wallet_id: str
    address: str
    blockchain: str
    account_type: str
    created: bool


def _safe_message(exc: Exception, *secrets: str) -> str:
    message = str(exc or "").strip() or exc.__class__.__name__
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:800]


def provision_platform_owner_wallet() -> PlatformOwnerWalletResult:
    configured_id = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID", "") or ""
    ).strip()
    configured_address = str(
        getattr(settings, "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS", "") or ""
    ).strip()
    if configured_id and configured_address:
        return PlatformOwnerWalletResult(
            wallet_set_id="",
            wallet_id=configured_id,
            address=configured_address,
            blockchain=settings.ARC_BLOCKCHAIN,
            account_type="SCA",
            created=False,
        )

    api_key = str(getattr(settings, "CIRCLE_API_KEY", "") or "").strip()
    entity_secret = str(getattr(settings, "CIRCLE_ENTITY_SECRET", "") or "").strip()
    if not api_key:
        raise PlatformOwnerWalletError("CIRCLE_API_KEY is not configured.")
    if not entity_secret:
        raise PlatformOwnerWalletError("CIRCLE_ENTITY_SECRET is not configured.")

    try:
        from circle.web3 import developer_controlled_wallets, utils
    except ImportError as exc:
        raise PlatformOwnerWalletError(
            "Circle developer-controlled wallet SDK is not installed."
        ) from exc

    try:
        client = utils.init_developer_controlled_wallets_client(
            api_key=api_key,
            entity_secret=entity_secret,
        )
        wallet_sets = developer_controlled_wallets.WalletSetsApi(client)
        wallets = developer_controlled_wallets.WalletsApi(client)

        wallet_set_response = wallet_sets.create_wallet_set(
            developer_controlled_wallets.CreateWalletSetRequest.from_dict(
                {
                    "name": getattr(
                        settings,
                        "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_SET_NAME",
                        "Veyra Platform Contract Owner",
                    )
                }
            )
        )
        wallet_set_id = _extract_wallet_set_id(wallet_set_response)

        wallet_response = wallets.create_wallet(
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
    except PlatformOwnerWalletError:
        raise
    except Exception as exc:
        raise PlatformOwnerWalletError(
            "Circle platform-owner wallet creation failed: "
            + _safe_message(exc, api_key, entity_secret)
        ) from exc

    return PlatformOwnerWalletResult(
        wallet_set_id=wallet_set_id,
        wallet_id=wallet["id"],
        address=wallet["address"],
        blockchain=wallet["blockchain"],
        account_type=wallet["account_type"],
        created=True,
    )


def _upsert_env_value(content: str, name: str, value: str) -> str:
    line = f"{name}={value}"
    pattern = re.compile(rf"(?m)^{re.escape(name)}=.*$")
    if pattern.search(content):
        return pattern.sub(line, content)
    if content and not content.endswith("\n"):
        content += "\n"
    return content + line + "\n"


def persist_platform_owner_wallet_to_env(
    result: PlatformOwnerWalletResult,
) -> tuple[Path, Path]:
    env_path = Path(settings.BASE_DIR) / ".env"
    if not env_path.exists():
        raise PlatformOwnerWalletError(f"Backend .env was not found at {env_path}.")

    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup_path = env_path.with_name(f".env.before-platform-owner-{timestamp}")
    shutil.copy2(env_path, backup_path)

    content = env_path.read_text(encoding="utf-8-sig")
    content = _upsert_env_value(
        content,
        "VEYRA_CONTRACT_OWNER_CIRCLE_WALLET_ID",
        result.wallet_id,
    )
    content = _upsert_env_value(
        content,
        "VEYRA_CONTRACT_OWNER_WALLET_ADDRESS",
        result.address,
    )
    env_path.write_text(content, encoding="utf-8")
    return env_path, backup_path
