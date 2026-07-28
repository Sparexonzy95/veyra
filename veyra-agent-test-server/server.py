from __future__ import annotations

import base64
from fnmatch import fnmatchcase
import html
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
# Capture path overrides before loading .env. This prevents a stale value inside
# .env from redirecting the runtime to a different identity/state directory.
ENV_FILE_OVERRIDE = os.environ.get("VEYRA_RUNTIME_ENV_FILE")
STATE_DIR_OVERRIDE = os.environ.get("VEYRA_RUNTIME_STATE_DIR")
ENV_FILE = Path(ENV_FILE_OVERRIDE or (ROOT / ".env")).resolve()
load_dotenv(ENV_FILE)
STATE_DIR = Path(STATE_DIR_OVERRIDE or (ROOT / ".veyra-runtime")).resolve()
STATE_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACE_ROOT_OVERRIDE = os.environ.get("VEYRA_RUNTIME_WORKSPACE_ROOT")
WORKSPACE_ROOT = Path(
    WORKSPACE_ROOT_OVERRIDE
    or (
        Path(tempfile.gettempdir())
        / "veyra-runtime-workspaces"
        / hashlib.sha256(str(STATE_DIR).encode("utf-8")).hexdigest()[:16]
    )
).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "state.json"
PRIVATE_KEY_PATH = STATE_DIR / "ed25519-private.pem"

HOST = os.getenv("RUNTIME_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("RUNTIME_PORT", "9100"))
PUBLIC_HOST = os.getenv("RUNTIME_PUBLIC_HOST", "localhost").strip() or "localhost"
PUBLIC_PORT = os.getenv("RUNTIME_PUBLIC_PORT", str(PORT)).strip()
RUNTIME_ROLE = os.getenv("VEYRA_RUNTIME_ROLE", "WORKER").strip().upper() or "WORKER"
if RUNTIME_ROLE not in {"WORKER", "VERIFIER"}:
    raise RuntimeError("VEYRA_RUNTIME_ROLE must be WORKER or VERIFIER.")
RUNTIME_VERSION = f"veyra-owner-runtime-{RUNTIME_ROLE.lower()}/1.1.3-git-path-parser"
PROTOCOL_VERSION = 1
TOKEN_TTL_SECONDS = 24 * 60 * 60
HEARTBEAT_SECONDS = max(5, int(os.getenv("VEYRA_HEARTBEAT_SECONDS", "10")))

AI_PROVIDER = os.getenv("AI_PROVIDER", "aiand").strip()
AI_MODEL = os.getenv("AI_MODEL", "zai-org/glm-5.2").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.aiand.com/v1").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_HEALTHCHECK_MODE = os.getenv("AI_HEALTHCHECK_MODE", "live").strip().lower()
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")

STATE_LOCK = threading.RLock()
HEARTBEAT_STARTED = False
QUALIFICATION_LOCK = threading.RLock()
QUALIFICATION_RUNNING: set[str] = set()
JOB_LOCK = threading.RLock()
JOB_RUNNING: set[str] = set()
VERIFICATION_LOCK = threading.RLock()
VERIFICATION_RUNNING: set[str] = set()
PROVIDER_CACHE: dict[str, Any] = {"checked_at": 0.0, "ready": False, "message": "Not checked"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _public_key_text(private_key: Ed25519PrivateKey) -> str:
    return b64url(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def _new_state(public_key: str) -> dict[str, Any]:
    issued_at = int(time.time())
    return {
        "runtime_id": f"runtime-{uuid.uuid4()}",
        "signing_public_key": public_key,
        "one_time_token": secrets.token_urlsafe(36),
        "token_issued_at": issued_at,
        "token_expires_at": issued_at + TOKEN_TTL_SECONDS,
        "token_consumed": False,
        "revoked_token_hashes": [],
        "agent_id": "",
        "agent_name": "",
        "runtime_credential": "",
        "heartbeat_url": "",
        "configuration_url": "",
        "agent_configuration": {},
        "connected_at": "",
        "last_heartbeat_at": "",
        "last_heartbeat_error": "",
        "qualification_id": "",
        "qualification_status": "waiting",
        "qualification_message": "Waiting for Veyra",
        "qualification_updated_at": "",
        "job_assignment_id": "",
        "job_lease_id": "",
        "job_assignment_attempt": 0,
        "job_onchain_id": "",
        "job_status": "waiting",
        "job_message": "Waiting for paid work",
        "job_updated_at": "",
        "verification_assignment_id": "",
        "verification_status": "waiting",
        "verification_message": "Waiting for a submitted worker job",
        "verification_updated_at": "",
    }


def default_state() -> dict[str, Any]:
    return _new_state(PUBLIC_KEY_TEXT)


def _protect_private_path(path: Path, *, directory: bool = False) -> None:
    try:
        path.chmod(0o700 if directory else 0o600)
        if os.name == "nt":
            permission = "(OI)(CI)F" if directory else "F"
            principal = subprocess.run(
                ["whoami"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not principal:
                raise RuntimeError("Unable to determine the current Windows account.")
            subprocess.run(
                [
                    "icacls",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{principal}:{permission}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception as exc:
        raise RuntimeError(
            f"Unable to restrict access to private runtime path {path}."
        ) from exc


def _read_state_file() -> dict[str, Any]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(state, dict):
            raise ValueError("Runtime state root must be a JSON object.")
    except Exception as exc:
        raise RuntimeError(
            f"Unable to read Veyra runtime state at {STATE_PATH}. "
            "The file was preserved and was not replaced."
        ) from exc
    return state


def _validate_state_identity(
    state: dict[str, Any],
    *,
    expected_public_key: str | None = None,
) -> None:
    runtime_id = state.get("runtime_id")
    token = state.get("one_time_token")
    try:
        if not isinstance(runtime_id, str) or not runtime_id.startswith("runtime-"):
            raise ValueError("runtime_id is missing or invalid")
        uuid.UUID(runtime_id.removeprefix("runtime-"))
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("one_time_token is missing or invalid")
        if not isinstance(state.get("token_expires_at"), int):
            raise ValueError("token_expires_at is missing or invalid")
        if not isinstance(state.get("token_consumed"), bool):
            raise ValueError("token_consumed is missing or invalid")
        issued_at = state.get("token_issued_at")
        if issued_at is not None and not isinstance(issued_at, int):
            raise ValueError("token_issued_at is invalid")
        revoked_hashes = state.get("revoked_token_hashes")
        if revoked_hashes is not None and (
            not isinstance(revoked_hashes, list)
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in revoked_hashes
            )
        ):
            raise ValueError("revoked_token_hashes is invalid")
        public_key = state.get("signing_public_key")
        if public_key is not None and (
            not isinstance(public_key, str) or not public_key
        ):
            raise ValueError("signing_public_key is invalid")
        if expected_public_key and public_key not in {None, expected_public_key}:
            raise ValueError("state does not match the runtime signing key")
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Veyra runtime state at {STATE_PATH} is corrupt or incomplete. "
            "The file was preserved and the identity was not regenerated."
        ) from exc


def _load_private_key() -> Ed25519PrivateKey:
    try:
        private_key = serialization.load_pem_private_key(
            PRIVATE_KEY_PATH.read_bytes(),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Signing key is not Ed25519.")
        return private_key
    except Exception as exc:
        raise RuntimeError(
            f"Veyra signing identity at {PRIVATE_KEY_PATH} is corrupt. "
            "It was preserved and was not regenerated."
        ) from exc


def _write_new_identity(
    state: dict[str, Any],
    private_key: Ed25519PrivateKey,
) -> None:
    key_temporary = STATE_DIR / f".ed25519-private-{uuid.uuid4().hex}.tmp"
    state_temporary = STATE_DIR / f".state-{uuid.uuid4().hex}.tmp"
    try:
        key_temporary.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        # Explicit UTF-8 bytes guarantee that state.json never receives a BOM.
        state_temporary.write_bytes(json.dumps(state, indent=2).encode("utf-8"))
        if os.name != "nt":
            _protect_private_path(key_temporary)
            _protect_private_path(state_temporary)
        if PRIVATE_KEY_PATH.exists() or STATE_PATH.exists():
            raise RuntimeError(
                "Another process created runtime identity files during initialization."
            )
        key_temporary.replace(PRIVATE_KEY_PATH)
        _protect_private_path(PRIVATE_KEY_PATH)
        state_temporary.replace(STATE_PATH)
        _protect_private_path(STATE_PATH)
    finally:
        key_temporary.unlink(missing_ok=True)
        state_temporary.unlink(missing_ok=True)


def initialize_runtime_identity() -> tuple[dict[str, Any], Ed25519PrivateKey]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_exists = STATE_PATH.exists()
    key_exists = PRIVATE_KEY_PATH.exists()

    if state_exists != key_exists:
        raise RuntimeError(
            f"Veyra runtime identity at {STATE_DIR} is incomplete. "
            "Existing private files were preserved and no identity was regenerated."
        )

    if state_exists:
        state = _read_state_file()
        _validate_state_identity(state)
        private_key = _load_private_key()
        public_key = _public_key_text(private_key)
        _validate_state_identity(state, expected_public_key=public_key)
        _protect_private_path(STATE_DIR, directory=True)
        _protect_private_path(STATE_PATH)
        _protect_private_path(PRIVATE_KEY_PATH)
        return state, private_key

    private_key = Ed25519PrivateKey.generate()
    state = _new_state(_public_key_text(private_key))
    _write_new_identity(state, private_key)
    _protect_private_path(STATE_DIR, directory=True)
    return state, private_key


INITIAL_STATE, PRIVATE_KEY = initialize_runtime_identity()
PUBLIC_KEY_TEXT = _public_key_text(PRIVATE_KEY)


def load_state() -> dict[str, Any]:
    with STATE_LOCK:
        if not STATE_PATH.exists():
            raise RuntimeError(
                f"Veyra runtime state at {STATE_PATH} disappeared after startup. "
                "No replacement identity was generated."
            )
        state = _read_state_file()
        _validate_state_identity(state, expected_public_key=PUBLIC_KEY_TEXT)
        required = default_state()
        for key, value in required.items():
            state.setdefault(key, value)
        return state


def save_state(state: dict[str, Any]) -> None:
    with STATE_LOCK:
        _validate_state_identity(state, expected_public_key=PUBLIC_KEY_TEXT)
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_bytes(json.dumps(state, indent=2).encode("utf-8"))
        if os.name != "nt":
            _protect_private_path(temporary)
        temporary.replace(STATE_PATH)
        _protect_private_path(STATE_PATH)


def rotate_connection_token() -> dict[str, Any]:
    with STATE_LOCK:
        state = load_state()
        if state.get("runtime_credential"):
            raise RuntimeError("Disconnect the existing Veyra agent before generating another link.")
        current_token = str(state.get("one_time_token") or "")
        revoked_hashes = list(state.get("revoked_token_hashes") or [])
        if current_token:
            revoked_hashes.append(token_digest(current_token))
        issued_at = int(time.time())
        state["one_time_token"] = secrets.token_urlsafe(36)
        state["token_issued_at"] = issued_at
        state["token_expires_at"] = issued_at + TOKEN_TTL_SECONDS
        state["token_consumed"] = False
        state["revoked_token_hashes"] = list(dict.fromkeys(revoked_hashes))[-20:]
        save_state(state)
        return state


def public_netloc() -> str:
    if not PUBLIC_PORT or PUBLIC_PORT in {"80", "443"}:
        return PUBLIC_HOST
    return f"{PUBLIC_HOST}:{PUBLIC_PORT}"


def connection_link(state: dict[str, Any] | None = None) -> str:
    current = state or load_state()
    return (
        f"veyra-connect://{public_netloc()}/connect/"
        f"{current['one_time_token']}?protocol={PROTOCOL_VERSION}"
    )


def token_digest(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def connection_link_expiry(state: dict[str, Any]) -> str:
    expires_at = int(state.get("token_expires_at") or 0)
    return (
        datetime.fromtimestamp(expires_at, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def provider_health(*, force: bool = False) -> tuple[bool, str]:
    now = time.time()
    if not force and now - float(PROVIDER_CACHE["checked_at"]) < 30:
        return bool(PROVIDER_CACHE["ready"]), str(PROVIDER_CACHE["message"])

    if AI_HEALTHCHECK_MODE == "mock":
        ready, message = True, "Mock provider health enabled for local connector testing."
    elif not AI_API_KEY or AI_API_KEY == "PASTE_OWNER_PAID_KEY_HERE":
        ready, message = False, "Add the owner-paid AI_API_KEY to veyra-agent-test-server/.env."
    else:
        try:
            response = httpx.get(
                f"{AI_BASE_URL}/models",
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
                timeout=15,
                follow_redirects=False,
            )
            ready = response.status_code == 200
            message = (
                f"Provider reachable ({response.status_code})."
                if ready
                else f"Provider rejected the health check ({response.status_code})."
            )
        except Exception as exc:
            ready, message = False, f"Provider health check failed: {str(exc)[:180]}"

    PROVIDER_CACHE.update({"checked_at": now, "ready": ready, "message": message})
    return ready, message


def token_is_valid(state: dict[str, Any], token: str) -> tuple[bool, str]:
    supplied_token = str(token or "")
    current_token = str(state.get("one_time_token") or "")
    if secrets.compare_digest(current_token, supplied_token):
        if state.get("token_consumed"):
            return False, "This connection link has already been used."
        if int(state.get("token_expires_at") or 0) <= int(time.time()):
            return False, "This connection link has expired. Generate a new one."
        return True, ""
    supplied_digest = token_digest(supplied_token)
    if any(
        secrets.compare_digest(value, supplied_digest)
        for value in state.get("revoked_token_hashes") or []
    ):
        return False, "This connection link was revoked when a newer link was generated."
    return False, "This connection link is invalid."


def refresh_agent_configuration(state: dict[str, Any]) -> None:
    credential = str(state.get("runtime_credential") or "")
    configuration_url = str(state.get("configuration_url") or "")
    agent_id = str(state.get("agent_id") or "")
    if not credential or not configuration_url or not agent_id:
        return
    try:
        response = httpx.get(
            configuration_url,
            headers={
                "Authorization": f"Bearer {credential}",
                "X-Veyra-Agent-ID": agent_id,
            },
            timeout=15,
            follow_redirects=False,
        )
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict):
                with STATE_LOCK:
                    current = load_state()
                    current["agent_configuration"] = payload
                    save_state(current)
    except Exception:
        # Heartbeats remain the source of connection health. Configuration is
        # retried later and a temporary Veyra startup race is harmless.
        return



def _safe_runtime_text(value: Any, *, limit: int = 12000) -> str:
    text = str(value or "").strip()
    if AI_API_KEY:
        text = text.replace(AI_API_KEY, "[REDACTED]")
    return text[:limit]


def _qualification_workspace(qualification_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", qualification_id)[:80]
    return WORKSPACE_ROOT / "qualification" / safe_id


def _write_starter_files(workspace: Path, files: list[dict[str, Any]]) -> None:
    if workspace.exists():
        _remove_workspace(workspace, strict=True)
    workspace.mkdir(parents=True, exist_ok=True)
    for item in files:
        path = str(item.get("path") or "").replace("\\", "/").strip().lstrip("/")
        if not path or ".." in Path(path).parts or path.startswith(".git/"):
            raise RuntimeError("Veyra sent an unsafe qualification file path.")
        destination = (workspace / path).resolve()
        if workspace.resolve() not in destination.parents:
            raise RuntimeError("Veyra sent an unsafe qualification file path.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(item.get("content") or ""), encoding="utf-8")


def _extract_json_object(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("The AI model did not return the required JSON result.")
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise RuntimeError("The AI model returned an invalid qualification result.")
    return payload


def _run_owner_model(task: dict[str, Any]) -> list[dict[str, str]]:
    if not AI_API_KEY or AI_API_KEY == "PASTE_OWNER_PAID_KEY_HERE":
        raise RuntimeError("The owner-paid AI_API_KEY is not configured.")

    starter = task.get("starter_files") or []
    prompt = (
        "You are completing a controlled Veyra coding qualification. "
        "Return JSON only, with this exact shape: "
        '{"files":[{"path":"app.py","content":"complete Python source"}]}.\n\n'
        + str(task.get("instructions") or "")
        + "\n\nStarter files:\n"
        + json.dumps(starter, ensure_ascii=False, indent=2)
    )
    response = httpx.post(
        f"{AI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON. Do not include markdown fences or explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        },
        timeout=120,
        follow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"The owner AI provider returned {response.status_code}."
        )
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("The AI provider returned no qualification answer.")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else ""
    result = _extract_json_object(str(content or ""))
    files = result.get("files")
    if not isinstance(files, list):
        raise RuntimeError("The AI model returned no files.")

    cleaned: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/").strip().lstrip("/")
        content = str(item.get("content") or "")
        if path == "app.py":
            cleaned.append({"path": path, "content": content})
    if [item["path"] for item in cleaned] != ["app.py"]:
        raise RuntimeError("The AI model must return app.py only.")
    return cleaned


def _qualification_signature(
    qualification_id: str,
    files: list[dict[str, str]],
    test_return_code: int,
) -> str:
    canonical = json.dumps(
        files,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    files_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    message = (
        f"veyra-qualification-v1:{qualification_id}:{files_hash}:{int(test_return_code)}"
    ).encode("utf-8")
    return b64url(PRIVATE_KEY.sign(message))


def _submit_qualification(
    task: dict[str, Any],
    *,
    files: list[dict[str, str]] | None = None,
    return_code: int = 1,
    test_output: str = "",
    runtime_error: str = "",
) -> dict[str, Any]:
    state = load_state()
    credential = str(state.get("runtime_credential") or "")
    agent_id = str(state.get("agent_id") or "")
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "qualification_id": str(task.get("id") or ""),
        "lease_token": str(task.get("lease_token") or ""),
        "provider": AI_PROVIDER,
        "model": AI_MODEL,
        "runtime_version": RUNTIME_VERSION,
    }
    if runtime_error:
        payload["runtime_error"] = _safe_runtime_text(runtime_error, limit=1200)
    else:
        submitted = files or []
        payload.update(
            {
                "files": submitted,
                "test_return_code": int(return_code),
                "test_output": _safe_runtime_text(test_output),
                "signature": _qualification_signature(
                    str(task.get("id") or ""),
                    submitted,
                    int(return_code),
                ),
            }
        )
    response = httpx.post(
        str(task.get("submit_url") or ""),
        headers={
            "Authorization": f"Bearer {credential}",
            "X-Veyra-Agent-ID": agent_id,
        },
        json=payload,
        timeout=30,
        follow_redirects=False,
    )
    try:
        response_payload = response.json()
    except Exception:
        response_payload = {}
    if response.status_code != 200:
        raise RuntimeError(
            str(response_payload.get("detail") or f"Veyra returned {response.status_code}.")
        )
    return response_payload


def run_qualification_task(task: dict[str, Any]) -> None:
    qualification_id = str(task.get("id") or "")
    with STATE_LOCK:
        state = load_state()
        state["qualification_id"] = qualification_id
        state["qualification_status"] = "running"
        state["qualification_message"] = "Owner model is completing the automatic qualification."
        state["qualification_updated_at"] = utc_now_iso()
        save_state(state)

    try:
        workspace = _qualification_workspace(qualification_id)
        _write_starter_files(workspace, list(task.get("starter_files") or []))
        files = _run_owner_model(task)
        for item in files:
            (workspace / item["path"]).write_text(item["content"], encoding="utf-8")

        command = [sys.executable, "-m", "pytest", "-q"]
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120,
            env={
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "TEMP": os.environ.get("TEMP", ""),
                "TMP": os.environ.get("TMP", ""),
                "USERPROFILE": os.environ.get("USERPROFILE", ""),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            check=False,
        )
        output = "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip()
        result = _submit_qualification(
            task,
            files=files,
            return_code=completed.returncode,
            test_output=output,
        )
        passed = bool(result.get("passed"))
        with STATE_LOCK:
            state = load_state()
            state["qualification_status"] = "passed" if passed else "failed"
            state["qualification_message"] = (
                "Automatic qualification passed."
                if passed
                else "Automatic qualification did not pass."
            )
            state["qualification_updated_at"] = utc_now_iso()
            save_state(state)
    except Exception as exc:
        message = _safe_runtime_text(exc, limit=800)
        try:
            _submit_qualification(task, runtime_error=message)
        except Exception as submit_exc:
            message = f"{message}; result delivery failed: {_safe_runtime_text(submit_exc, limit=300)}"
        with STATE_LOCK:
            state = load_state()
            state["qualification_status"] = "failed"
            state["qualification_message"] = message
            state["qualification_updated_at"] = utc_now_iso()
            save_state(state)
    finally:
        with QUALIFICATION_LOCK:
            QUALIFICATION_RUNNING.discard(qualification_id)


def ensure_qualification_thread(task: dict[str, Any]) -> None:
    qualification_id = str(task.get("id") or "").strip()
    if not qualification_id:
        return
    with QUALIFICATION_LOCK:
        if qualification_id in QUALIFICATION_RUNNING:
            return
        state = load_state()
        if (
            str(state.get("qualification_id") or "") == qualification_id
            and str(state.get("qualification_status") or "") == "passed"
        ):
            return
        QUALIFICATION_RUNNING.add(qualification_id)
    threading.Thread(
        target=run_qualification_task,
        args=(task,),
        name=f"veyra-qualification-{qualification_id[:8]}",
        daemon=True,
    ).start()




def _job_workspace(assignment_id: str, lease_id: str) -> Path:
    """Return an isolated workspace for one assignment lease.

    An assignment can be retried with a new lease after a provider, machine, or
    network failure. Reusing only the assignment ID makes the retry depend on
    deleting the previous Git worktree first, which is unreliable on Windows
    when antivirus or Git still has a pack index open. A lease-scoped path makes
    every retry start clean without touching the previous attempt.
    """
    safe_assignment = re.sub(r"[^A-Za-z0-9_.-]", "", assignment_id)[:64]
    safe_lease = re.sub(r"[^A-Za-z0-9_.-]", "", lease_id)[:64]
    if not safe_assignment or not safe_lease:
        raise RuntimeError("A paid job workspace requires assignment and lease IDs.")
    return WORKSPACE_ROOT / "jobs" / f"{safe_assignment}--{safe_lease}"


def _make_path_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    except OSError:
        pass


def _rmtree_onerror(function: Any, path: str, exc_info: Any) -> None:
    """Retry one shutil.rmtree operation after clearing Windows read-only bits."""
    target = Path(path)
    _make_path_writable(target)
    try:
        function(path)
    except OSError:
        # Let shutil surface the original cleanup failure to the outer retry loop.
        raise


def _remove_workspace(workspace: Path, *, strict: bool = False) -> bool:
    """Remove a workspace with Windows-safe retries.

    Cleanup is best-effort after a finished attempt. Before cloning into an
    already-existing lease path it is strict, because continuing would mix two
    executions.
    """
    if not workspace.exists() and not workspace.is_symlink():
        return True

    last_error: OSError | None = None
    attempts = max(2, int(os.getenv("VEYRA_WORKSPACE_DELETE_ATTEMPTS", "6")))
    delay = max(0.05, float(os.getenv("VEYRA_WORKSPACE_DELETE_DELAY_SECONDS", "0.25")))

    for attempt in range(attempts):
        try:
            if workspace.is_symlink():
                workspace.unlink()
            else:
                shutil.rmtree(workspace, onerror=_rmtree_onerror)
            return True
        except FileNotFoundError:
            return True
        except OSError as exc:
            last_error = exc
            try:
                for child in workspace.rglob("*"):
                    _make_path_writable(child)
                _make_path_writable(workspace)
            except OSError:
                pass
            time.sleep(delay * (attempt + 1))

    if strict:
        raise RuntimeError(
            "Veyra could not prepare a clean job workspace after "
            f"{attempts} attempts: {workspace}. Last error: {last_error}"
        )
    return False


def _safe_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip().lstrip("/")
    if not path or ".." in Path(path).parts or path.startswith(".git/"):
        raise RuntimeError("The job attempted to use an unsafe repository path.")
    return path


class ModelOutputPolicyError(RuntimeError):
    """The model proposed a file path that violates the funded job policy."""


def _path_matches_policy_rule(path: str, rule: str) -> bool:
    """Match exact paths, directory prefixes, and common recursive globs safely."""
    clean_path = path.replace("\\", "/").casefold().strip("/")
    clean_rule = rule.replace("\\", "/").casefold().strip("/")
    if not clean_path or not clean_rule:
        return False
    if clean_rule.endswith("/**"):
        prefix = clean_rule[:-3].rstrip("/")
        return bool(prefix) and (clean_path == prefix or clean_path.startswith(prefix + "/"))
    if any(marker in clean_rule for marker in ("*", "?", "[")):
        return fnmatchcase(clean_path, clean_rule)
    return clean_path == clean_rule or clean_path.startswith(clean_rule + "/")


def _enforce_job_path_policy(task: dict[str, Any], paths: list[str]) -> None:
    policy = task.get("policy") if isinstance(task.get("policy"), dict) else {}
    forbidden = [
        _safe_path(value)
        for value in list(policy.get("forbidden_paths") or [])
        if str(value or "").strip()
    ]
    forbidden.extend([".env", ".git", ".github/workflows"])
    allowed = [
        _safe_path(value)
        for value in list(policy.get("allowed_paths") or [])
        if str(value or "").strip()
    ]
    for path in paths:
        try:
            selected = _safe_path(path)
        except RuntimeError as exc:
            raise ModelOutputPolicyError(str(exc)) from exc
        basename = selected.rsplit("/", 1)[-1].casefold()
        if basename == ".env" or basename.startswith(".env."):
            raise ModelOutputPolicyError(
                f"The model attempted to change protected environment path: {selected}"
            )
        if any(_path_matches_policy_rule(selected, prefix) for prefix in forbidden):
            raise ModelOutputPolicyError(f"The model attempted to change protected path: {selected}")
        if allowed and not any(_path_matches_policy_rule(selected, prefix) for prefix in allowed):
            allowed_text = ", ".join(allowed)
            raise ModelOutputPolicyError(
                "The model attempted to change a path outside the funded policy: "
                f"{selected}. Allowed paths: {allowed_text}"
            )
        lower = selected.casefold()
        if not bool(policy.get("allow_new_dependencies")) and Path(lower).name in {
            "requirements.txt", "pyproject.toml", "package.json", "package-lock.json",
            "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
        }:
            raise ModelOutputPolicyError(f"Dependency changes are disabled by policy: {selected}")
        if not bool(policy.get("allow_database_migrations")) and (
            "/migrations/" in f"/{lower}/" or lower.startswith("migrations/")
        ):
            raise ModelOutputPolicyError(f"Database migrations are disabled by policy: {selected}")


def _credential_headers(token: str) -> dict[str, str]:
    basic = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run_process(
    args: list[str],
    *,
    cwd: Path,
    timeout: int,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    # Repository-controlled test code must never inherit the runtime's provider
    # key, Veyra credential, connection token, or user-level credential paths.
    # This is defense in depth; it is not a replacement for an OS sandbox.
    env = {
        key: os.environ[key]
        for key in (
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
        )
        if os.environ.get(key)
    }
    env.update(
        {
            "HOME": str(cwd),
            "USERPROFILE": str(cwd),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    return completed


def _git(
    workspace: Path,
    *args: str,
    token: str = "",
    timeout: int = 120,
    expected: tuple[int, ...] = (0,),
) -> str:
    extra = _credential_headers(token) if token else None
    completed = _run_process(["git", *args], cwd=workspace, timeout=timeout, extra_env=extra)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode not in expected:
        raise RuntimeError(f"Git command failed: {_safe_runtime_text(output, limit=1200)}")
    return output


def _repository_credential(task: dict[str, Any]) -> dict[str, Any]:
    state = load_state()
    credential = str(state.get("runtime_credential") or "")
    agent_id = str(state.get("agent_id") or "")
    response = httpx.post(
        str(task.get("credential_url") or ""),
        headers={
            "Authorization": f"Bearer {credential}",
            "X-Veyra-Agent-ID": agent_id,
        },
        json={
            "agent_id": agent_id,
            "assignment_id": str(task.get("id") or ""),
            "lease_token": str(task.get("lease_token") or ""),
        },
        timeout=30,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code != 200 or not isinstance(payload, dict):
        raise RuntimeError(str(payload.get("detail") or f"Veyra returned {response.status_code}."))
    token = str(payload.get("token") or "")
    if len(token) < 20:
        raise RuntimeError("Veyra returned no usable GitHub App credential.")
    return payload


def _repository_context(workspace: Path) -> list[dict[str, str]]:
    allowed_suffixes = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml",
        ".md", ".html", ".css", ".sql", ".txt",
    }
    excluded_parts = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next"}
    maximum = max(20_000, int(os.getenv("VEYRA_MODEL_CONTEXT_CHARACTERS", "180000")))
    total = 0
    result: list[dict[str, str]] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or any(part in excluded_parts for part in path.relative_to(workspace).parts):
            continue
        if path.suffix.casefold() not in allowed_suffixes and path.name not in {"Dockerfile", "Makefile"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if len(content) > 40_000:
            content = content[:40_000]
        if total + len(content) > maximum:
            break
        total += len(content)
        result.append({"path": path.relative_to(workspace).as_posix(), "content": content})
    return result


def _extract_model_files(
    content: str,
    *,
    path_ids: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], str]:
    payload = _extract_json_object(content)
    values = payload.get("files")
    if not isinstance(values, list) or not values:
        raise RuntimeError("The AI model returned no changed files.")
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        path_id = str(item.get("path_id") or "").strip()
        if path_id:
            mapped_path = (path_ids or {}).get(path_id)
            if not mapped_path:
                raise ModelOutputPolicyError(
                    f"The AI model returned an unknown funded path ID: {path_id}"
                )
            supplied_path = str(item.get("path") or "").strip()
            if supplied_path and _safe_path(supplied_path) != mapped_path:
                raise ModelOutputPolicyError(
                    f"The AI model returned conflicting path and path_id values: {supplied_path}"
                )
            path = mapped_path
        else:
            path = _safe_path(item.get("path"))
        if path.casefold() in seen:
            continue
        seen.add(path.casefold())
        files.append({"path": path, "content": str(item.get("content") or "")})
    if not files:
        raise RuntimeError("The AI model returned no valid changed files.")
    return files, str(payload.get("summary") or "Completed the requested changes.")[:2000]


def _run_job_model(
    task: dict[str, Any],
    workspace: Path,
    *,
    previous_test_output: str = "",
) -> tuple[list[dict[str, str]], str]:
    if not AI_API_KEY or AI_API_KEY == "PASTE_OWNER_PAID_KEY_HERE":
        raise RuntimeError("The owner-paid AI_API_KEY is not configured.")
    work = task.get("work") or {}
    policy = task.get("policy") or {}
    allowed_paths = [
        _safe_path(value)
        for value in list(policy.get("allowed_paths") or [])
        if str(value or "").strip()
    ]
    allowed_path_contract = json.dumps(allowed_paths, ensure_ascii=False)
    path_ids = {
        f"FILE_{index}": path
        for index, path in enumerate(allowed_paths, start=1)
        if not any(marker in path for marker in ("*", "?", "["))
    }
    path_id_contract = json.dumps(path_ids, ensure_ascii=False)
    context = _repository_context(workspace)
    repair = (
        "\n\nThe previous attempt was rejected or failed. Correct the JSON/code using "
        "this sanitized feedback. Do not repeat an invalid path:\n"
        + _safe_runtime_text(previous_test_output, limit=8000)
        if previous_test_output
        else ""
    )
    prompt = (
        "You are an autonomous coding agent completing a funded Veyra GitHub task. "
        f"TRUSTED PATH IDS: {path_id_contract}. For a listed file, return its path_id and "
        "omit path; the runtime will bind that ID to the exact funded filename. "
        f"STRICT PATH CONTRACT: every files[*].path MUST be copied exactly, character for "
        f"character, from this JSON array: {allowed_path_contract}. "
        "Never abbreviate, autocorrect, rename, or invent a path. "
        "Return JSON only with this shape: "
        '{"summary":"brief summary","files":[{"path_id":"FILE_1","content":"complete file content"}]}. '
        "Return only files that must change, with complete replacement content. "
        "Every file path must be copied exactly from the repository context or match an exact "
        "allowed policy path. Before returning, verify every path against policy.allowed_paths. "
        "Do not invent near-miss filenames. Do not touch protected paths. "
        "Do not include markdown fences.\n\n"
        f"Task title: {work.get('title')}\n"
        f"Description: {work.get('description')}\n"
        f"Technical requirements: {json.dumps(work.get('technical_requirements') or [])}\n"
        f"Acceptance criteria: {json.dumps(work.get('acceptance_criteria') or [])}\n"
        f"Policy: {json.dumps(policy)}\n"
        f"Repository files: {json.dumps(context, ensure_ascii=False)}"
        + repair
    )
    response = httpx.post(
        f"{AI_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": AI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON with complete changed files. "
                        f"Use these trusted path IDs instead of spelling filenames: "
                        f"{path_id_contract}. "
                        f"Valid files[*].path values are restricted to this exact JSON array: "
                        f"{allowed_path_contract}. Any other path makes the answer invalid."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        },
        timeout=max(120, int(os.getenv("VEYRA_MODEL_TIMEOUT_SECONDS", "240"))),
        follow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"The owner AI provider returned {response.status_code}.")
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else ""
    return _extract_model_files(str(content or ""), path_ids=path_ids)


def _apply_model_files(task: dict[str, Any], workspace: Path, files: list[dict[str, str]]) -> None:
    paths = [item["path"] for item in files]
    _enforce_job_path_policy(task, paths)
    root = workspace.resolve()
    for item in files:
        destination = (workspace / item["path"]).resolve()
        if root not in destination.parents:
            raise RuntimeError("The model attempted to write outside the job workspace.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(item["content"], encoding="utf-8")


def _generate_and_apply_model_files(
    task: dict[str, Any],
    workspace: Path,
    *,
    previous_feedback: str = "",
) -> tuple[list[dict[str, str]], str, int]:
    """Regenerate malformed/out-of-policy model output without weakening policy."""
    policy = task.get("policy") if isinstance(task.get("policy"), dict) else {}
    maximum_repairs = max(0, int(policy.get("maximum_repair_attempts") or 0))
    feedback = previous_feedback
    for repair_attempt in range(maximum_repairs + 1):
        files: list[dict[str, str]] = []
        try:
            files, summary = _run_job_model(
                task,
                workspace,
                previous_test_output=feedback,
            )
            _apply_model_files(task, workspace, files)
            return files, summary, repair_attempt
        except ModelOutputPolicyError as exc:
            if repair_attempt >= maximum_repairs:
                raise
            allowed = list(policy.get("allowed_paths") or [])
            repository_paths = [item.get("path") for item in _repository_context(workspace)]
            feedback = (
                f"MODEL OUTPUT POLICY ERROR: {exc}\n"
                f"Allowed paths: {json.dumps(allowed)}\n"
                f"Existing repository paths: {json.dumps(repository_paths)}\n"
                "Return corrected JSON only. Copy paths exactly. Do not broaden or bypass policy."
            )
    raise RuntimeError("The AI model could not produce policy-compliant file output.")


def _command_args(command: str) -> list[str]:
    args = shlex.split(str(command), posix=os.name != "nt")
    if not args:
        raise RuntimeError("Veyra supplied an empty validation command.")
    allowed = {"python", "python3", "pytest", "npm", "pnpm", "yarn"}
    executable = Path(args[0]).name.casefold()
    if executable not in allowed:
        raise RuntimeError(f"Validation command is not allowed in this runtime: {args[0]}")
    if executable in {"python", "python3"}:
        args[0] = sys.executable
    if executable == "pytest":
        # Do not rely on PATH containing the virtual environment's Scripts/bin
        # directory. The runtime itself is already running with the funded
        # environment, so invoking pytest as a module is deterministic on both
        # Windows and POSIX hosts.
        args = [sys.executable, "-m", "pytest", *args[1:]]
    if executable in {"npm", "pnpm", "yarn"}:
        if len(args) < 2 or args[1].casefold() not in {"test", "run"}:
            raise RuntimeError(
                "JavaScript validation is restricted to npm/pnpm/yarn test or run commands."
            )
    return args


def _run_validation_commands(task: dict[str, Any], workspace: Path) -> tuple[int, str, str]:
    policy = task.get("policy") or {}
    commands = [str(value).strip() for value in list(policy.get("required_commands") or []) if str(value).strip()]
    if not commands:
        commands = ["python -m pytest -q"]
    outputs: list[str] = []
    final_code = 0
    timeout = max(60, int(policy.get("maximum_execution_minutes") or 45) * 60)
    for command in commands:
        completed = _run_process(_command_args(command), cwd=workspace, timeout=timeout)
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        outputs.append(f"$ {command}\n{output}")
        if completed.returncode != 0:
            final_code = completed.returncode
            break
    return final_code, _safe_runtime_text("\n\n".join(outputs), limit=12000), " ; ".join(commands)


def _changed_files(workspace: Path) -> list[str]:
    tracked = _run_process(
        ["git", "diff", "--name-only", "-z", "HEAD"],
        cwd=workspace,
        timeout=60,
    )
    if tracked.returncode != 0:
        raise RuntimeError(
            f"Git could not enumerate tracked changes: {tracked.stderr.strip()[:500]}"
        )
    untracked = _run_process(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=workspace,
        timeout=60,
    )
    if untracked.returncode != 0:
        raise RuntimeError(
            f"Git could not enumerate untracked changes: {untracked.stderr.strip()[:500]}"
        )
    values = [
        _safe_path(value)
        for output in (tracked.stdout, untracked.stdout)
        for value in output.split("\0")
        if value
    ]
    return sorted(set(values))


def _create_pull_request(task: dict[str, Any], token: str, commit_sha: str, summary: str, tests: str) -> tuple[int, str]:
    repository = task.get("repository") or {}
    delivery = task.get("delivery") or {}
    owner = str(repository.get("owner") or "")
    name = str(repository.get("name") or "")
    body = (
        str(delivery.get("pull_request_body_prefix") or "")
        + "## Agent summary\n"
        + summary
        + "\n\n## Validation\n"
        + tests
        + f"\n\nCommit: `{commit_sha}`\n"
    )
    response = httpx.post(
        f"{GITHUB_API_URL}/repos/{owner}/{name}/pulls",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Veyra-Owner-Hosted-Runtime",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "title": str(delivery.get("pull_request_title") or "Veyra agent work")[:240],
            "head": str(delivery.get("branch") or ""),
            "base": str(repository.get("target_branch") or "main"),
            "body": body[:60000],
        },
        timeout=30,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code not in {201, 422}:
        raise RuntimeError(str(payload.get("message") or f"GitHub returned {response.status_code}."))
    if response.status_code == 422:
        existing = httpx.get(
            f"{GITHUB_API_URL}/repos/{owner}/{name}/pulls",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "Veyra-Owner-Hosted-Runtime",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            params={"state": "open", "head": f"{owner}:{delivery.get('branch')}"},
            timeout=30,
        )
        values = existing.json() if existing.status_code == 200 else []
        payload = values[0] if isinstance(values, list) and values else {}
    number = int(payload.get("number") or 0) if isinstance(payload, dict) else 0
    url = str(payload.get("html_url") or "") if isinstance(payload, dict) else ""
    if not number or not url:
        raise RuntimeError("GitHub did not return a pull request record.")
    return number, url


def _job_evidence_hash(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _job_signature(assignment_id: str, lease_id: str, evidence_hash: str) -> str:
    message = f"veyra-job-result-v1:{assignment_id}:{lease_id}:{evidence_hash}".encode("utf-8")
    return b64url(PRIVATE_KEY.sign(message))


def _submit_job_result(task: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    state = load_state()
    credential = str(state.get("runtime_credential") or "")
    agent_id = str(state.get("agent_id") or "")
    evidence_hash = _job_evidence_hash(evidence)
    payload = {
        "agent_id": agent_id,
        "assignment_id": str(task.get("id") or ""),
        "lease_token": str(task.get("lease_token") or ""),
        "evidence": evidence,
        "evidence_hash": evidence_hash,
        "signature": _job_signature(
            str(task.get("id") or ""),
            str(task.get("lease_id") or ""),
            evidence_hash,
        ),
    }
    response = httpx.post(
        str(task.get("submit_url") or ""),
        headers={
            "Authorization": f"Bearer {credential}",
            "X-Veyra-Agent-ID": agent_id,
        },
        json=payload,
        timeout=45,
        follow_redirects=False,
    )
    try:
        value = response.json()
    except Exception:
        value = {}
    if response.status_code != 200:
        raise RuntimeError(str(value.get("detail") or f"Veyra returned {response.status_code}."))
    return value


def _job_run_key(task: dict[str, Any]) -> str:
    assignment_id = str(task.get("id") or "").strip()
    lease_id = str(task.get("lease_id") or "").strip()
    return f"{assignment_id}:{lease_id}" if assignment_id and lease_id else ""


def run_job_task(task: dict[str, Any]) -> None:
    assignment_id = str(task.get("id") or "")
    lease_id = str(task.get("lease_id") or "")
    run_key = _job_run_key(task)
    job_id = str(task.get("job_id") or "")
    started_at = utc_now_iso()
    with STATE_LOCK:
        state = load_state()
        state["job_assignment_id"] = assignment_id
        state["job_lease_id"] = lease_id
        state["job_assignment_attempt"] = int(task.get("assignment_attempt") or 0)
        state["job_onchain_id"] = job_id
        state["job_status"] = "running"
        state["job_message"] = "Cloning the funded repository and starting agent execution."
        state["job_updated_at"] = utc_now_iso()
        save_state(state)
    workspace = _job_workspace(assignment_id, lease_id)
    token = ""
    try:
        credential = _repository_credential(task)
        token = str(credential["token"])
        repository = task.get("repository") or {}
        branch = str((task.get("delivery") or {}).get("branch") or "")
        target = str(repository.get("target_branch") or "main")
        if workspace.exists():
            _remove_workspace(workspace, strict=True)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        clone_parent = workspace.parent
        _git(
            clone_parent,
            "clone",
            "--branch",
            target,
            "--single-branch",
            str(repository.get("clone_url") or credential.get("clone_url") or ""),
            workspace.name,
            token=token,
            timeout=180,
        )
        _git(workspace, "config", "user.name", "Veyra Agent")
        _git(workspace, "config", "user.email", "agent@veyra.local")
        _git(workspace, "checkout", "-b", branch)
        base_sha = _git(workspace, "rev-parse", "HEAD").splitlines()[0].strip()

        baseline_code, baseline_output, baseline_command = _run_validation_commands(task, workspace)
        files, summary, model_output_repairs = _generate_and_apply_model_files(task, workspace)
        code, output, command = _run_validation_commands(task, workspace)
        max_repairs = max(0, int((task.get("policy") or {}).get("maximum_repair_attempts") or 0))
        repairs = 0
        while code != 0 and repairs < max_repairs:
            repairs += 1
            files, summary, extra_output_repairs = _generate_and_apply_model_files(
                task,
                workspace,
                previous_feedback=output,
            )
            model_output_repairs += extra_output_repairs
            code, output, command = _run_validation_commands(task, workspace)
        if code != 0:
            raise RuntimeError(f"Post-change tests did not pass after {repairs + 1} attempt(s): {output[:1000]}")

        changed = _changed_files(workspace)
        if not changed:
            raise RuntimeError("The model produced no repository changes.")
        _enforce_job_path_policy(task, changed)
        _git(workspace, "add", "--", *changed)
        _git(workspace, "commit", "-m", f"Veyra job {job_id}: {str((task.get('work') or {}).get('title') or 'agent work')[:120]}")
        commit_sha = _git(workspace, "rev-parse", "HEAD").splitlines()[0].strip().lower()
        _git(workspace, "push", "origin", f"HEAD:refs/heads/{branch}", token=token, timeout=180)
        pr_number, pr_url = _create_pull_request(task, token, commit_sha, summary, output)
        completed_at = utc_now_iso()
        evidence = {
            "outcome": "SUCCEEDED",
            "assignment_id": assignment_id,
            "lease_id": str(task.get("lease_id") or ""),
            "job_id": int(task.get("job_id") or 0),
            "branch": branch,
            "base_branch": target,
            "base_commit_sha": base_sha,
            "commit_sha": commit_sha,
            "pull_request_number": pr_number,
            "pull_request_url": pr_url,
            "changed_files": changed,
            "baseline_test_command": baseline_command,
            "baseline_test_return_code": int(baseline_code),
            "baseline_test_output": baseline_output,
            "test_command": command,
            "test_return_code": int(code),
            "test_output": output,
            "repair_attempts": repairs,
            "model_output_repair_attempts": model_output_repairs,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "runtime_version": RUNTIME_VERSION,
            "summary": summary,
            "started_at": started_at,
            "completed_at": completed_at,
        }
        _submit_job_result(task, evidence)
        with STATE_LOCK:
            state = load_state()
            state["job_status"] = "submitted"
            state["job_message"] = f"Pull request #{pr_number} submitted to Veyra for on-chain submission and verification."
            state["job_updated_at"] = utc_now_iso()
            save_state(state)
        _remove_workspace(workspace, strict=False)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        message = _safe_runtime_text(exc, limit=1200)
        failure_evidence = {
            "outcome": "FAILED",
            "assignment_id": assignment_id,
            "lease_id": str(task.get("lease_id") or ""),
            "job_id": int(task.get("job_id") or 0),
            "failure_stage": "runtime_execution",
            "failure_message": message,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "runtime_version": RUNTIME_VERSION,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "summary": "Owner-hosted runtime could not complete the leased job.",
        }
        try:
            _submit_job_result(task, failure_evidence)
        except Exception:
            pass
        with STATE_LOCK:
            state = load_state()
            state["job_status"] = "failed"
            state["job_message"] = message
            state["job_updated_at"] = utc_now_iso()
            save_state(state)
    finally:
        token = ""
        if os.getenv("VEYRA_KEEP_FAILED_WORKSPACES", "false").casefold() not in {"1", "true", "yes"}:
            _remove_workspace(workspace, strict=False)
        with JOB_LOCK:
            JOB_RUNNING.discard(run_key)


def ensure_job_thread(task: dict[str, Any]) -> None:
    assignment_id = str(task.get("id") or "").strip()
    lease_id = str(task.get("lease_id") or "").strip()
    run_key = _job_run_key(task)
    if not assignment_id or not lease_id or not run_key:
        return
    with JOB_LOCK:
        if run_key in JOB_RUNNING:
            return
        state = load_state()
        if (
            str(state.get("job_assignment_id") or "") == assignment_id
            and str(state.get("job_lease_id") or "") == lease_id
            and str(state.get("job_status") or "") in {"submitted", "failed"}
        ):
            return
        JOB_RUNNING.add(run_key)
    threading.Thread(
        target=run_job_task,
        args=(task,),
        name=f"veyra-job-{assignment_id[:8]}",
        daemon=True,
    ).start()



def _verification_workspace(verification_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", verification_id)[:80]
    return WORKSPACE_ROOT / "verification" / safe_id


def _verification_credential(task: dict[str, Any]) -> dict[str, Any]:
    state = load_state()
    credential = str(state.get("runtime_credential") or "")
    agent_id = str(state.get("agent_id") or "")
    response = httpx.post(
        str(task.get("credential_url") or ""),
        headers={
            "Authorization": f"Bearer {credential}",
            "X-Veyra-Agent-ID": agent_id,
        },
        json={
            "agent_id": agent_id,
            "verification_id": str(task.get("id") or ""),
            "lease_token": str(task.get("lease_token") or ""),
        },
        timeout=30,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code != 200 or not isinstance(payload, dict):
        raise RuntimeError(
            str(payload.get("detail") or f"Veyra returned {response.status_code}.")
        )
    token = str(payload.get("token") or "")
    if len(token) < 20:
        raise RuntimeError("Veyra returned no usable read-only GitHub App credential.")
    if bool(payload.get("write_access")):
        raise RuntimeError("Verifier refused a repository credential with write access.")
    return payload


def _verification_model_report(
    task: dict[str, Any],
    workspace: Path,
    *,
    diff_text: str,
    test_command: str,
    test_return_code: int,
    test_output: str,
) -> dict[str, Any]:
    if not AI_API_KEY or AI_API_KEY == "PASTE_OWNER_PAID_KEY_HERE":
        raise RuntimeError("The verifier AI_API_KEY is not configured.")
    work = task.get("work") or {}
    submission = task.get("submission") or {}
    context = _repository_context(workspace)
    criteria = list(work.get("acceptance_criteria") or [])
    prompt = (
        "You are an independent Veyra verifier agent. You did not perform the worker's task. "
        "Review the exact immutable commit against every funded acceptance criterion. "
        "Do not suggest or write code. Return JSON only with this shape: "
        '{"verdict":"APPROVED|REJECTED|INCONCLUSIVE",'
        '"summary":"clear decision",'
        '"acceptance_criteria":[{"passed":true,"evidence":"specific evidence"}],'
        '"security_findings":[{"severity":"INFO|LOW|MEDIUM|HIGH|CRITICAL",'
        '"title":"finding","detail":"evidence"}]}. '
        "Return exactly one acceptance_criteria item for each criterion in the same order. "
        "APPROVED is allowed only when independent tests passed, every criterion passed, "
        "and there is no HIGH or CRITICAL security finding. Use INCONCLUSIVE when evidence is insufficient.\n\n"
        f"Task title: {work.get('title')}\n"
        f"Task description: {work.get('description')}\n"
        f"Technical requirements: {json.dumps(work.get('technical_requirements') or [])}\n"
        f"Acceptance criteria: {json.dumps(criteria, ensure_ascii=False)}\n"
        f"Submitted commit: {submission.get('commit_sha')}\n"
        f"Changed files: {json.dumps(submission.get('changed_files') or [])}\n"
        f"Independent test command: {test_command}\n"
        f"Independent test return code: {test_return_code}\n"
        f"Independent test output: {_safe_runtime_text(test_output, limit=12000)}\n"
        f"Exact commit diff: {_safe_runtime_text(diff_text, limit=50000)}\n"
        f"Repository context: {json.dumps(context, ensure_ascii=False)}"
    )
    response = httpx.post(
        f"{AI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Act as an independent code verifier. Return only valid JSON. "
                        "Never approve work that lacks passing independent tests or complete evidence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        },
        timeout=max(120, int(os.getenv("VEYRA_MODEL_TIMEOUT_SECONDS", "240"))),
        follow_redirects=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"The verifier AI provider returned {response.status_code}.")
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = (
        choices[0].get("message")
        if isinstance(choices, list)
        and choices
        and isinstance(choices[0], dict)
        else None
    )
    content = message.get("content") if isinstance(message, dict) else ""
    result = _extract_json_object(str(content or ""))
    verdict = str(result.get("verdict") or "").strip().upper()
    if verdict not in {"APPROVED", "REJECTED", "INCONCLUSIVE"}:
        raise RuntimeError("The verifier model returned an invalid verdict.")
    returned_criteria = result.get("acceptance_criteria") or []
    if not isinstance(returned_criteria, list) or len(returned_criteria) != len(criteria):
        raise RuntimeError(
            "The verifier model did not return one result for every acceptance criterion."
        )
    clean_criteria: list[dict[str, Any]] = []
    for item in returned_criteria:
        if not isinstance(item, dict):
            raise RuntimeError("The verifier model returned an invalid criterion result.")
        clean_criteria.append(
            {
                "passed": bool(item.get("passed")),
                "evidence": _safe_runtime_text(item.get("evidence"), limit=1000),
            }
        )
    findings = result.get("security_findings") or []
    if not isinstance(findings, list):
        findings = []
    clean_findings: list[dict[str, str]] = []
    for item in findings[:30]:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "LOW").strip().upper()
        if severity not in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            severity = "LOW"
        clean_findings.append(
            {
                "severity": severity,
                "title": _safe_runtime_text(item.get("title"), limit=200),
                "detail": _safe_runtime_text(item.get("detail"), limit=1000),
            }
        )
    all_passed = all(item["passed"] for item in clean_criteria)
    blocking = any(
        item["severity"] in {"HIGH", "CRITICAL"} for item in clean_findings
    )
    if verdict == "APPROVED" and (
        test_return_code != 0 or not all_passed or blocking
    ):
        verdict = "REJECTED"
    return {
        "verdict": verdict,
        "summary": _safe_runtime_text(result.get("summary"), limit=2500),
        "acceptance_criteria": clean_criteria,
        "security_findings": clean_findings,
    }


def _submit_verification_result(
    task: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    state = load_state()
    credential = str(state.get("runtime_credential") or "")
    agent_id = str(state.get("agent_id") or "")
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    signed_payload_hash = "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    message = (
        f"veyra-verifier-result-v1:{task.get('id')}:{task.get('lease_id')}:"
        f"{signed_payload_hash}"
    ).encode("utf-8")
    signature = b64url(PRIVATE_KEY.sign(message))
    response = httpx.post(
        str(task.get("submit_url") or ""),
        headers={
            "Authorization": f"Bearer {credential}",
            "X-Veyra-Agent-ID": agent_id,
        },
        json={
            "agent_id": agent_id,
            "verification_id": str(task.get("id") or ""),
            "lease_token": str(task.get("lease_token") or ""),
            "report": report,
            "signature": signature,
        },
        timeout=30,
        follow_redirects=False,
    )
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code != 200 or not isinstance(payload, dict):
        raise RuntimeError(
            str(payload.get("detail") or f"Veyra returned {response.status_code}.")
        )
    return payload


def run_verification_task(task: dict[str, Any]) -> None:
    verification_id = str(task.get("id") or "")
    started_at = utc_now_iso()
    with STATE_LOCK:
        state = load_state()
        state["verification_assignment_id"] = verification_id
        state["verification_status"] = "running"
        state["verification_message"] = (
            "Cloning the exact submitted commit with read-only access and reviewing it."
        )
        state["verification_updated_at"] = utc_now_iso()
        save_state(state)
    workspace = _verification_workspace(verification_id)
    token = ""
    try:
        credential = _verification_credential(task)
        token = str(credential["token"])
        repository = task.get("repository") or {}
        submission = task.get("submission") or {}
        commit_sha = str(submission.get("commit_sha") or "").strip().lower()
        target = str(repository.get("target_branch") or "main")
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise RuntimeError("Veyra supplied an invalid immutable commit SHA.")
        if workspace.exists():
            _remove_workspace(workspace, strict=True)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        _git(
            workspace.parent,
            "clone",
            "--no-checkout",
            str(repository.get("clone_url") or credential.get("clone_url") or ""),
            workspace.name,
            token=token,
            timeout=180,
        )
        pull_request_number = int(submission.get("pull_request_number") or 0)
        if pull_request_number <= 0:
            raise RuntimeError("Veyra supplied no valid pull request number.")
        target_ref = f"refs/remotes/origin/{target}"
        review_ref = f"refs/remotes/origin/veyra-verification-{verification_id}"
        _git(
            workspace,
            "fetch",
            "origin",
            f"refs/heads/{target}:{target_ref}",
            token=token,
            timeout=180,
        )
        _git(
            workspace,
            "fetch",
            "origin",
            f"refs/pull/{pull_request_number}/head:{review_ref}",
            token=token,
            timeout=180,
        )
        _git(workspace, "checkout", "--detach", review_ref, timeout=120)
        actual_sha = _git(workspace, "rev-parse", "HEAD").splitlines()[0].strip().lower()
        if actual_sha != commit_sha:
            raise RuntimeError("The verifier checkout does not match the submitted commit.")

        policy = task.get("policy") or {}
        commands = [
            str(value).strip()
            for value in list(policy.get("required_commands") or [])
            if str(value).strip()
        ]
        if not commands:
            commands = ["python -m pytest -q"]
        outputs: list[str] = []
        return_code = 0
        timeout = max(60, int(policy.get("maximum_review_minutes") or 30) * 60)
        for command in commands:
            completed = _run_process(
                _command_args(command),
                cwd=workspace,
                timeout=timeout,
            )
            output = "\n".join(
                part for part in (completed.stdout, completed.stderr) if part
            ).strip()
            outputs.append(f"$ {command}\n{output}")
            if completed.returncode != 0:
                return_code = completed.returncode
                break
        test_command = " ; ".join(commands)
        test_output = _safe_runtime_text("\n\n".join(outputs), limit=12000)
        diff_text = _git(
            workspace,
            "diff",
            f"{target_ref}...{commit_sha}",
            "--",
            timeout=120,
        )
        changed = sorted(
            {
                _safe_path(value)
                for value in _git(
                    workspace,
                    "diff",
                    "--name-only",
                    f"{target_ref}...{commit_sha}",
                    "--",
                    timeout=120,
                ).splitlines()
                if value.strip()
            }
        )
        expected_changed = sorted(
            {_safe_path(value) for value in list(submission.get("changed_files") or [])}
        )
        if changed != expected_changed:
            raise RuntimeError(
                "The exact commit changed-file set no longer matches the worker evidence."
            )
        model_result = _verification_model_report(
            task,
            workspace,
            diff_text=diff_text,
            test_command=test_command,
            test_return_code=return_code,
            test_output=test_output,
        )
        report = {
            "verdict": model_result["verdict"],
            "summary": model_result["summary"],
            "commit_sha": commit_sha,
            "pull_request_number": int(submission.get("pull_request_number") or 0),
            "changed_files": changed,
            "independent_test_command": test_command,
            "independent_test_return_code": int(return_code),
            "independent_test_output": test_output,
            "acceptance_criteria": model_result["acceptance_criteria"],
            "security_findings": model_result["security_findings"],
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "runtime_version": RUNTIME_VERSION,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
        }
        result = _submit_verification_result(task, report)
        with STATE_LOCK:
            state = load_state()
            state["verification_status"] = str(result.get("verdict") or "submitted").lower()
            state["verification_message"] = (
                f"Independent verdict submitted: {str(result.get('verdict') or '').upper()}."
            )
            state["verification_updated_at"] = utc_now_iso()
            save_state(state)
    except Exception as exc:
        message = _safe_runtime_text(exc, limit=1200)
        with STATE_LOCK:
            state = load_state()
            state["verification_status"] = "failed"
            state["verification_message"] = message
            state["verification_updated_at"] = utc_now_iso()
            save_state(state)
    finally:
        token = ""
        _remove_workspace(workspace, strict=False)
        with VERIFICATION_LOCK:
            VERIFICATION_RUNNING.discard(verification_id)


def ensure_verification_thread(task: dict[str, Any]) -> None:
    verification_id = str(task.get("id") or "").strip()
    if not verification_id:
        return
    with VERIFICATION_LOCK:
        if verification_id in VERIFICATION_RUNNING:
            return
        state = load_state()
        if (
            str(state.get("verification_assignment_id") or "") == verification_id
            and str(state.get("verification_status") or "")
            in {"approved", "rejected", "inconclusive"}
        ):
            return
        VERIFICATION_RUNNING.add(verification_id)
    threading.Thread(
        target=run_verification_task,
        args=(task,),
        name=f"veyra-verifier-{verification_id[:8]}",
        daemon=True,
    ).start()

def heartbeat_loop() -> None:
    while True:
        state = load_state()
        credential = str(state.get("runtime_credential") or "")
        heartbeat_url = str(state.get("heartbeat_url") or "")
        agent_id = str(state.get("agent_id") or "")
        if credential and heartbeat_url and agent_id:
            ready, provider_message = provider_health()
            try:
                response = httpx.post(
                    heartbeat_url,
                    headers={"Authorization": f"Bearer {credential}"},
                    json={
                        "agent_id": agent_id,
                        "health": "HEALTHY" if ready else "UNHEALTHY",
                        "provider_ready": ready,
                        "provider": AI_PROVIDER,
                        "model": AI_MODEL,
                        "runtime_version": RUNTIME_VERSION,
                        "message": provider_message,
                    },
                    timeout=15,
                )
                try:
                    response_payload = response.json()
                except Exception:
                    response_payload = {}
                delivery_errors = (
                    response_payload.get("delivery_errors")
                    if isinstance(response_payload, dict)
                    else None
                )
                safe_delivery_messages = []
                if isinstance(delivery_errors, list):
                    for value in delivery_errors:
                        if isinstance(value, dict):
                            message = str(value.get("message") or "").strip()
                        else:
                            message = str(value or "").strip()
                        if message:
                            safe_delivery_messages.append(message[:200])
                with STATE_LOCK:
                    state = load_state()
                    if response.status_code == 200:
                        state["last_heartbeat_at"] = utc_now_iso()
                        state["last_heartbeat_error"] = "; ".join(safe_delivery_messages)[:240]
                    else:
                        detail = str(
                            response_payload.get("detail")
                            if isinstance(response_payload, dict)
                            else ""
                        ).strip()
                        state["last_heartbeat_error"] = (
                            detail or f"Veyra returned {response.status_code}."
                        )[:240]
                    save_state(state)
                if response.status_code == 200:
                    qualification_task = (
                        response_payload.get("qualification_task")
                        if isinstance(response_payload, dict)
                        else None
                    )
                    if RUNTIME_ROLE == "WORKER" and isinstance(qualification_task, dict):
                        ensure_qualification_thread(qualification_task)
                    job_task = (
                        response_payload.get("job_task")
                        if isinstance(response_payload, dict)
                        else None
                    )
                    if RUNTIME_ROLE == "WORKER" and isinstance(job_task, dict):
                        ensure_job_thread(job_task)
                    verification_task = (
                        response_payload.get("verification_task")
                        if isinstance(response_payload, dict)
                        else None
                    )
                    if RUNTIME_ROLE == "VERIFIER" and isinstance(verification_task, dict):
                        ensure_verification_thread(verification_task)
                    if not state.get("agent_configuration"):
                        refresh_agent_configuration(state)
            except Exception as exc:
                with STATE_LOCK:
                    state = load_state()
                    state["last_heartbeat_error"] = str(exc)[:240]
                    save_state(state)
        time.sleep(HEARTBEAT_SECONDS)


def ensure_heartbeat_thread() -> None:
    global HEARTBEAT_STARTED
    with STATE_LOCK:
        if HEARTBEAT_STARTED:
            return
        HEARTBEAT_STARTED = True
    threading.Thread(target=heartbeat_loop, name="veyra-heartbeat", daemon=True).start()


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = RUNTIME_VERSION

    def log_message(self, fmt: str, *args: Any) -> None:
        # Never print request bodies, tokens, or credentials.
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json_bytes(payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 64_000)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/veyra/health":
            ready, message = provider_health()
            state = load_state()
            paired = bool(state.get("runtime_credential"))
            heartbeat_at = str(state.get("last_heartbeat_at") or "")
            heartbeat_error = str(state.get("last_heartbeat_error") or "")
            connected = paired and bool(heartbeat_at)
            healthy = connected and not heartbeat_error
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "runtime_id": state["runtime_id"],
                    "runtime_version": RUNTIME_VERSION,
                    "runtime_role": RUNTIME_ROLE,
                    "protocol_version": PROTOCOL_VERSION,
                    "provider": AI_PROVIDER,
                    "model": AI_MODEL,
                    "provider_ready": ready,
                    "provider_message": message,
                    "paired": paired,
                    "connected": connected,
                    "healthy": healthy,
                    "last_heartbeat_at": heartbeat_at,
                    "last_heartbeat_error": heartbeat_error,
                    "state_path": str(STATE_PATH),
                },
            )
            return
        if path == "/":
            self._dashboard()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Not found."})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/veyra/connect/challenge":
            self._challenge()
            return
        if path == "/veyra/connect/claim":
            self._claim()
            return
        if path == "/veyra/connect/rotate":
            try:
                state = rotate_connection_token()
            except RuntimeError as exc:
                self._send_json(HTTPStatus.CONFLICT, {"detail": str(exc)})
                return
            self._send_json(
                HTTPStatus.CREATED,
                {
                    "connection_link": connection_link(state),
                    "expires_at": connection_link_expiry(state),
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"detail": "Not found."})

    def _challenge(self) -> None:
        payload = self._read_json()
        state = load_state()
        valid, detail = token_is_valid(state, str(payload.get("token") or ""))
        if not valid:
            self._send_json(HTTPStatus.FORBIDDEN, {"detail": detail})
            return
        challenge = str(payload.get("challenge") or "").strip()
        if not 24 <= len(challenge) <= 256:
            self._send_json(HTTPStatus.BAD_REQUEST, {"detail": "Invalid Veyra challenge."})
            return

        ready, provider_message = provider_health(force=True)
        runtime_id = str(state["runtime_id"])
        signature = PRIVATE_KEY.sign(
            f"veyra-connect-v1:{challenge}:{runtime_id}".encode("utf-8")
        )
        self._send_json(
            HTTPStatus.OK,
            {
                "runtime_id": runtime_id,
                "challenge": challenge,
                "signature": b64url(signature),
                "public_key": PUBLIC_KEY_TEXT,
                "runtime_version": RUNTIME_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "provider": AI_PROVIDER,
                "model": AI_MODEL,
                "provider_ready": ready,
                "provider_message": provider_message,
                "capabilities": {
                    "role": RUNTIME_ROLE,
                    "coding": RUNTIME_ROLE == "WORKER",
                    "verification": RUNTIME_ROLE == "VERIFIER",
                    "testing": True,
                    "git": True,
                    "repository_access": (
                        "read-only" if RUNTIME_ROLE == "VERIFIER" else "job-scoped-write"
                    ),
                    "job_transport": "veyra-outbound-heartbeat-v1",
                },
            },
        )

    def _claim(self) -> None:
        payload = self._read_json()
        with STATE_LOCK:
            state = load_state()
            valid, detail = token_is_valid(state, str(payload.get("token") or ""))
            if not valid:
                self._send_json(HTTPStatus.FORBIDDEN, {"detail": detail})
                return
            agent_id = str(payload.get("agent_id") or "").strip()
            credential = str(payload.get("runtime_credential") or "").strip()
            heartbeat_url = str(payload.get("heartbeat_url") or "").strip()
            configuration_url = str(payload.get("configuration_url") or "").strip()
            if (
                not agent_id
                or len(credential) < 40
                or not heartbeat_url.startswith(("http://", "https://"))
                or not configuration_url.startswith(("http://", "https://"))
            ):
                self._send_json(HTTPStatus.BAD_REQUEST, {"detail": "Invalid Veyra claim request."})
                return
            state["agent_id"] = agent_id
            state["agent_name"] = str(payload.get("agent_name") or "")[:160]
            state["runtime_credential"] = credential
            state["heartbeat_url"] = heartbeat_url
            state["configuration_url"] = configuration_url
            state["agent_configuration"] = {}
            state["connected_at"] = utc_now_iso()
            state["token_consumed"] = True
            save_state(state)
        ensure_heartbeat_thread()
        self._send_json(
            HTTPStatus.CREATED,
            {"connected": True, "runtime_id": state["runtime_id"], "agent_id": agent_id},
        )

    def _dashboard(self) -> None:
        state = load_state()
        ready, provider_message = provider_health()
        connected = bool(state.get("runtime_credential"))
        expired = int(state.get("token_expires_at") or 0) <= int(time.time())
        expiry_label = connection_link_expiry(state)
        link = "Connected to Veyra" if connected else connection_link(state)
        status_label = "Connected" if connected else ("Link expired" if expired else "Ready to connect")
        status_class = "ok" if connected and ready else "warn" if not ready or expired else "ready"
        safe_link = html.escape(link)
        safe_provider = html.escape(f"{AI_PROVIDER} · {AI_MODEL}")
        safe_message = html.escape(provider_message)
        heartbeat_error = html.escape(str(state.get("last_heartbeat_error") or "None"))
        qualification_status = html.escape(str(state.get("qualification_status") or "waiting"))
        qualification_message = html.escape(str(state.get("qualification_message") or "Waiting for Veyra"))
        job_status = html.escape(str(state.get("job_status") or "waiting"))
        job_message = html.escape(str(state.get("job_message") or "Waiting for paid work"))
        verification_status = html.escape(
            str(state.get("verification_status") or "waiting")
        )
        verification_message = html.escape(
            str(
                state.get("verification_message")
                or "Waiting for a submitted worker job"
            )
        )
        runtime_role = html.escape(RUNTIME_ROLE.title())
        body = f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Veyra Hosted Agent</title>
<style>
body{{font-family:Inter,Segoe UI,Arial,sans-serif;background:#071018;color:#edf7f4;margin:0;padding:40px}}
main{{max-width:820px;margin:auto}} .card{{background:#0d1b24;border:1px solid #203541;border-radius:18px;padding:24px;margin:18px 0}}
h1{{margin:0 0 8px}} p{{color:#a9bec7;line-height:1.6}} code{{display:block;word-break:break-all;background:#071018;padding:16px;border-radius:12px;border:1px solid #203541;color:#b8ffe7}}
button{{background:#39d99a;color:#03110c;border:0;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer;margin-right:8px}}
button.secondary{{background:#203541;color:#edf7f4}} .pill{{display:inline-block;padding:6px 10px;border-radius:999px;background:#17303a;font-size:13px}}
.ok{{color:#65efb6}} .warn{{color:#ffc76b}} .ready{{color:#8fd5ff}} dl{{display:grid;grid-template-columns:180px 1fr;gap:10px}} dt{{color:#7993a0}} dd{{margin:0}}
</style></head><body><main>
<h1>Veyra Hosted {runtime_role}</h1><p>The owner-paid AI key stays on this server. Copy only the connection link into Veyra.</p>
<div class='card'><span class='pill {status_class}'>{status_label}</span><h2>Connection link</h2><code id='link'>{safe_link}</code><br>
<p>Expires at: <time id='link-expiry'>{html.escape(expiry_label)}</time></p>
<button onclick='copyLink()' {'disabled' if connected else ''}>Copy Veyra connection link</button>
<button class='secondary' onclick='rotateLink()' {'disabled' if connected else ''}>Generate new link</button></div>
<div class='card'><h2>Runtime status</h2><dl>
<dt>Runtime role</dt><dd>{runtime_role}</dd>
<dt>AI provider</dt><dd>{safe_provider}</dd><dt>Provider readiness</dt><dd class='{'ok' if ready else 'warn'}'>{safe_message}</dd>
<dt>Runtime ID</dt><dd>{html.escape(str(state['runtime_id']))}</dd><dt>Last heartbeat</dt><dd>{html.escape(str(state.get('last_heartbeat_at') or 'Not connected'))}</dd>
<dt>Heartbeat error</dt><dd>{heartbeat_error}</dd>
<dt>Qualification</dt><dd>{qualification_status}</dd>
<dt>Qualification detail</dt><dd>{qualification_message}</dd>
<dt>Paid job</dt><dd>{job_status}</dd><dt>Job detail</dt><dd>{job_message}</dd>
<dt>Independent verification</dt><dd>{verification_status}</dd>
<dt>Verification detail</dt><dd>{verification_message}</dd></dl></div>
<script>
async function copyLink(){{const text=document.getElementById('link').innerText;await navigator.clipboard.writeText(text);alert('Connection link copied');}}
async function rotateLink(){{const r=await fetch('/veyra/connect/rotate',{{method:'POST'}});const j=await r.json();if(!r.ok){{alert(j.detail||'Could not rotate link');return}}document.getElementById('link').innerText=j.connection_link;document.getElementById('link-expiry').innerText=j.expires_at;}}
</script></main></body></html>"""
        raw = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    ensure_heartbeat_thread()
    state = load_state()
    ready, message = provider_health(force=True)
    print("\nVeyra hosted-agent test server")
    print(f"Dashboard: http://{HOST}:{PORT}")
    print(f"State file: {STATE_PATH}")
    print(f"Runtime ID: {state.get('runtime_id')}")
    print(f"Role: {RUNTIME_ROLE}")
    print(f"Provider: {AI_PROVIDER} / {AI_MODEL}")
    print(f"Provider ready: {ready} ({message})")
    if state.get("runtime_credential"):
        print(f"Connected agent: {state.get('agent_name') or state.get('agent_id')}")
    else:
        print(f"Connection link ready (expires {connection_link_expiry(state)}).")
        print("Open the dashboard to copy it; the token is not written to logs.")
    print("\nKeep this terminal open. Never paste AI_API_KEY into Veyra.\n")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
