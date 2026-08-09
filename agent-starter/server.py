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
import tomllib
import traceback
import uuid
import signal
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
RUNTIME_VERSION = f"veyra-owner-runtime-{RUNTIME_ROLE.lower()}/1.2.0-multistack"
PROTOCOL_VERSION = 1
TOKEN_TTL_SECONDS = 24 * 60 * 60
HEARTBEAT_SECONDS = max(2, int(os.getenv("VEYRA_HEARTBEAT_SECONDS", "5")))

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
        "job_phase": "",
        "job_message": "Waiting for paid work",
        "job_updated_at": "",
        "verification_assignment_id": "",
        "verification_status": "waiting",
        "verification_phase": "",
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
        ready, message = False, "Add the owner-paid AI_API_KEY to agent-starter/.env."
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


def _safe_path(value: Any) -> str:
    """Normalize one untrusted path to canonical repository-relative POSIX form."""
    raw_path = str(value or "").strip()
    path = raw_path.replace("\\", "/")
    if (
        not path
        or "\x00" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
    ):
        raise RuntimeError("The job attempted to use an unsafe repository path.")
    parts: list[str] = []
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise RuntimeError("The job attempted to use an unsafe repository path.")
        parts.append(part)
    if not parts:
        raise RuntimeError("The job attempted to use an unsafe repository path.")
    return "/".join(parts)


def _protected_path(path: str) -> bool:
    selected = _safe_path(path)
    parts = [part.casefold() for part in selected.split("/")]
    basename = parts[-1]
    return (
        basename == ".env"
        or basename.startswith(".env.")
        or ".git" in parts
        or parts[:2] == [".github", "workflows"]
    )


def _qualification_workspace(qualification_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", qualification_id)[:80]
    return WORKSPACE_ROOT / "qualification" / safe_id


def _write_starter_files(workspace: Path, files: list[dict[str, Any]]) -> None:
    if workspace.exists():
        _remove_workspace(workspace, strict=True)
    workspace.mkdir(parents=True, exist_ok=True)
    for item in files:
        try:
            path = _safe_path(item.get("path"))
        except RuntimeError as exc:
            raise RuntimeError("Veyra sent an unsafe qualification file path.") from exc
        if _protected_path(path):
            raise RuntimeError("Veyra sent an unsafe qualification file path.")
        destination = (workspace / path).resolve()
        if workspace.resolve() not in destination.parents:
            raise RuntimeError("Veyra sent an unsafe qualification file path.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(item.get("content") or ""), encoding="utf-8")


def _preview(text: str, limit: int = 200) -> str:
    """First `limit` characters of an upstream body, for diagnosis only.

    Model output and provider errors are not credentials, but they are
    untrusted text, so this collapses whitespace and hard-truncates rather
    than pasting an arbitrarily long body into a failure message.
    """
    collapsed = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def _escape_json_string_control_characters(value: str) -> str:
    """Escape literal control characters only while inside JSON strings.

    Models sometimes place multiline source directly in a JSON string instead
    of encoding its newlines. This scanner repairs that narrow violation while
    preserving structural whitespace and every non-control character.
    """
    escapes = {
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    output: list[str] = []
    in_string = False
    escaped = False
    for character in value:
        if not in_string:
            output.append(character)
            if character == '"':
                in_string = True
            continue

        if escaped:
            output.append(character)
            escaped = False
        elif character == "\\":
            output.append(character)
            escaped = True
        elif character == '"':
            output.append(character)
            in_string = False
        elif ord(character) < 0x20:
            output.append(escapes.get(character, f"\\u{ord(character):04x}"))
        else:
            output.append(character)
    return "".join(output)


def _load_model_json(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        if exc.msg != "Invalid control character at":
            raise
        repaired = _escape_json_string_control_characters(value)
        if repaired == value:
            raise
        return json.loads(repaired)


def _extract_json_object(value: str) -> dict[str, Any]:
    """Parse the JSON object an AI model was asked to return.

    A model can stop mid-token when it hits a length cap, so the text may be
    a *prefix* of valid JSON such as `{"summary":`. The brace-slice fallback
    below used to call json.loads() unguarded, which let a raw
    `Expecting value: line 1 column 12 (char 11)` escape all the way to the
    job detail page. Every parse here is guarded and reported as a Veyra
    error that says what was wrong and shows a short excerpt.
    """
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)

    if not text:
        raise RuntimeError(
            "The AI model returned an empty response instead of the required JSON result."
        )

    try:
        payload = _load_model_json(text)
    except json.JSONDecodeError as initial_exc:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(
                "The AI model returned malformed or incomplete JSON, so Veyra could not "
                f"read the result. Parser reported: {initial_exc.msg}. "
                f"Response began: {_preview(text)}"
            ) from initial_exc
        try:
            payload = _load_model_json(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "The AI model returned malformed JSON, so Veyra could not read the result. "
                f"Parser reported: {exc.msg}. Response began: {_preview(text)}"
            ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "The AI model returned "
            f"{type(payload).__name__} instead of a JSON object. "
            f"Response began: {_preview(text)}"
        )
    return payload


def _response_json(response: Any, source: str) -> Any:
    """Read a JSON body from an upstream HTTP response, defensively.

    Checks status, then an empty body, then Content-Type, before parsing.
    Providers answer with HTML error pages, proxy timeouts and plain-text
    rate-limit notices, and calling .json() on any of those raises a bare
    JSONDecodeError that means nothing to the person reading the job page.
    """
    status = int(getattr(response, "status_code", 0) or 0)
    raw_body = getattr(response, "text", None)
    body = raw_body if isinstance(raw_body, str) else None

    if status >= 400:
        raise RuntimeError(
            f"{source} returned {status}. Response began: {_preview(body or '')}"
        )

    if body is not None:
        if not body.strip():
            raise RuntimeError(
                f"{source} returned an empty response with status {status}."
            )

        headers = getattr(response, "headers", None)
        get_header = getattr(headers, "get", None)
        header_value = get_header("content-type", "") if callable(get_header) else ""
        content_type = header_value.lower() if isinstance(header_value, str) else ""
        if content_type and "json" not in content_type:
            raise RuntimeError(
                f"{source} returned {content_type.split(';')[0]} instead of JSON "
                f"(status {status}). Response began: {_preview(body)}"
            )

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{source} returned a response Veyra could not read as JSON "
                f"(status {status}). Parser reported: {exc.msg}. "
                f"Response began: {_preview(body)}"
            ) from exc

    # A few unit-test doubles expose only response.json(). Real httpx
    # responses always take the stricter text/content-type branch above.
    try:
        return response.json()
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{source} returned a response Veyra could not read as JSON "
            f"(status {status})."
        ) from exc


def _post_ai_json(
    payload: dict[str, Any],
    *,
    source: str,
    timeout: int,
) -> Any:
    """Post one AI request with a bounded retry for transport failures only.

    This retry remains inside the current runtime step and therefore does not
    create a new Veyra assignment, lease, claim, or funding transaction.
    Provider HTTP responses and malformed model output still follow their
    existing validation and repair paths.
    """
    attempts = max(
        1,
        min(3, int(os.getenv("VEYRA_MODEL_TRANSPORT_ATTEMPTS", "2"))),
    )
    delay_seconds = max(
        0.0,
        min(10.0, float(os.getenv("VEYRA_MODEL_TRANSPORT_RETRY_DELAY_SECONDS", "1"))),
    )
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(
                f"{AI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            if attempt >= attempts:
                raise RuntimeError(
                    f"{source} request failed after {attempts} transport attempt(s): "
                    f"{_preview(str(exc)) or type(exc).__name__}."
                ) from exc
            if delay_seconds:
                time.sleep(delay_seconds)
            continue
        return _response_json(response, source)
    raise RuntimeError(f"{source} request did not produce a response.")


def _qualification_target(task: dict[str, Any]) -> str:
    raw_allowed = task.get("allowed_submission_paths")
    allowed = list(raw_allowed) if isinstance(raw_allowed, list) else []
    if len(allowed) != 1:
        raise RuntimeError(
            "Veyra qualification must declare exactly one controlled submission path."
        )
    target = _safe_path(task.get("qualification_target_path"))
    allowed_target = _safe_path(allowed[0])
    if target != allowed_target:
        raise RuntimeError(
            "Veyra qualification target does not match its controlled submission path."
        )
    if _protected_path(target):
        raise RuntimeError("Veyra qualification target is a protected path.")
    starter_paths = [
        _safe_path(item.get("path"))
        for item in list(task.get("starter_files") or [])
        if isinstance(item, dict)
    ]
    if starter_paths.count(target) != 1:
        raise RuntimeError(
            "Veyra qualification target is not present exactly once in the controlled workspace."
        )
    return target


def _run_owner_model(task: dict[str, Any]) -> list[dict[str, str]]:
    if not AI_API_KEY or AI_API_KEY == "PASTE_OWNER_PAID_KEY_HERE":
        raise RuntimeError("The owner-paid AI_API_KEY is not configured.")

    target_path = _qualification_target(task)
    starter = task.get("starter_files") or []
    prompt = (
        "You are completing a controlled Veyra coding qualification. "
        "Return JSON only, with this exact shape: "
        + json.dumps(
            {
                "files": [
                    {"path": target_path, "content": "complete replacement source"}
                ]
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + ". Return exactly the controlled target path shown; do not add files.\n\n"
        + str(task.get("instructions") or "")
        + "\n\nStarter files:\n"
        + json.dumps(starter, ensure_ascii=False, indent=2)
    )
    payload = _post_ai_json(
        {
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
        source="The owner AI provider",
        timeout=120,
    )
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
        path = _safe_path(item.get("path"))
        content = str(item.get("content") or "")
        if path == target_path:
            cleaned.append({"path": path, "content": content})
    if [item["path"] for item in cleaned] != [target_path]:
        raise RuntimeError(f"The AI model must return {target_path} only.")
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

        test_command = str(task.get("test_command") or "").strip()
        if not test_command:
            raise RuntimeError("Veyra qualification supplied no validation command.")
        command = _command_args(test_command)
        _require_command_tool(command, workspace)
        completed = _run_process(
            command,
            cwd=workspace,
            timeout=120,
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


class ModelOutputRepairError(RuntimeError):
    """The model response cannot be applied and should receive bounded repair feedback."""


class ModelOutputPolicyError(ModelOutputRepairError):
    """The model proposed a file path that violates the funded job policy."""


class RuntimePreflightError(RuntimeError):
    """The leased repository could not be prepared for funded validation."""

    def __init__(self, message: str, *, code: str = "RUNTIME_PREFLIGHT_FAILED"):
        super().__init__(message)
        self.code = code


def _path_matches_policy_rule(path: str, rule: str) -> bool:
    """Match exact paths, directory prefixes, and common recursive globs safely."""
    try:
        clean_path = _safe_path(path).casefold()
        clean_rule = _safe_path(rule).casefold()
    except RuntimeError:
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
    runtime_home = cwd.parent / f".{cwd.name}--runtime"
    runtime_home.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "HOME": str(runtime_home),
            "USERPROFILE": str(runtime_home),
            "GOCACHE": str(runtime_home / "go-build"),
            "GOMODCACHE": str(runtime_home / "go-mod"),
            "npm_config_cache": str(runtime_home / "npm-cache"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    if extra_env:
        env.update(extra_env)
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=os.name != "nt",
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        ),
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            args,
            timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def _job_python_environment(workspace: Path) -> Path:
    """Keep installed dependencies outside the Git worktree and scoped to one lease."""
    return workspace.parent / f".{workspace.name}--python"


def _python_environment_executable(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _explicit_validation_commands(task: dict[str, Any]) -> list[str]:
    policy = task.get("policy") if isinstance(task.get("policy"), dict) else {}
    return [
        str(value).strip()
        for value in list(policy.get("required_commands") or [])
        if str(value).strip()
    ]


def _package_json(workspace: Path) -> dict[str, Any]:
    path = workspace / "package.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimePreflightError(
            "package.json is present but invalid, so validation cannot be selected.",
            code="INVALID_PROJECT_MANIFEST",
        ) from exc
    if not isinstance(value, dict):
        raise RuntimePreflightError(
            "package.json must contain a JSON object.",
            code="INVALID_PROJECT_MANIFEST",
        )
    return value


def _node_package_manager(workspace: Path) -> str:
    if (workspace / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (workspace / "yarn.lock").is_file():
        return "yarn"
    return "npm"


def _wrapper_or_tool(
    workspace: Path,
    *,
    unix_name: str,
    windows_name: str,
    tool: str,
) -> str:
    if os.name == "nt" and (workspace / windows_name).is_file():
        return windows_name
    if (workspace / unix_name).is_file():
        return f"./{unix_name}"
    return tool


def _detect_validation_plan(workspace: Path) -> dict[str, Any]:
    """Infer one validation plan from repository-owned manifests and config."""
    package = _package_json(workspace)
    dependencies = {
        str(key).casefold()
        for section in ("dependencies", "devDependencies", "peerDependencies")
        if isinstance(package.get(section), dict)
        for key in package[section]
    }
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    hardhat = any(workspace.glob("hardhat.config.*")) or "hardhat" in dependencies

    candidates: list[dict[str, Any]] = []
    if (workspace / "foundry.toml").is_file():
        candidates.append({"stack": "foundry", "commands": ["forge test -q"]})
    if hardhat:
        manager = _node_package_manager(workspace)
        command = (
            f"{manager} test"
            if str(scripts.get("test") or "").strip()
            else "npx --no-install hardhat test"
        )
        candidates.append({"stack": "hardhat", "commands": [command]})
    elif package:
        if str(scripts.get("test") or "").strip():
            candidates.append(
                {
                    "stack": "node",
                    "commands": [f"{_node_package_manager(workspace)} test"],
                }
            )
    if (workspace / "Cargo.toml").is_file():
        candidates.append({"stack": "rust", "commands": ["cargo test --quiet"]})
    if (workspace / "go.mod").is_file():
        candidates.append({"stack": "go", "commands": ["go test ./..."]})
    if (workspace / "pom.xml").is_file():
        tool = _wrapper_or_tool(
            workspace,
            unix_name="mvnw",
            windows_name="mvnw.cmd",
            tool="mvn",
        )
        candidates.append({"stack": "maven", "commands": [f"{tool} test"]})
    if any((workspace / name).is_file() for name in ("build.gradle", "build.gradle.kts")):
        tool = _wrapper_or_tool(
            workspace,
            unix_name="gradlew",
            windows_name="gradlew.bat",
            tool="gradle",
        )
        candidates.append({"stack": "gradle", "commands": [f"{tool} test"]})
    if (workspace / "composer.json").is_file():
        try:
            composer = json.loads((workspace / "composer.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimePreflightError(
                "composer.json is present but invalid, so validation cannot be selected.",
                code="INVALID_PROJECT_MANIFEST",
            ) from exc
        composer_scripts = composer.get("scripts") if isinstance(composer, dict) else {}
        command = "composer test" if isinstance(composer_scripts, dict) and composer_scripts.get("test") else "php vendor/bin/phpunit"
        if (workspace / "phpunit.xml").is_file() or (workspace / "phpunit.xml.dist").is_file() or command == "composer test":
            candidates.append({"stack": "php", "commands": [command]})
    if (workspace / "Gemfile").is_file():
        if (workspace / "Rakefile").is_file():
            command = "bundle exec rake test"
        elif (workspace / ".rspec").is_file() or (workspace / "spec").is_dir():
            command = "bundle exec rspec"
        else:
            command = ""
        if command:
            candidates.append({"stack": "ruby", "commands": [command]})

    python_markers = any(
        (workspace / name).is_file()
        for name in ("pyproject.toml", "requirements.txt", "setup.py", "pytest.ini", "tox.ini")
    )
    python_tests = any((workspace / "tests").glob("test*.py")) if (workspace / "tests").is_dir() else False
    if python_markers or python_tests:
        command = "python -m pytest -q" if python_tests or (workspace / "pytest.ini").is_file() else "python -m unittest discover -v"
        candidates.append({"stack": "python", "commands": [command]})

    if not candidates:
        raise RuntimePreflightError(
            "No supported validation toolchain was detected from repository manifests or test configuration.",
            code="UNSUPPORTED_TOOLCHAIN",
        )
    stacks = sorted({candidate["stack"] for candidate in candidates})
    if len(stacks) != 1:
        raise RuntimePreflightError(
            "Multiple validation toolchains were detected without explicit funded commands: "
            + ", ".join(stacks)
            + ".",
            code="AMBIGUOUS_TOOLCHAIN",
        )
    return {**candidates[0], "source": "repository_detection"}


def _validation_plan(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    explicit = _explicit_validation_commands(task)
    if explicit:
        stacks = {
            _command_stack(command)
            for command in explicit
            if _command_stack(command)
        }
        stack = stacks.pop() if len(stacks) == 1 else "explicit"
        return {"stack": stack, "commands": explicit, "source": "funded_policy"}
    return _detect_validation_plan(workspace)


def _validation_commands(task: dict[str, Any], workspace: Path | None = None) -> list[str]:
    explicit = _explicit_validation_commands(task)
    if explicit:
        return explicit
    if workspace is None:
        raise RuntimePreflightError(
            "Repository evidence is required when funded validation commands are absent.",
            code="VALIDATION_CONTEXT_REQUIRED",
        )
    return list(_detect_validation_plan(workspace)["commands"])


def _uses_python_validation(task: dict[str, Any], workspace: Path) -> bool:
    for command in _validation_commands(task, workspace):
        args = shlex.split(command, posix=os.name != "nt")
        if args and Path(args[0]).name.casefold() in {"python", "python3", "pytest"}:
            return True
    return False


def _preflight_output(completed: subprocess.CompletedProcess[str]) -> str:
    return _safe_runtime_text(
        "\n".join(
            part for part in (completed.stdout, completed.stderr) if part
        ).strip(),
        limit=4000,
    )


def _pyproject_dependencies(pyproject: Path) -> list[str]:
    try:
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimePreflightError(
            f"The declared pyproject.toml could not be read: {exc}"
        ) from exc
    project = metadata.get("project")
    if not isinstance(project, dict):
        return []
    dependencies = [
        str(value).strip()
        for value in list(project.get("dependencies") or [])
        if str(value).strip()
    ]
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        dependencies.extend(
            str(value).strip()
            for value in list(optional.get("test") or [])
            if str(value).strip()
        )
    return dependencies


def _prepare_validation_environment(
    task: dict[str, Any],
    workspace: Path,
    environment: Path,
) -> tuple[Path, str, str]:
    """Prepare declared dependencies for the selected repository toolchain."""
    plan = _validation_plan(task, workspace)
    requirements = workspace / "requirements.txt"
    pyproject = workspace / "pyproject.toml"
    uses_python = _uses_python_validation(task, workspace)
    if not uses_python:
        stack = str(plan["stack"])
        preparation: list[str] = []
        if stack in {"node", "hardhat"} or (stack == "explicit" and (workspace / "package.json").is_file()):
            manager = _node_package_manager(workspace)
            if manager == "pnpm":
                preparation = ["pnpm install --frozen-lockfile"]
            elif manager == "yarn":
                preparation = ["yarn install --immutable"]
            elif (workspace / "package-lock.json").is_file():
                preparation = ["npm ci"]
            else:
                preparation = ["npm install --no-package-lock"]
        elif stack == "rust":
            preparation = ["cargo fetch" + (" --locked" if (workspace / "Cargo.lock").is_file() else "")]
        elif stack == "go":
            preparation = ["go mod download"]
        elif stack == "php":
            preparation = ["composer install --no-interaction --prefer-dist"]
        elif stack == "ruby":
            preparation = ["bundle install"]
        if not preparation:
            return Path(sys.executable), "", ""
        command = preparation[0]
        args = _command_args(command, preparation=True)
        _require_command_tool(args, workspace)
        completed = _run_process(
            args,
            cwd=workspace,
            timeout=max(180, int((task.get("policy") or {}).get("maximum_execution_minutes") or 45) * 60),
        )
        output = _preflight_output(completed)
        if completed.returncode != 0:
            raise RuntimePreflightError(
                f"{stack} dependency preparation failed: {output}",
                code="DEPENDENCY_PREPARATION_FAILED",
            )
        return Path(sys.executable), output, command

    if not (requirements.is_file() or pyproject.is_file()):
        return Path(sys.executable), "", ""

    _remove_workspace(environment, strict=True)
    environment.parent.mkdir(parents=True, exist_ok=True)
    create = _run_process(
        [sys.executable, "-m", "venv", str(environment)],
        cwd=workspace,
        timeout=180,
    )
    if create.returncode != 0:
        raise RuntimePreflightError(
            "Python environment creation failed before funded validation: "
            + _preflight_output(create),
            code="DEPENDENCY_PREPARATION_FAILED",
        )

    python_executable = _python_environment_executable(environment)
    if not python_executable.is_file():
        raise RuntimePreflightError(
            "Python environment creation completed without a usable interpreter.",
            code="DEPENDENCY_PREPARATION_FAILED",
        )

    if requirements.is_file():
        install_args = ["-r", "requirements.txt"]
        display_command = "python -m pip install -r requirements.txt"
    else:
        install_args = _pyproject_dependencies(pyproject)
        if not install_args:
            return python_executable, "", ""
        display_command = "python -m pip install <declared pyproject dependencies>"

    install = _run_process(
        [
            str(python_executable),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *install_args,
        ],
        cwd=workspace,
        timeout=max(
            180,
            int((task.get("policy") or {}).get("maximum_execution_minutes") or 45)
            * 60,
        ),
        extra_env={
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PIP_REQUIRE_VIRTUALENV": "1",
        },
    )
    output = _preflight_output(install)
    if install.returncode != 0:
        raise RuntimePreflightError(
            f"Declared dependency installation failed before funded validation: {output}",
            code="DEPENDENCY_PREPARATION_FAILED",
        )
    return python_executable, output, display_command


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


REPOSITORY_EXCLUDED_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
}


def _repository_paths(workspace: Path) -> list[str]:
    """Enumerate existing regular files using canonical repository-relative paths."""
    root = workspace.resolve()
    result: list[str] = []
    for candidate in workspace.rglob("*"):
        try:
            relative = _safe_path(candidate.relative_to(workspace).as_posix())
        except (OSError, RuntimeError, ValueError):
            continue
        if any(
            part.casefold() in REPOSITORY_EXCLUDED_PARTS
            for part in relative.split("/")
        ):
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if root not in resolved.parents:
            continue
        result.append(relative)
    return sorted(set(result), key=lambda value: (value.casefold(), value))


def _resolve_funded_repository_path(
    value: Any,
    repository_paths: list[str],
) -> str:
    """Resolve an untrusted spelling to one existing canonical repository path."""
    try:
        selected = _safe_path(value)
    except RuntimeError as exc:
        raise ModelOutputPolicyError(str(exc)) from exc
    available = [_safe_path(path) for path in repository_paths]
    if selected in available:
        return selected
    folded_matches = [
        path for path in available if path.casefold() == selected.casefold()
    ]
    if len(folded_matches) != 1:
        raise ModelOutputPolicyError(
            f"The AI model returned an unknown funded repository path: {selected}"
        )
    return folded_matches[0]


def _repository_context(workspace: Path) -> list[dict[str, str]]:
    maximum = max(20_000, int(os.getenv("VEYRA_MODEL_CONTEXT_CHARACTERS", "180000")))
    total = 0
    result: list[dict[str, str]] = []
    for relative in _repository_paths(workspace):
        basename = relative.rsplit("/", 1)[-1].casefold()
        if basename == ".env" or basename.startswith(".env."):
            continue
        path = workspace.joinpath(*relative.split("/"))
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if "\x00" in content:
            continue
        if len(content) > 40_000:
            content = content[:40_000]
        if total + len(content) > maximum:
            break
        total += len(content)
        result.append({"path": relative, "content": content})
    return result


def _trusted_model_paths(
    allowed_paths: list[str],
    repository_paths: list[str],
) -> list[str]:
    """Return exact funded paths that can be represented by opaque model IDs."""
    normalized_allowed = [_safe_path(path) for path in allowed_paths]
    normalized_repository = [_safe_path(path) for path in repository_paths]
    permitted_repository_paths = [
        path
        for path in normalized_repository
        if not normalized_allowed
        or any(_path_matches_policy_rule(path, rule) for rule in normalized_allowed)
    ]
    result: list[str] = []
    seen: set[str] = set()
    for path in permitted_repository_paths:
        key = path.casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _extract_model_files(
    content: str,
    *,
    path_ids: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], str]:
    try:
        payload = _extract_json_object(content)
    except RuntimeError as exc:
        raise ModelOutputRepairError(str(exc)) from exc
    values = payload.get("files")
    if not isinstance(values, list) or not values:
        raise ModelOutputRepairError(
            "The AI model returned no changed files. Return at least one complete file "
            "in the JSON files array."
        )
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        path_id = str(item.get("path_id") or "").strip()
        if path_id:
            mapped_path = (path_ids or {}).get(path_id)
            if not mapped_path:
                # Some models copy the trusted filename value into path_id
                # instead of its FILE_n key. Exact values remain confined to
                # the same funded-path allowlist; near misses are rejected.
                try:
                    mapped_path = _resolve_funded_repository_path(
                        path_id,
                        list((path_ids or {}).values()),
                    )
                except ModelOutputPolicyError:
                    mapped_path = None
            if not mapped_path:
                raise ModelOutputPolicyError(
                    f"The AI model returned an unknown funded path ID: {path_id}"
                )
            mapped_path = _safe_path(mapped_path)
            supplied_path = str(item.get("path") or "").strip()
            if supplied_path and _safe_path(supplied_path).casefold() != mapped_path.casefold():
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
        raise ModelOutputRepairError(
            "The AI model returned no valid changed files. Return at least one complete "
            "file with a valid funded path."
        )
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
    context = _repository_context(workspace)
    repository_paths = _repository_paths(workspace)
    trusted_paths = _trusted_model_paths(allowed_paths, repository_paths)
    path_ids = {
        f"FILE_{index}": path
        for index, path in enumerate(trusted_paths, start=1)
    }
    path_id_contract = json.dumps(path_ids, ensure_ascii=False)
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
    payload = _post_ai_json(
        {
            "model": AI_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON with complete changed files. "
                        f"Use these trusted path IDs instead of spelling filenames: "
                        f"{path_id_contract}. "
                        f"Funded allowed-path rules are: {allowed_path_contract}. "
                        "Any explicit path must satisfy those rules and the protected-path policy."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        },
        source="The owner AI provider",
        timeout=max(120, int(os.getenv("VEYRA_MODEL_TIMEOUT_SECONDS", "240"))),
    )
    choices = payload.get("choices") if isinstance(payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else ""
    return _extract_model_files(str(content or ""), path_ids=path_ids)


def _apply_model_files(task: dict[str, Any], workspace: Path, files: list[dict[str, str]]) -> None:
    paths = [item["path"] for item in files]
    _enforce_job_path_policy(task, paths)
    repository_paths = _repository_paths(workspace)
    root = workspace.resolve()
    for item in files:
        repository_path = _resolve_funded_repository_path(item["path"], repository_paths)
        destination = workspace.joinpath(*repository_path.split("/")).resolve()
        if root not in destination.parents:
            raise RuntimeError("The model attempted to write outside the job workspace.")
        destination.write_text(item["content"], encoding="utf-8")
        item["path"] = repository_path


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
        except ModelOutputRepairError as exc:
            if repair_attempt >= maximum_repairs:
                raise
            allowed = list(policy.get("allowed_paths") or [])
            repository_paths = [item.get("path") for item in _repository_context(workspace)]
            feedback = (
                f"MODEL OUTPUT REPAIR ERROR: {exc}\n"
                f"Allowed paths: {json.dumps(allowed)}\n"
                f"Existing repository paths: {json.dumps(repository_paths)}\n"
                "Return corrected JSON only. Copy paths exactly. Do not broaden or bypass policy."
            )
    raise RuntimeError("The AI model could not produce policy-compliant file output.")


def _command_args(
    command: str,
    *,
    python_executable: str | Path | None = None,
    preparation: bool = False,
) -> list[str]:
    args = shlex.split(str(command), posix=os.name != "nt")
    if not args:
        raise RuntimeError("Veyra supplied an empty validation command.")
    if any(
        "\x00" in value
        or "\n" in value
        or "\r" in value
        or value in {"&&", "||", "|", ";", ">", ">>", "<", "2>", "2>&1"}
        for value in args
    ):
        raise RuntimeError("Validation commands may not contain shell operators.")
    allowed = {
        "python", "python3", "pytest", "node", "npm", "pnpm", "yarn", "npx",
        "cargo", "go", "mvn", "mvnw", "mvnw.cmd", "gradle", "gradlew",
        "gradlew.bat", "php", "composer", "bundle", "forge",
    }
    executable = Path(args[0].removeprefix("./")).name.casefold()
    if executable not in allowed:
        raise RuntimePreflightError(
            f"Validation command is not allowed in this runtime: {args[0]}",
            code="UNSAFE_VALIDATION_COMMAND",
        )
    selected_python = str(python_executable or sys.executable)
    if executable in {"python", "python3"}:
        valid_python = (
            len(args) >= 3
            and args[1:3] in (["-m", "pytest"], ["-m", "unittest"])
        ) or (
            len(args) >= 3
            and Path(args[1]).name.casefold() == "manage.py"
            and args[2].casefold() == "test"
        )
        if not valid_python:
            raise RuntimePreflightError(
                "Python validation is restricted to pytest, unittest, or manage.py test.",
                code="UNSAFE_VALIDATION_COMMAND",
            )
        args[0] = selected_python
    if executable == "pytest":
        # Invoke pytest through the lease's Python environment on every host.
        args = [selected_python, "-m", "pytest", *args[1:]]
    if executable == "node" and (len(args) < 2 or args[1].casefold() != "--test"):
        raise RuntimePreflightError(
            "Node validation is restricted to the built-in node --test runner.",
            code="UNSAFE_VALIDATION_COMMAND",
        )
    if executable in {"npm", "pnpm", "yarn"}:
        allowed_actions = {"test", "run"}
        if preparation:
            allowed_actions.update({"install", "ci"})
        if len(args) < 2 or args[1].casefold() not in allowed_actions:
            raise RuntimePreflightError(
                "Package-manager execution is restricted to test, run, install, or ci.",
                code="UNSAFE_VALIDATION_COMMAND",
            )
    fixed_prefixes: dict[str, tuple[tuple[str, ...], ...]] = {
        "npx": (("--no-install", "hardhat", "test"),),
        "cargo": (("test",),),
        "go": (("test",),),
        "mvn": (("test",),),
        "mvnw": (("test",),),
        "mvnw.cmd": (("test",),),
        "gradle": (("test",),),
        "gradlew": (("test",),),
        "gradlew.bat": (("test",),),
        "php": (("vendor/bin/phpunit",),),
        "composer": (("test",),),
        "bundle": (("exec", "rake", "test"), ("exec", "rspec")),
        "forge": (("test",),),
    }
    if preparation:
        fixed_prefixes.update(
            {
                "cargo": (("fetch",),),
                "go": (("mod", "download"),),
                "composer": (("install",),),
                "bundle": (("install",),),
            }
        )
    prefixes = fixed_prefixes.get(executable)
    if prefixes and not any(
        tuple(value.casefold() for value in args[1 : 1 + len(prefix)]) == prefix
        for prefix in prefixes
    ):
        raise RuntimePreflightError(
            f"Validation command is outside the allowed {executable} operations.",
            code="UNSAFE_VALIDATION_COMMAND",
        )
    return args


def _command_stack(command: str) -> str:
    args = shlex.split(str(command), posix=os.name != "nt")
    if not args:
        return ""
    executable = Path(args[0].removeprefix("./")).name.casefold()
    if executable in {"python", "python3", "pytest"}:
        return "python"
    if executable in {"node", "npm", "pnpm", "yarn"}:
        return "node"
    if executable == "npx" and any(value.casefold() == "hardhat" for value in args[1:]):
        return "hardhat"
    if executable == "cargo":
        return "rust"
    if executable == "go":
        return "go"
    if executable in {"mvn", "mvnw", "mvnw.cmd"}:
        return "maven"
    if executable in {"gradle", "gradlew", "gradlew.bat"}:
        return "gradle"
    if executable in {"php", "composer"}:
        return "php"
    if executable == "bundle":
        return "ruby"
    if executable == "forge":
        return "foundry"
    return ""


def _require_command_tool(args: list[str], workspace: Path) -> None:
    if not args:
        raise RuntimePreflightError(
            "Validation resolved to an empty command.",
            code="UNSAFE_VALIDATION_COMMAND",
        )
    executable = str(args[0])
    candidate = Path(executable)
    if candidate.is_absolute():
        available = candidate.is_file()
    elif executable.startswith("./") or executable.startswith(".\\"):
        resolved = (workspace / executable).resolve()
        available = workspace.resolve() in resolved.parents and resolved.is_file()
    elif Path(executable).name.casefold() in {"mvnw", "mvnw.cmd", "gradlew", "gradlew.bat"}:
        available = (workspace / Path(executable).name).is_file()
        if available:
            args[0] = str((workspace / Path(executable).name).resolve())
    else:
        resolved = shutil.which(executable)
        available = resolved is not None
        if resolved:
            args[0] = resolved
    if not available:
        raise RuntimePreflightError(
            f"Required validation tool is unavailable: {Path(executable).name}",
            code="TOOLCHAIN_UNAVAILABLE",
        )


def _validation_plan_evidence(plan: dict[str, Any] | None) -> dict[str, Any]:
    selected = plan or {}
    return {
        "validation_toolchain": str(selected.get("stack") or "unknown"),
        "validation_command_source": str(selected.get("source") or "unknown"),
        "validation_commands": [
            str(value)
            for value in list(selected.get("commands") or [])
            if str(value).strip()
        ],
    }


def _runtime_failure_details(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, RuntimePreflightError):
        return "runtime_preflight", exc.code
    return "runtime_execution", "RUNTIME_EXECUTION_FAILED"


def _run_validation_commands(
    task: dict[str, Any],
    workspace: Path,
    *,
    python_executable: str | Path | None = None,
) -> tuple[int, str, str]:
    policy = task.get("policy") or {}
    commands = _validation_commands(task, workspace)
    outputs: list[str] = []
    final_code = 0
    timeout = max(60, int(policy.get("maximum_execution_minutes") or 45) * 60)
    for command in commands:
        args = _command_args(command, python_executable=python_executable)
        _require_command_tool(args, workspace)
        completed = _run_process(
            args,
            cwd=workspace,
            timeout=timeout,
        )
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


def _set_job_progress(phase: str, message: str) -> None:
    with STATE_LOCK:
        state = load_state()
        state["job_phase"] = str(phase or "")[:80]
        state["job_message"] = str(message or "")[:500]
        state["job_updated_at"] = utc_now_iso()
        save_state(state)


def _set_verification_progress(phase: str, message: str) -> None:
    with STATE_LOCK:
        state = load_state()
        state["verification_phase"] = str(phase or "")[:80]
        state["verification_message"] = str(message or "")[:500]
        state["verification_updated_at"] = utc_now_iso()
        save_state(state)


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
        state["job_phase"] = "PREPARING_REPOSITORY"
        state["job_message"] = "Preparing the funded repository."
        state["job_updated_at"] = utc_now_iso()
        save_state(state)
    workspace = _job_workspace(assignment_id, lease_id)
    python_environment = _job_python_environment(workspace)
    token = ""
    validation_plan: dict[str, Any] | None = None
    try:
        credential = _repository_credential(task)
        token = str(credential["token"])
        repository = task.get("repository") or {}
        branch = str((task.get("delivery") or {}).get("branch") or "")
        target = str(repository.get("target_branch") or "main")
        _set_job_progress("PREPARING_REPOSITORY", "Cloning the funded repository and preparing the execution branch.")
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

        validation_plan = _validation_plan(task, workspace)
        _set_job_progress("PREPARING_ENVIRONMENT", "Preparing dependencies and the validation environment.")
        python_executable, setup_output, setup_command = _prepare_validation_environment(
            task,
            workspace,
            python_environment,
        )
        _set_job_progress("BASELINE_VALIDATION", "Running the funded baseline validation before code changes.")
        baseline_code, baseline_output, baseline_command = _run_validation_commands(
            task,
            workspace,
            python_executable=python_executable,
        )
        _set_job_progress("GENERATING_IMPLEMENTATION", "Generating and applying the implementation with the configured AI model.")
        files, summary, model_output_repairs = _generate_and_apply_model_files(task, workspace)
        _set_job_progress("POST_CHANGE_VALIDATION", "Running the funded validation against the generated changes.")
        code, output, command = _run_validation_commands(
            task,
            workspace,
            python_executable=python_executable,
        )
        max_repairs = max(0, int((task.get("policy") or {}).get("maximum_repair_attempts") or 0))
        repairs = 0
        while code != 0 and repairs < max_repairs:
            repairs += 1
            _set_job_progress("REPAIRING_IMPLEMENTATION", f"Repairing the implementation after validation failure (attempt {repairs} of {max_repairs}).")
            files, summary, extra_output_repairs = _generate_and_apply_model_files(
                task,
                workspace,
                previous_feedback=output,
            )
            model_output_repairs += extra_output_repairs
            _set_job_progress("POST_CHANGE_VALIDATION", "Re-running the funded validation after the repair.")
            code, output, command = _run_validation_commands(
                task,
                workspace,
                python_executable=python_executable,
            )
        if code != 0:
            raise RuntimeError(f"Post-change tests did not pass after {repairs + 1} attempt(s): {output[:1000]}")

        changed = _changed_files(workspace)
        if not changed:
            raise RuntimeError("The model produced no repository changes.")
        _enforce_job_path_policy(task, changed)
        _set_job_progress("CREATING_COMMIT", "Validation passed. Creating the exact Veyra execution commit.")
        _git(workspace, "add", "--", *changed)
        _git(workspace, "commit", "-m", f"Veyra job {job_id}: {str((task.get('work') or {}).get('title') or 'agent work')[:120]}")
        commit_sha = _git(workspace, "rev-parse", "HEAD").splitlines()[0].strip().lower()
        _set_job_progress("PUSHING_BRANCH", "Pushing the validated execution commit to the Veyra job branch.")
        _git(workspace, "push", "origin", f"HEAD:refs/heads/{branch}", token=token, timeout=180)
        _set_job_progress("CREATING_PULL_REQUEST", "Opening the pull request for independent verification.")
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
            "environment_setup_command": setup_command,
            "environment_setup_output": setup_output,
            "baseline_test_command": baseline_command,
            "baseline_test_return_code": int(baseline_code),
            "baseline_test_output": baseline_output,
            "test_command": command,
            "test_return_code": int(code),
            "test_output": output,
            **_validation_plan_evidence(validation_plan),
            "repair_attempts": repairs,
            "model_output_repair_attempts": model_output_repairs,
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "runtime_version": RUNTIME_VERSION,
            "summary": summary,
            "started_at": started_at,
            "completed_at": completed_at,
        }
        _set_job_progress("SUBMITTING_RESULT", f"Pull request #{pr_number} is ready. Submitting signed execution evidence to Veyra.")
        _submit_job_result(task, evidence)
        with STATE_LOCK:
            state = load_state()
            state["job_status"] = "submitted"
            state["job_phase"] = "SUBMITTED"
            state["job_message"] = f"Pull request #{pr_number} submitted to Veyra for on-chain submission and verification."
            state["job_updated_at"] = utc_now_iso()
            save_state(state)
        _remove_workspace(workspace, strict=False)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        message = _safe_runtime_text(exc, limit=1200)
        failure_stage, failure_code = _runtime_failure_details(exc)
        failure_evidence = {
            "outcome": "FAILED",
            "assignment_id": assignment_id,
            "lease_id": str(task.get("lease_id") or ""),
            "job_id": int(task.get("job_id") or 0),
            "failure_stage": failure_stage,
            "failure_code": failure_code,
            "failure_message": message,
            **_validation_plan_evidence(validation_plan),
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
            state["job_phase"] = "FAILED"
            state["job_message"] = message
            state["job_updated_at"] = utc_now_iso()
            save_state(state)
    finally:
        token = ""
        _remove_workspace(python_environment, strict=False)
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
    payload = _post_ai_json(
        {
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
        source="The verifier AI provider",
        timeout=max(120, int(os.getenv("VEYRA_MODEL_TIMEOUT_SECONDS", "240"))),
    )
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
        state["verification_phase"] = "PREPARING_REVIEW"
        state["verification_message"] = (
            "Preparing the exact submitted commit for independent review."
        )
        state["verification_updated_at"] = utc_now_iso()
        save_state(state)
    workspace = _verification_workspace(verification_id)
    python_environment = _job_python_environment(workspace)
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
        _set_verification_progress("CHECKING_OUT_COMMIT", "Cloning the repository with read-only access and checking out the exact submitted commit.")
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

        _set_verification_progress("PREPARING_ENVIRONMENT", "Preparing the independent verifier validation environment.")
        python_executable, setup_output, setup_command = _prepare_validation_environment(
            task,
            workspace,
            python_environment,
        )
        _set_verification_progress("RUNNING_VALIDATION", "Running the funded validation independently on the exact submitted commit.")
        return_code, test_output, test_command = _run_validation_commands(
            task,
            workspace,
            python_executable=python_executable,
        )
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
        _set_verification_progress("EVALUATING_REQUIREMENTS", "Evaluating the funded acceptance criteria and security constraints.")
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
            "environment_setup_command": setup_command,
            "environment_setup_output": setup_output,
            "acceptance_criteria": model_result["acceptance_criteria"],
            "security_findings": model_result["security_findings"],
            "provider": AI_PROVIDER,
            "model": AI_MODEL,
            "runtime_version": RUNTIME_VERSION,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
        }
        _set_verification_progress("SUBMITTING_VERDICT", "Submitting the signed independent verification report to Veyra.")
        result = _submit_verification_result(task, report)
        with STATE_LOCK:
            state = load_state()
            state["verification_status"] = str(result.get("verdict") or "submitted").lower()
            state["verification_phase"] = "COMPLETED"
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
            state["verification_phase"] = "FAILED"
            state["verification_message"] = message
            state["verification_updated_at"] = utc_now_iso()
            save_state(state)
    finally:
        token = ""
        _remove_workspace(python_environment, strict=False)
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
                        "job_assignment_id": str(state.get("job_assignment_id") or ""),
                        "job_onchain_id": str(state.get("job_onchain_id") or ""),
                        "job_status": str(state.get("job_status") or ""),
                        "job_phase": str(state.get("job_phase") or ""),
                        "job_message": str(state.get("job_message") or ""),
                        "job_updated_at": str(state.get("job_updated_at") or ""),
                        "verification_assignment_id": str(state.get("verification_assignment_id") or ""),
                        "verification_status": str(state.get("verification_status") or ""),
                        "verification_phase": str(state.get("verification_phase") or ""),
                        "verification_message": str(state.get("verification_message") or ""),
                        "verification_updated_at": str(state.get("verification_updated_at") or ""),
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
        safe_agent_name = html.escape(str(state.get("agent_name") or "Veyra agent"))
        safe_provider = html.escape(f"{AI_PROVIDER} · {AI_MODEL}")
        safe_message = html.escape(provider_message)
        runtime_role = html.escape(RUNTIME_ROLE.title())
        runtime_id = html.escape(str(state["runtime_id"]))
        heartbeat_at = html.escape(str(state.get("last_heartbeat_at") or "Not connected"))
        heartbeat_error = html.escape(str(state.get("last_heartbeat_error") or "None"))

        qualification_status = html.escape(
            str(state.get("qualification_status") or "waiting").replace("_", " ").title()
        )
        qualification_message = html.escape(
            str(state.get("qualification_message") or "Waiting for Veyra")
        )
        job_status = html.escape(
            str(state.get("job_status") or "waiting").replace("_", " ").title()
        )
        job_message = html.escape(
            str(state.get("job_message") or "Waiting for paid work")
        )
        verification_status = html.escape(
            str(state.get("verification_status") or "waiting").replace("_", " ").title()
        )
        verification_message = html.escape(
            str(
                state.get("verification_message")
                or "Waiting for a submitted worker job"
            )
        )

        favicon = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'%3E%3Crect width='120' height='120' rx='26' fill='%23F5EDE2'/%3E%3Cpath d='M24 27h18l18 49 18-49h18L68 94H52L24 27Z' fill='%23050505'/%3E%3C/svg%3E"

        if connected:
            connection_panel = f"""
            <div class='connected-state'>
              <span class='state-dot'></span>
              <div class='connected-copy'>
                <strong>Connected to Veyra</strong>
                <span>{safe_agent_name}</span>
              </div>
              <a class='manage-link' href='https://veyra.surf/agent-owner' target='_blank' rel='noreferrer'>Manage in Veyra ↗</a>
            </div>
            """
        else:
            connection_panel = f"""
            <div class='link-box'>
              <code id='link'>{safe_link}</code>
              <span class='expiry'>{'Expired' if expired else 'Expires'} <time id='link-expiry'>{html.escape(expiry_label)}</time></span>
            </div>
            <div class='actions'>
              <button id='copy-button' class='primary' onclick='copyLink()'>Copy connection link</button>
              <button class='secondary' onclick='rotateLink()'>Generate new link</button>
            </div>
            """

        body = f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='theme-color' content='#050505'>
<link rel='icon' type='image/svg+xml' href=\"{favicon}\">
<title>Veyra Agent Runtime</title>
<style>
:root{{--ink:#050505;--raised:#15110e;--cream:#f5ede2;--cream2:#fff9f1;--sand:#c4ad8d;--muted:#aa9a88;--line:rgba(245,237,226,.12);--soft:rgba(245,237,226,.055)}}
*{{box-sizing:border-box}}
html{{background:var(--ink)}}
body{{margin:0;min-height:100vh;background:radial-gradient(circle at 82% 0%,rgba(196,173,141,.10),transparent 28rem),var(--ink);color:var(--cream);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
a{{color:inherit}}
.shell{{width:min(900px,calc(100% - 32px));margin:0 auto;padding:28px 0 42px}}
.nav{{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:40px}}
.brand{{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:760}}
.mark{{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:var(--cream)}}
.mark svg{{width:21px;height:21px}}
.nav-links{{display:flex;align-items:center;gap:7px}}
.nav-link{{display:inline-flex;align-items:center;min-height:36px;padding:0 11px;border:1px solid var(--line);border-radius:999px;color:var(--muted);text-decoration:none;font-size:12px;font-weight:700}}
.nav-link:hover{{color:var(--cream);background:var(--soft)}}
.heading{{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:18px}}
.heading h1{{margin:0;font-size:clamp(30px,5vw,44px);line-height:1;letter-spacing:-.04em;font-weight:720}}
.heading p{{margin:8px 0 0;color:var(--muted);font-size:13px}}
.badges{{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}}
.pill{{display:inline-flex;align-items:center;gap:7px;min-height:32px;padding:0 10px;border:1px solid var(--line);border-radius:999px;background:var(--soft);font-size:11px;font-weight:760}}
.pill:before{{content:"";width:6px;height:6px;border-radius:999px;background:currentColor}}
.ok{{color:#b8e5c5}} .warn{{color:#efc884}} .ready{{color:var(--sand)}}
.panel{{border:1px solid var(--line);border-radius:18px;background:rgba(21,17,14,.78)}}
.connect{{padding:20px}}
.section-label{{display:block;margin-bottom:11px;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}}
.connected-state{{display:flex;align-items:center;gap:12px;min-height:72px;padding:14px;border:1px solid rgba(184,229,197,.16);border-radius:13px;background:rgba(184,229,197,.04)}}
.state-dot{{flex:none;width:9px;height:9px;border-radius:999px;background:#b8e5c5;box-shadow:0 0 0 5px rgba(184,229,197,.07)}}
.connected-copy{{min-width:0;flex:1}}
.connected-copy strong{{display:block;font-size:14px}}
.connected-copy span{{display:block;margin-top:3px;color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.manage-link{{flex:none;display:inline-flex;align-items:center;min-height:36px;padding:0 12px;border:1px solid var(--line);border-radius:999px;color:var(--cream);text-decoration:none;font-size:11px;font-weight:760}}
.manage-link:hover{{background:var(--soft)}}
.link-box{{position:relative}}
code{{display:block;min-height:76px;padding:16px 16px 32px;border:1px solid var(--line);border-radius:13px;background:#080706;color:#e3d2bb;font:600 12px/1.5 "SFMono-Regular",Consolas,monospace;word-break:break-all;white-space:pre-wrap}}
.expiry{{position:absolute;left:16px;bottom:9px;color:var(--muted);font-size:10px}}
.actions{{display:flex;gap:9px;margin-top:11px}}
button{{appearance:none;border:0;min-height:40px;padding:0 15px;border-radius:999px;font:750 12px/1 Inter,ui-sans-serif,system-ui;cursor:pointer}}
.primary{{background:var(--cream);color:var(--ink)}}
.secondary{{background:transparent;color:var(--cream);border:1px solid var(--line)}}
.status{{margin-top:12px;padding:18px}}
.status-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}}
.stat{{padding:13px;border:1px solid rgba(245,237,226,.09);border-radius:13px;background:rgba(5,5,5,.2)}}
.stat-label{{display:block;color:var(--muted);font-size:9px;font-weight:760;letter-spacing:.06em;text-transform:uppercase}}
.stat-value{{display:block;margin-top:6px;color:var(--cream2);font-size:13px;font-weight:700;word-break:break-word}}
details{{margin-top:12px;border:1px solid var(--line);border-radius:14px;background:rgba(13,11,9,.66)}}
summary{{cursor:pointer;list-style:none;padding:14px 16px;color:var(--muted);font-size:11px;font-weight:720}}
summary::-webkit-details-marker{{display:none}}
summary:after{{content:"+";float:right;color:var(--sand)}}
details[open] summary:after{{content:"–"}}
.detail-body{{border-top:1px solid var(--line);padding:14px 16px}}
dl{{display:grid;grid-template-columns:145px 1fr;gap:8px 14px;margin:0;font-size:11px;line-height:1.5}}
dt{{color:var(--muted)}} dd{{margin:0;color:var(--cream);word-break:break-word}}
.footer{{margin-top:16px;color:#75695c;font-size:10px;text-align:center}}
@media(max-width:760px){{.heading{{display:block}}.badges{{justify-content:flex-start;margin-top:13px}}.status-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.connected-state{{align-items:flex-start;flex-wrap:wrap}}.manage-link{{margin-left:21px}}}}
@media(max-width:520px){{.shell{{width:min(100% - 20px,900px);padding-top:16px}}.nav{{margin-bottom:28px}}.brand span:last-child{{display:none}}.heading h1{{font-size:34px}}.status-grid{{grid-template-columns:1fr}}.actions{{flex-direction:column}}button{{width:100%}}dl{{grid-template-columns:1fr;gap:3px}}dd{{margin-bottom:7px}}.manage-link{{width:100%;justify-content:center;margin-left:0}}}}
</style>
</head>
<body>
<!-- veyra-runtime-console-v3 -->
<main class='shell'>
  <nav class='nav'>
    <div class='brand'>
      <span class='mark' aria-hidden='true'><svg viewBox='0 0 120 120'><path d='M24 27h18l18 49 18-49h18L68 94H52L24 27Z' fill='#050505'/></svg></span>
      <span>Veyra Runtime</span>
    </div>
    <div class='nav-links'>
      <a class='nav-link' href='https://docs.veyra.surf/docs/agent-runtime/overview' target='_blank' rel='noreferrer'>Docs ↗</a>
      <a class='nav-link' href='https://veyra.surf/agent-owner' target='_blank' rel='noreferrer'>Open Veyra ↗</a>
    </div>
  </nav>

  <header class='heading'>
    <div>
      <h1>Agent Runtime</h1>
      <p>{'Runtime connected to Veyra.' if connected else 'Connect this runtime to Veyra.'}</p>
    </div>
    <div class='badges'>
      <span class='pill {status_class}'>{status_label}</span>
      <span class='pill {'ok' if ready else 'warn'}'>{'Provider ready' if ready else 'Provider issue'}</span>
    </div>
  </header>

  <section class='panel connect'>
    <span class='section-label'>Connection</span>
    {connection_panel}
  </section>

  <section class='panel status'>
    <span class='section-label'>Status</span>
    <div class='status-grid'>
      <div class='stat'><span class='stat-label'>Provider</span><span class='stat-value'>{'Ready' if ready else 'Check'}</span></div>
      <div class='stat'><span class='stat-label'>Qualification</span><span class='stat-value'>{qualification_status}</span></div>
      <div class='stat'><span class='stat-label'>Paid job</span><span class='stat-value'>{job_status}</span></div>
      <div class='stat'><span class='stat-label'>Verification</span><span class='stat-value'>{verification_status}</span></div>
    </div>
  </section>

  <details>
    <summary>Runtime details</summary>
    <div class='detail-body'>
      <dl>
        <dt>Role</dt><dd>{runtime_role}</dd>
        <dt>Provider / model</dt><dd>{safe_provider}</dd>
        <dt>Provider detail</dt><dd>{safe_message}</dd>
        <dt>Runtime ID</dt><dd>{runtime_id}</dd>
        <dt>Last heartbeat</dt><dd>{heartbeat_at}</dd>
        <dt>Heartbeat error</dt><dd>{heartbeat_error}</dd>
        <dt>Qualification detail</dt><dd>{qualification_message}</dd>
        <dt>Job detail</dt><dd>{job_message}</dd>
        <dt>Verification detail</dt><dd>{verification_message}</dd>
      </dl>
    </div>
  </details>

  <footer class='footer'>Veyra Agent Runtime · Protocol v{PROTOCOL_VERSION}</footer>
</main>
<script>
async function copyLink(){{
  const button=document.getElementById('copy-button');
  const link=document.getElementById('link');
  if(!button||!link)return;
  await navigator.clipboard.writeText(link.innerText);
  const previous=button.innerText;
  button.innerText='Copied';
  setTimeout(()=>button.innerText=previous,1200);
}}
async function rotateLink(){{
  const r=await fetch('/veyra/connect/rotate',{{method:'POST'}});
  const j=await r.json();
  if(!r.ok){{window.alert(j.detail||'Could not generate a new link');return;}}
  window.location.reload();
}}
</script>
</body></html>"""
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
