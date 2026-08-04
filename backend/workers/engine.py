from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from django.conf import settings
from django.utils import timezone

from workers.models import WorkerAgent


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|token|secret|password)\b\s*[:=]\s*([^\s]+)"
)


@dataclass(frozen=True)
class EngineHealthResult:
    connected: bool
    provider: str
    model: str
    version: str
    executable: str
    checked_at: str
    message: str
    return_code: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class EngineConnectionError(RuntimeError):
    pass


def _safe_text(value: str | None, *, limit: int = 600) -> str:
    text = (value or "").strip()
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _resolve_executable(configured: str) -> str | None:
    configured = configured.strip()
    if not configured:
        return None

    candidate = Path(configured).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())

    resolved = shutil.which(configured)
    if resolved:
        return resolved

    # npm-installed CLIs on Windows are commonly exposed as .cmd or .ps1 shims.
    if os.name == "nt":
        for suffix in (".exe", ".cmd", ".bat", ".ps1"):
            resolved = shutil.which(f"{configured}{suffix}")
            if resolved:
                return resolved

    return None


def _command_for_platform(executable: str, args: Sequence[str]) -> list[str]:
    if os.name == "nt":
        lowered = executable.lower()
        if lowered.endswith((".cmd", ".bat")):
            command_line = subprocess.list2cmdline([executable, *args])
            return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
        if lowered.endswith(".ps1"):
            powershell = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
            return [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                executable,
                *args,
            ]
    return [executable, *args]


def check_opencode_engine(worker: WorkerAgent) -> EngineHealthResult:
    if worker.engine_provider != WorkerAgent.EngineProvider.OPENCODE:
        raise EngineConnectionError("This connector supports OpenCode workers only.")

    expected_model = settings.WORKER_ENGINE_MODEL.strip()
    if expected_model and worker.engine_model != expected_model:
        raise EngineConnectionError(
            f"Worker model is {worker.engine_model}, but runtime expects {expected_model}."
        )

    executable = _resolve_executable(settings.WORKER_ENGINE_EXECUTABLE)
    checked_at = timezone.now()
    if not executable:
        return EngineHealthResult(
            connected=False,
            provider=worker.engine_provider,
            model=worker.engine_model,
            version="",
            executable=settings.WORKER_ENGINE_EXECUTABLE,
            checked_at=checked_at.isoformat(),
            message=(
                "OpenCode executable was not found. Install it or set "
                "WORKER_ENGINE_EXECUTABLE to its full path."
            ),
        )

    args = list(settings.WORKER_ENGINE_HEALTHCHECK_ARGS)
    command = _command_for_platform(executable, args)

    try:
        completed = subprocess.run(
            command,
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=settings.WORKER_ENGINE_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return EngineHealthResult(
            connected=False,
            provider=worker.engine_provider,
            model=worker.engine_model,
            version="",
            executable=Path(executable).name,
            checked_at=checked_at.isoformat(),
            message="OpenCode health check timed out.",
        )
    except OSError as exc:
        return EngineHealthResult(
            connected=False,
            provider=worker.engine_provider,
            model=worker.engine_model,
            version="",
            executable=Path(executable).name,
            checked_at=checked_at.isoformat(),
            message=f"OpenCode could not be started: {_safe_text(str(exc))}",
        )

    stdout = _safe_text(completed.stdout)
    stderr = _safe_text(completed.stderr)
    version = (stdout or stderr).splitlines()[0].strip() if (stdout or stderr) else ""

    if completed.returncode != 0:
        detail = stderr or stdout or "OpenCode returned a non-zero status."
        return EngineHealthResult(
            connected=False,
            provider=worker.engine_provider,
            model=worker.engine_model,
            version="",
            executable=Path(executable).name,
            checked_at=checked_at.isoformat(),
            message=detail,
            return_code=completed.returncode,
        )

    if not version:
        return EngineHealthResult(
            connected=False,
            provider=worker.engine_provider,
            model=worker.engine_model,
            version="",
            executable=Path(executable).name,
            checked_at=checked_at.isoformat(),
            message="OpenCode responded without a version string.",
            return_code=completed.returncode,
        )

    return EngineHealthResult(
        connected=True,
        provider=worker.engine_provider,
        model=worker.engine_model,
        version=version,
        executable=Path(executable).name,
        checked_at=checked_at.isoformat(),
        message="OpenCode runtime is reachable and the Veyra GLM model is configured.",
        return_code=completed.returncode,
    )


def connect_worker_engine(worker: WorkerAgent) -> EngineHealthResult:
    result = check_opencode_engine(worker)
    checked_at = timezone.now()

    worker.engine_last_checked_at = checked_at
    worker.engine_connection_metadata = {
        "provider": result.provider,
        "model": result.model,
        "executable": result.executable,
        "return_code": result.return_code,
        "healthcheck_args": list(settings.WORKER_ENGINE_HEALTHCHECK_ARGS),
    }

    if result.connected:
        worker.engine_connected = True
        worker.engine_version = result.version
        worker.engine_last_error = ""
        if worker.status in {
            WorkerAgent.Status.SETUP_REQUIRED,
            WorkerAgent.Status.PROFILE_READY,
            WorkerAgent.Status.ENGINE_CONNECTED,
        }:
            worker.status = WorkerAgent.Status.ENGINE_CONNECTED
    else:
        worker.engine_connected = False
        worker.engine_version = ""
        worker.engine_last_error = result.message
        if worker.status not in {
            WorkerAgent.Status.SETUP_REQUIRED,
            WorkerAgent.Status.PROFILE_READY,
        }:
            worker.status = WorkerAgent.Status.PROFILE_READY

    worker.save(
        update_fields=[
            "engine_connected",
            "engine_version",
            "engine_last_checked_at",
            "engine_last_error",
            "engine_connection_metadata",
            "status",
            "discovery_enabled",
            "updated_at",
        ]
    )
    return result
