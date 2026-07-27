from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from workers.hosted_runtime import HOSTED_RUNTIME_MODE, OWNER_HOSTED_RUNTIME_MODE
from workers.models import RunnerAgentBinding, RunnerDevice, WorkerAgent


RUNTIME_NOT_CONNECTED = "NOT_CONNECTED"
RUNTIME_PAIRED = "PAIRED"
RUNTIME_ONLINE = "ONLINE"
RUNTIME_OFFLINE = "OFFLINE"
RUNTIME_UNHEALTHY = "UNHEALTHY"
RUNTIME_REVOKED = "REVOKED"


def _empty_runtime() -> dict:
    return {
        "status": RUNTIME_NOT_CONNECTED,
        "paired": False,
        "connected": False,
        "runtime_mode": HOSTED_RUNTIME_MODE,
        "managed_by": "VEYRA",
        "auto_start": True,
        "runner_id": None,
        "runner_name": "",
        "runner_version": "",
        "os_name": "",
        "os_version": "",
        "architecture": "",
        "python_version": "",
        "last_seen_at": None,
        "provisioned_at": None,
        "health_message": "",
        "tools": {},
    }


def runtime_snapshot(worker: WorkerAgent) -> dict:
    """Return the owner-safe, dynamically evaluated runtime state for an agent."""

    try:
        binding = worker.runtime_binding
    except RunnerAgentBinding.DoesNotExist:
        return _empty_runtime()

    runner = binding.runner
    tools = runner.tools if isinstance(runner.tools, dict) else {}
    runtime_mode = tools.get("runtime_mode") or OWNER_HOSTED_RUNTIME_MODE
    hosted = runtime_mode == HOSTED_RUNTIME_MODE

    base = {
        "paired": binding.status == RunnerAgentBinding.Status.ACTIVE,
        "connected": False,
        "runtime_mode": runtime_mode,
        "managed_by": "VEYRA" if hosted else "OWNER",
        "auto_start": hosted,
        "runner_id": str(runner.id),
        "runner_name": runner.name,
        "runner_version": runner.runner_version,
        "os_name": runner.os_name,
        "os_version": runner.os_version,
        "architecture": runner.architecture,
        "python_version": runner.python_version,
        "last_seen_at": runner.last_seen_at,
        "provisioned_at": binding.paired_at,
        "health_message": runner.health_message,
        "tools": tools,
    }

    if (
        binding.status != RunnerAgentBinding.Status.ACTIVE
        or runner.status != RunnerDevice.Status.ACTIVE
    ):
        return {**base, "status": RUNTIME_REVOKED, "paired": False}

    if hosted:
        if runner.health != RunnerDevice.Health.HEALTHY:
            return {**base, "status": RUNTIME_UNHEALTHY}
        return {
            **base,
            "status": RUNTIME_ONLINE,
            "connected": True,
            "last_seen_at": timezone.now(),
        }

    if runner.last_seen_at is None:
        return {**base, "status": RUNTIME_PAIRED}

    online_window = timedelta(
        seconds=getattr(settings, "VEYRA_RUNNER_ONLINE_WINDOW_SECONDS", 35)
    )
    if timezone.now() - runner.last_seen_at > online_window:
        return {**base, "status": RUNTIME_OFFLINE}

    if runner.health != RunnerDevice.Health.HEALTHY:
        return {**base, "status": RUNTIME_UNHEALTHY}

    return {**base, "status": RUNTIME_ONLINE, "connected": True}
