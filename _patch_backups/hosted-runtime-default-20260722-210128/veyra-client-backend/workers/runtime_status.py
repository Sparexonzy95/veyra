from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from workers.models import RunnerAgentBinding, RunnerDevice, WorkerAgent


RUNTIME_NOT_CONNECTED = "NOT_CONNECTED"
RUNTIME_PAIRED = "PAIRED"
RUNTIME_ONLINE = "ONLINE"
RUNTIME_OFFLINE = "OFFLINE"
RUNTIME_UNHEALTHY = "UNHEALTHY"
RUNTIME_REVOKED = "REVOKED"


def runtime_snapshot(worker: WorkerAgent) -> dict:
    """Return the owner-safe, dynamically evaluated runtime state for an agent."""

    try:
        binding = worker.runtime_binding
    except RunnerAgentBinding.DoesNotExist:
        return {
            "status": RUNTIME_NOT_CONNECTED,
            "paired": False,
            "connected": False,
            "runner_id": None,
            "runner_name": "",
            "runner_version": "",
            "os_name": "",
            "os_version": "",
            "architecture": "",
            "python_version": "",
            "last_seen_at": None,
            "health_message": "",
            "tools": {},
        }

    runner = binding.runner
    base = {
        "paired": binding.status == RunnerAgentBinding.Status.ACTIVE,
        "connected": False,
        "runner_id": str(runner.id),
        "runner_name": runner.name,
        "runner_version": runner.runner_version,
        "os_name": runner.os_name,
        "os_version": runner.os_version,
        "architecture": runner.architecture,
        "python_version": runner.python_version,
        "last_seen_at": runner.last_seen_at,
        "health_message": runner.health_message,
        "tools": runner.tools if isinstance(runner.tools, dict) else {},
    }

    if (
        binding.status != RunnerAgentBinding.Status.ACTIVE
        or runner.status != RunnerDevice.Status.ACTIVE
    ):
        return {**base, "status": RUNTIME_REVOKED, "paired": False}

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
