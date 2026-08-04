from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from workers.hosted_runtime import HOSTED_RUNTIME_MODE, OWNER_HOSTED_RUNTIME_MODE
from workers.models import (
    HostedAgentConnection,
    RunnerAgentBinding,
    RunnerDevice,
    WorkerAgent,
)


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
        "runtime_mode": OWNER_HOSTED_RUNTIME_MODE,
        "managed_by": "OWNER",
        "auto_start": False,
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
        "provider": "",
        "model": "",
        "provider_ready": False,
        "protocol_version": None,
        "public_key_fingerprint": "",
        "connection_method": "COPY_LINK_V1",
    }


def _hosted_connection_snapshot(worker: WorkerAgent) -> dict | None:
    try:
        connection = worker.hosted_connection
    except HostedAgentConnection.DoesNotExist:
        return None

    base = {
        "paired": connection.status != HostedAgentConnection.Status.REVOKED,
        "connected": False,
        "runtime_mode": OWNER_HOSTED_RUNTIME_MODE,
        "managed_by": "OWNER",
        "auto_start": False,
        "runner_id": str(connection.id),
        "runner_name": connection.runtime_id,
        "runner_version": connection.runtime_version,
        "os_name": "",
        "os_version": "",
        "architecture": "",
        "python_version": "",
        "last_seen_at": connection.last_seen_at,
        "provisioned_at": connection.connected_at,
        "health_message": connection.last_error,
        "tools": connection.capabilities if isinstance(connection.capabilities, dict) else {},
        "provider": connection.provider,
        "model": connection.model_name,
        "provider_ready": connection.provider_ready,
        "protocol_version": connection.protocol_version,
        "public_key_fingerprint": connection.public_key_fingerprint,
        "connection_method": "COPY_LINK_V1",
    }

    if connection.status == HostedAgentConnection.Status.REVOKED:
        return {**base, "status": RUNTIME_REVOKED, "paired": False}
    if connection.status == HostedAgentConnection.Status.UNHEALTHY:
        return {**base, "status": RUNTIME_UNHEALTHY}
    if connection.last_seen_at is None:
        return {**base, "status": RUNTIME_PAIRED}

    online_window = timedelta(
        seconds=int(getattr(settings, "VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS", 35))
    )
    if timezone.now() - connection.last_seen_at > online_window:
        return {**base, "status": RUNTIME_OFFLINE}
    if not connection.provider_ready:
        return {**base, "status": RUNTIME_UNHEALTHY}
    return {**base, "status": RUNTIME_ONLINE, "connected": True}


def runtime_snapshot(worker: WorkerAgent) -> dict:
    """Return owner-safe runtime state, preferring the modern copy-link runtime."""

    modern = _hosted_connection_snapshot(worker)
    if modern is not None:
        return modern

    # Legacy runner bindings remain readable during migration, but new agents
    # are created through HostedAgentConnection.
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
        "provider": str(tools.get("provider") or ""),
        "model": str(tools.get("model") or ""),
        "provider_ready": runner.health == RunnerDevice.Health.HEALTHY,
        "protocol_version": tools.get("protocol_version"),
        "public_key_fingerprint": "",
        "connection_method": "LEGACY_PAIRING",
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
