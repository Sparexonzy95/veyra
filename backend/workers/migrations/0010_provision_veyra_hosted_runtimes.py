import hashlib
import platform

from django.db import migrations
from django.utils import timezone


HOSTED_RUNTIME_MODE = "VEYRA_HOSTED"
HOSTED_RUNTIME_VERSION = "hosted-0.1.0"


def _device_address(worker_id):
    digest = hashlib.sha256(
        f"veyra-hosted-runtime:{worker_id}".encode("utf-8")
    ).hexdigest()
    return f"0x{digest[:40]}"


def provision_existing_agents(apps, schema_editor):
    WorkerAgent = apps.get_model("workers", "WorkerAgent")
    RunnerDevice = apps.get_model("workers", "RunnerDevice")
    RunnerAgentBinding = apps.get_model("workers", "RunnerAgentBinding")
    RunnerPairingCode = apps.get_model("workers", "RunnerPairingCode")

    now = timezone.now()
    python_version = platform.python_version()
    tools = {
        "runtime_mode": HOSTED_RUNTIME_MODE,
        "managed_by": "VEYRA",
        "workspace": "isolated",
        "python": python_version,
        "git": "managed",
        "node": "managed",
    }
    old_runner_ids = set()

    workers = WorkerAgent.objects.filter(
        owner_type="EXTERNAL",
        owner_user_id__isnull=False,
    )
    for worker in workers.iterator():
        runner, _ = RunnerDevice.objects.update_or_create(
            device_address=_device_address(worker.id),
            defaults={
                "owner_user_id": worker.owner_user_id,
                "name": "Veyra Hosted Runtime",
                "status": "ACTIVE",
                "runner_version": HOSTED_RUNTIME_VERSION,
                "os_name": "Veyra Cloud",
                "os_version": "Managed",
                "architecture": "Isolated container",
                "python_version": python_version,
                "health": "HEALTHY",
                "health_message": "",
                "tools": tools,
                "last_seen_at": now,
                "revoked_at": None,
            },
        )

        existing = RunnerAgentBinding.objects.filter(worker_id=worker.id).first()
        if existing and existing.runner_id != runner.id:
            old_runner_ids.add(existing.runner_id)

        RunnerAgentBinding.objects.update_or_create(
            worker_id=worker.id,
            defaults={
                "runner_id": runner.id,
                "status": "ACTIVE",
                "paired_at": now,
                "revoked_at": None,
            },
        )

        RunnerPairingCode.objects.filter(
            worker_id=worker.id,
            consumed_at__isnull=True,
            cancelled_at__isnull=True,
        ).update(cancelled_at=now)

        worker.engine_provider = "OPENCODE"
        worker.engine_model = worker.engine_model or "zai-org/glm-5.2"
        if worker.engine_model == "external-runner":
            worker.engine_model = "zai-org/glm-5.2"
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
        if worker.status in {"SETUP_REQUIRED", "PROFILE_READY"}:
            worker.status = "ENGINE_CONNECTED"
        worker.updated_at = now
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
                "updated_at",
            ]
        )

    for runner_id in old_runner_ids:
        if not RunnerAgentBinding.objects.filter(runner_id=runner_id).exists():
            RunnerDevice.objects.filter(id=runner_id).update(
                status="REVOKED",
                revoked_at=now,
                health="UNHEALTHY",
                health_message="Replaced by the Veyra-hosted runtime.",
            )


def reverse_noop(apps, schema_editor):
    # Runtime conversion is intentionally not reversed automatically because the
    # previous owner-hosted device binding cannot be reconstructed safely.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0009_runner_runtime_pairing"),
    ]

    operations = [
        migrations.RunPython(provision_existing_agents, reverse_noop),
    ]
