from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct


RUNNER_VERSION = "0.1.0"
SIGNATURE_VERSION = "VEYRA-RUNNER-V1"
PAIRING_SIGNATURE_VERSION = "VEYRA-RUNNER-PAIR-V1"
DEFAULT_SERVER = "http://localhost:8000"
DEFAULT_INTERVAL = 10


def runner_home() -> Path:
    return Path(os.environ.get("VEYRA_RUNNER_HOME", Path.home() / ".veyra")).expanduser()


def config_path() -> Path:
    return runner_home() / "runner.local.json"


def key_path() -> Path:
    return runner_home() / "device.key"


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create_device() -> tuple[str, str]:
    path = key_path()
    if path.exists():
        private_key = path.read_text(encoding="utf-8").strip()
        account = Account.from_key(private_key)
        return private_key, account.address

    account = Account.create()
    private_key = account.key.hex()
    _write_private(path, private_key)
    return private_key, account.address


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"bindings": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Runner configuration is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Runner configuration must be an object.")
    if not isinstance(data.get("bindings", []), list):
        data["bindings"] = []
    return data


def save_config(data: dict[str, Any]) -> None:
    _write_private(config_path(), json.dumps(data, indent=2, sort_keys=True))


def command_version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
        )
    except (OSError, subprocess.SubprocessError):
        return "not detected"
    output = (result.stdout or result.stderr or "").strip().splitlines()
    return output[0][:80] if output else "not detected"


def environment_summary() -> dict[str, Any]:
    return {
        "os_name": platform.system(),
        "os_version": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "tools": {
            "git": command_version(["git", "--version"]),
            "python": platform.python_version(),
            "node": command_version(["node", "--version"]),
            "npm": command_version(["npm", "--version"]),
            "pytest": command_version([sys.executable, "-m", "pytest", "--version"]),
            "docker": command_version(["docker", "--version"]),
        },
    }


def canonical_pairing_message(*, code: str, device_address: str, runner_name: str) -> str:
    normalised_code = "".join(ch for ch in code.upper() if ch.isalnum())
    return "\n".join(
        [
            PAIRING_SIGNATURE_VERSION,
            normalised_code,
            device_address.lower(),
            runner_name.strip(),
        ]
    )


def canonical_message(*, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    return "\n".join(
        [
            SIGNATURE_VERSION,
            method.upper(),
            path,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        ]
    )


def signed_headers(*, private_key: str, runner_id: str, method: str, path: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    message = canonical_message(
        method=method,
        path=path,
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    signature = Account.sign_message(
        encode_defunct(text=message),
        private_key,
    ).signature.hex()
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Veyra-Runner-ID": runner_id,
        "X-Veyra-Timestamp": timestamp,
        "X-Veyra-Nonce": nonce,
        "X-Veyra-Signature": signature,
    }


def validate_server_url(raw: str) -> str:
    value = raw.rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Server URL must begin with http:// or https://")
    return value


def pair(args: argparse.Namespace) -> int:
    server = validate_server_url(args.server)
    code = getpass.getpass("Enter the one-time pairing code shown in Veyra: ").strip()
    if not code:
        raise RuntimeError("Pairing code is required.")

    private_key, device_address = load_or_create_device()
    proof_message = canonical_pairing_message(
        code=code,
        device_address=device_address,
        runner_name=args.name,
    )
    device_signature = Account.sign_message(
        encode_defunct(text=proof_message),
        private_key,
    ).signature.hex()
    payload = {
        "code": code,
        "device_address": device_address,
        "device_signature": device_signature,
        "runner_name": args.name,
        "runner_version": RUNNER_VERSION,
        "environment": environment_summary(),
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(f"{server}/api/v1/runner/pair/", json=payload)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Pairing failed ({response.status_code}): {detail}")

    data = response.json()
    config = load_config()
    binding = data["agent"]
    bindings = [item for item in config.get("bindings", []) if item.get("id") != binding["id"]]
    bindings.append({"id": binding["id"], "name": binding["name"]})
    config.update(
        {
            "server_url": server,
            "runner_id": data["runner_id"],
            "runner_name": args.name,
            "device_address": device_address,
            "bindings": bindings,
        }
    )
    save_config(config)
    print(f"Paired successfully with agent: {binding['name']}")
    print("Start Veyra Runner to send the first signed heartbeat.")
    return 0


def heartbeat_once(config: dict[str, Any], private_key: str) -> dict[str, Any]:
    server = validate_server_url(config.get("server_url", ""))
    runner_id = str(config.get("runner_id", ""))
    if not runner_id:
        raise RuntimeError("Runner is not paired. Run the pair command first.")
    agent_ids = [str(item.get("id")) for item in config.get("bindings", []) if item.get("id")]
    if not agent_ids:
        raise RuntimeError("Runner has no paired agents.")

    path = "/api/v1/runner/heartbeat/"
    payload = {
        "runner_version": RUNNER_VERSION,
        "health": "HEALTHY",
        "health_message": "",
        "environment": environment_summary(),
        "agent_ids": agent_ids,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = signed_headers(
        private_key=private_key,
        runner_id=runner_id,
        method="POST",
        path=path,
        body=body,
    )
    with httpx.Client(timeout=20) as client:
        response = client.post(f"{server}{path}", content=body, headers=headers)
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Heartbeat rejected ({response.status_code}): {detail}")
    return response.json()


def start(args: argparse.Namespace) -> int:
    private_key, _ = load_or_create_device()
    config = load_config()
    interval = max(5, args.interval)
    print(f"Veyra Runner {RUNNER_VERSION} started.")
    print(f"Paired agents: {len(config.get('bindings', []))}")
    while True:
        result = heartbeat_once(config, private_key)
        names = ", ".join(agent.get("name", "Agent") for agent in result.get("agents", []))
        print(f"Heartbeat accepted at {time.strftime('%H:%M:%S')} — {names or 'no active bindings'}")
        if args.once:
            return 0
        time.sleep(interval)


def status_command(args: argparse.Namespace) -> int:
    config = load_config()
    _, device_address = load_or_create_device()
    print(f"Runner version: {RUNNER_VERSION}")
    print(f"Device identity: {device_address[:8]}…{device_address[-6:]}")
    print(f"Server: {config.get('server_url', 'Not paired')}")
    print(f"Runner ID: {config.get('runner_id', 'Not paired')}")
    bindings = config.get("bindings", [])
    if bindings:
        print("Paired agents:")
        for binding in bindings:
            print(f"  - {binding.get('name', 'Agent')} ({binding.get('id', '')})")
    else:
        print("Paired agents: none")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secure connector for owner-hosted Veyra agents.")
    sub = parser.add_subparsers(dest="command", required=True)

    pair_parser = sub.add_parser("pair", help="Pair this Runner with an agent using a one-time code.")
    pair_parser.add_argument("--server", default=DEFAULT_SERVER)
    pair_parser.add_argument("--name", default=f"{platform.node() or 'Local'} Runner")
    pair_parser.set_defaults(func=pair)

    start_parser = sub.add_parser("start", help="Start signed Runner heartbeats.")
    start_parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    start_parser.add_argument("--once", action="store_true", help="Send one heartbeat and exit.")
    start_parser.set_defaults(func=start)

    status_parser = sub.add_parser("status", help="Show local pairing information.")
    status_parser.set_defaults(func=status_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Runner stopped.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
