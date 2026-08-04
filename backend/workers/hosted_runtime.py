from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from workers.models import (
    RunnerAgentBinding,
    RunnerDevice,
    RunnerPairingCode,
    WorkerAgent,
)


HOSTED_RUNTIME_MODE = "VEYRA_HOSTED"
OWNER_HOSTED_RUNTIME_MODE = "OWNER_HOSTED"
HOSTED_RUNTIME_VERSION = "hosted-0.1.0"
HOSTED_RUNTIME_NAME = "Veyra Hosted Runtime"


class HostedRuntimeProvisioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class HostedRuntimeResult:
    worker: WorkerAgent
    runner: RunnerDevice
    binding: RunnerAgentBinding
    created: bool


def _hosted_device_address(worker_id) -> str:
    """Create a stable internal identity for one hosted runtime.

    RunnerDevice currently stores an EVM-shaped device identity because the
    owner-hosted Runner signs requests with an Ethereum-compatible keypair. A
    Veyra-hosted runtime does not use this value as a wallet and never receives
    funds. The deterministic value only satisfies the existing unique identity
    field while we keep one shared runtime model for both deployment modes.
    """

    digest = hashlib.sha256(f"veyra-hosted-runtime:{worker_id}".encode("utf-8")).hexdigest()
    return f"0x{digest[:40]}"


def _hosted_tools() -> dict[str, str]:
    return {
        "runtime_mode": HOSTED_RUNTIME_MODE,
        "managed_by": "VEYRA",
        "workspace": "isolated",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "git": "managed",
        "node": "managed",
    }


def is_hosted_runtime(worker: WorkerAgent) -> bool:
    try:
        binding = worker.runtime_binding
    except RunnerAgentBinding.DoesNotExist:
        return False

    tools = binding.runner.tools if isinstance(binding.runner.tools, dict) else {}
    return tools.get("runtime_mode") == HOSTED_RUNTIME_MODE


@transaction.atomic
def ensure_hosted_runtime(worker: WorkerAgent) -> HostedRuntimeResult:
    """Provision or repair the default Veyra-managed runtime for an agent.

    The hosted runtime is represented by the same control-plane records used by
    owner-hosted Runners, but it is managed by Veyra and therefore does not rely
    on owner pairing codes or laptop heartbeats.
    """

    if not worker.owner_user_id:
        raise HostedRuntimeProvisioningError(
            "A hosted runtime requires an agent with an owner user."
        )

    now = timezone.now()
    device_address = _hosted_device_address(worker.id)
    tools = _hosted_tools()

    runner, runner_created = RunnerDevice.objects.update_or_create(
        device_address=device_address,
        defaults={
            "owner_user_id": worker.owner_user_id,
            "name": HOSTED_RUNTIME_NAME,
            "status": RunnerDevice.Status.ACTIVE,
            "runner_version": HOSTED_RUNTIME_VERSION,
            "os_name": "Veyra Cloud",
            "os_version": "Managed",
            "architecture": "Isolated container",
            "python_version": tools["python"],
            "health": RunnerDevice.Health.HEALTHY,
            "health_message": "",
            "tools": tools,
            "last_seen_at": now,
            "revoked_at": None,
        },
    )

    binding, binding_created = RunnerAgentBinding.objects.update_or_create(
        worker=worker,
        defaults={
            "runner": runner,
            "status": RunnerAgentBinding.Status.ACTIVE,
            "paired_at": now,
            "revoked_at": None,
        },
    )

    RunnerPairingCode.objects.filter(
        worker=worker,
        consumed_at__isnull=True,
        cancelled_at__isnull=True,
    ).update(cancelled_at=now)

    worker.engine_provider = WorkerAgent.EngineProvider.OPENCODE
    worker.engine_model = settings.WORKER_ENGINE_MODEL.strip() or "zai-org/glm-5.2"
    worker.engine_connected = True
    worker.engine_version = HOSTED_RUNTIME_VERSION
    worker.engine_last_checked_at = now
    worker.engine_last_error = ""
    worker.engine_connection_metadata = {
        "runtime_mode": HOSTED_RUNTIME_MODE,
        "managed_by": "VEYRA",
        "runner_device_id": str(runner.id),
        "provisioning_state": "READY",
        "workspace": "isolated",
    }
    if worker.status in {
        WorkerAgent.Status.SETUP_REQUIRED,
        WorkerAgent.Status.PROFILE_READY,
    }:
        worker.status = WorkerAgent.Status.ENGINE_CONNECTED

    worker.save(
        update_fields=[
            "engine_provider",
            "engine_model",
            "engine_connected",
            "engine_version",
            "engine_last_checked_at",
            "engine_last_error",
            "engine_connection_metadata",
            "status",
            "discovery_enabled",
            "auto_claim_enabled",
            "updated_at",
        ]
    )

    return HostedRuntimeResult(
        worker=worker,
        runner=runner,
        binding=binding,
        created=runner_created or binding_created,
    )
