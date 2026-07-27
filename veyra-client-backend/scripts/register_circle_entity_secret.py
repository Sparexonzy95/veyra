from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from dotenv import load_dotenv
from circle.web3 import utils


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"
RECOVERY_DIR = Path.home() / "Veyra-Secrets" / "circle-recovery"


def _read_env() -> str:
    if not ENV_FILE.exists():
        raise RuntimeError(f"Backend .env file was not found: {ENV_FILE}")
    return ENV_FILE.read_text(encoding="utf-8-sig")


def _has_entity_secret(text: str) -> bool:
    match = re.search(
        r"^\s*CIRCLE_ENTITY_SECRET\s*=\s*(.*?)\s*$",
        text,
        flags=re.MULTILINE,
    )
    return bool(match and match.group(1).strip().strip("'\""))


def _append_entity_secret(entity_secret: str) -> None:
    current = _read_env()
    prefix = "" if current.endswith(("\n", "\r")) else "\n"
    with ENV_FILE.open("a", encoding="utf-8", newline="\n") as env_file:
        env_file.write(f"{prefix}CIRCLE_ENTITY_SECRET={entity_secret}\n")


def main() -> None:
    current_env = _read_env()
    if _has_entity_secret(current_env):
        raise RuntimeError(
            "CIRCLE_ENTITY_SECRET already exists in the backend .env. "
            "Refusing to generate or overwrite it."
        )

    load_dotenv(ENV_FILE, override=False)
    api_key = (os.environ.get("CIRCLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            f"CIRCLE_API_KEY is missing from {ENV_FILE}. "
            "Add the Circle Standard API key before running this script."
        )

    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)

    # 32 random bytes represented as 64 lowercase hexadecimal characters.
    entity_secret = secrets.token_hex(32)

    # Registration must succeed before the secret is written to .env.
    utils.register_entity_secret_ciphertext(
        api_key=api_key,
        entity_secret=entity_secret,
        recoveryFileDownloadPath=str(RECOVERY_DIR),
    )

    _append_entity_secret(entity_secret)

    print("Circle entity secret registered successfully.")
    print(f"Backend .env updated: {ENV_FILE}")
    print(f"Recovery file directory: {RECOVERY_DIR}")
    print("The entity secret was not printed.")
    print("Keep the recovery file private and store a second encrypted backup.")


if __name__ == "__main__":
    main()