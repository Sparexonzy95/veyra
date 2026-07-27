from __future__ import annotations

import base64
import html
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
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
load_dotenv(ROOT / ".env")
STATE_DIR = ROOT / ".veyra-runtime"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "state.json"
PRIVATE_KEY_PATH = STATE_DIR / "ed25519-private.pem"

HOST = os.getenv("RUNTIME_BIND_HOST", "127.0.0.1")
PORT = int(os.getenv("RUNTIME_PORT", "9100"))
PUBLIC_HOST = os.getenv("RUNTIME_PUBLIC_HOST", "localhost").strip() or "localhost"
PUBLIC_PORT = os.getenv("RUNTIME_PUBLIC_PORT", str(PORT)).strip()
RUNTIME_VERSION = "veyra-owner-runtime-test/1.0.0"
PROTOCOL_VERSION = 1
TOKEN_TTL_SECONDS = int(os.getenv("CONNECTION_LINK_TTL_SECONDS", "900"))
HEARTBEAT_SECONDS = max(5, int(os.getenv("VEYRA_HEARTBEAT_SECONDS", "10")))

AI_PROVIDER = os.getenv("AI_PROVIDER", "aiand").strip()
AI_MODEL = os.getenv("AI_MODEL", "zai-org/glm-5.2").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.aiand.com/v1").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_HEALTHCHECK_MODE = os.getenv("AI_HEALTHCHECK_MODE", "live").strip().lower()

STATE_LOCK = threading.RLock()
HEARTBEAT_STARTED = False
QUALIFICATION_LOCK = threading.RLock()
QUALIFICATION_RUNNING: set[str] = set()
PROVIDER_CACHE: dict[str, Any] = {"checked_at": 0.0, "ready": False, "message": "Not checked"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def load_or_create_private_key() -> Ed25519PrivateKey:
    if PRIVATE_KEY_PATH.exists():
        return serialization.load_pem_private_key(
            PRIVATE_KEY_PATH.read_bytes(),
            password=None,
        )
    private_key = Ed25519PrivateKey.generate()
    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return private_key


PRIVATE_KEY = load_or_create_private_key()
PUBLIC_KEY_TEXT = b64url(
    PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
)


def default_state() -> dict[str, Any]:
    return {
        "runtime_id": f"runtime-{uuid.uuid4()}",
        "one_time_token": secrets.token_urlsafe(36),
        "token_expires_at": int(time.time()) + TOKEN_TTL_SECONDS,
        "token_consumed": False,
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
    }


def load_state() -> dict[str, Any]:
    with STATE_LOCK:
        if not STATE_PATH.exists():
            state = default_state()
            save_state(state)
            return state
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            state = default_state()
            save_state(state)
            return state
        required = default_state()
        for key, value in required.items():
            state.setdefault(key, value)
        return state


def save_state(state: dict[str, Any]) -> None:
    with STATE_LOCK:
        temporary = STATE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(STATE_PATH)


def rotate_connection_token() -> dict[str, Any]:
    with STATE_LOCK:
        state = load_state()
        if state.get("runtime_credential"):
            raise RuntimeError("Disconnect the existing Veyra agent before generating another link.")
        state["one_time_token"] = secrets.token_urlsafe(36)
        state["token_expires_at"] = int(time.time()) + TOKEN_TTL_SECONDS
        state["token_consumed"] = False
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
    if state.get("token_consumed"):
        return False, "This connection link has already been used."
    if int(state.get("token_expires_at") or 0) <= int(time.time()):
        return False, "This connection link has expired. Generate a new one."
    if not secrets.compare_digest(str(state.get("one_time_token") or ""), str(token or "")):
        return False, "The one-time connection token is invalid."
    return True, ""


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
    return STATE_DIR / "qualification" / safe_id


def _write_starter_files(workspace: Path, files: list[dict[str, Any]]) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
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
                with STATE_LOCK:
                    state = load_state()
                    if response.status_code == 200:
                        state["last_heartbeat_at"] = utc_now_iso()
                        state["last_heartbeat_error"] = ""
                    else:
                        state["last_heartbeat_error"] = f"Veyra returned {response.status_code}."
                    save_state(state)
                if response.status_code == 200:
                    try:
                        response_payload = response.json()
                    except Exception:
                        response_payload = {}
                    qualification_task = (
                        response_payload.get("qualification_task")
                        if isinstance(response_payload, dict)
                        else None
                    )
                    if isinstance(qualification_task, dict):
                        ensure_qualification_thread(qualification_task)
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
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "runtime_id": state["runtime_id"],
                    "runtime_version": RUNTIME_VERSION,
                    "protocol_version": PROTOCOL_VERSION,
                    "provider": AI_PROVIDER,
                    "model": AI_MODEL,
                    "provider_ready": ready,
                    "provider_message": message,
                    "connected": bool(state.get("runtime_credential")),
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
            self._send_json(HTTPStatus.CREATED, {"connection_link": connection_link(state)})
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
                    "coding": True,
                    "testing": True,
                    "git": True,
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
        link = "Connected to Veyra" if connected else connection_link(state)
        status_label = "Connected" if connected else ("Link expired" if expired else "Ready to connect")
        status_class = "ok" if connected and ready else "warn" if not ready or expired else "ready"
        safe_link = html.escape(link)
        safe_provider = html.escape(f"{AI_PROVIDER} · {AI_MODEL}")
        safe_message = html.escape(provider_message)
        heartbeat_error = html.escape(str(state.get("last_heartbeat_error") or "None"))
        qualification_status = html.escape(str(state.get("qualification_status") or "waiting"))
        qualification_message = html.escape(str(state.get("qualification_message") or "Waiting for Veyra"))
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
<h1>Veyra Hosted Agent</h1><p>The owner-paid AI key stays on this server. Copy only the connection link into Veyra.</p>
<div class='card'><span class='pill {status_class}'>{status_label}</span><h2>Connection link</h2><code id='link'>{safe_link}</code><br>
<button onclick='copyLink()' {'disabled' if connected else ''}>Copy Veyra connection link</button>
<button class='secondary' onclick='rotateLink()' {'disabled' if connected else ''}>Generate new link</button></div>
<div class='card'><h2>Runtime status</h2><dl>
<dt>AI provider</dt><dd>{safe_provider}</dd><dt>Provider readiness</dt><dd class='{'ok' if ready else 'warn'}'>{safe_message}</dd>
<dt>Runtime ID</dt><dd>{html.escape(str(state['runtime_id']))}</dd><dt>Last heartbeat</dt><dd>{html.escape(str(state.get('last_heartbeat_at') or 'Not connected'))}</dd>
<dt>Heartbeat error</dt><dd>{heartbeat_error}</dd>
<dt>Qualification</dt><dd>{qualification_status}</dd>
<dt>Qualification detail</dt><dd>{qualification_message}</dd></dl></div>
<script>
async function copyLink(){{const text=document.getElementById('link').innerText;await navigator.clipboard.writeText(text);alert('Connection link copied');}}
async function rotateLink(){{const r=await fetch('/veyra/connect/rotate',{{method:'POST'}});const j=await r.json();if(!r.ok){{alert(j.detail||'Could not rotate link');return}}document.getElementById('link').innerText=j.connection_link;}}
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
    print(f"Provider: {AI_PROVIDER} / {AI_MODEL}")
    print(f"Provider ready: {ready} ({message})")
    if state.get("runtime_credential"):
        print(f"Connected agent: {state.get('agent_name') or state.get('agent_id')}")
    else:
        print("Connection link:")
        print(connection_link(state))
    print("\nKeep this terminal open. Never paste AI_API_KEY into Veyra.\n")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
