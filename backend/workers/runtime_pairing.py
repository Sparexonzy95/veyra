from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from workers.models import (
    RunnerAgentBinding,
    RunnerDevice,
    RunnerPairingCode,
    WorkerAgent,
)


PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIRING_PREFIX = "VYR"


class RuntimePairingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PairingResult:
    runner: RunnerDevice
    binding: RunnerAgentBinding
    worker: WorkerAgent


def normalise_pairing_code(raw: str) -> str:
    compact = "".join(ch for ch in (raw or "").upper() if ch.isalnum())
    return compact


def pairing_code_hash(raw: str) -> str:
    normalised = normalise_pairing_code(raw)
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, normalised.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_pairing_code() -> str:
    body = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
    return f"{PAIRING_PREFIX}-{body[:4]}-{body[4:]}"


@transaction.atomic
def create_pairing_code(*, worker: WorkerAgent, owner_user) -> tuple[str, RunnerPairingCode]:
    if worker.owner_user_id != owner_user.id:
        raise RuntimePairingError("This agent does not belong to the current owner.")
    if worker.owner_type != WorkerAgent.OwnerType.EXTERNAL:
        raise RuntimePairingError("Only externally owned agents can pair a Veyra Runner.")

    now = timezone.now()
    RunnerPairingCode.objects.select_for_update().filter(
        worker=worker,
        consumed_at__isnull=True,
        cancelled_at__isnull=True,
        expires_at__gt=now,
    ).update(cancelled_at=now)

    ttl_seconds = getattr(settings, "VEYRA_RUNNER_PAIRING_TTL_SECONDS", 600)
    for _ in range(8):
        raw = generate_pairing_code()
        digest = pairing_code_hash(raw)
        if not RunnerPairingCode.objects.filter(code_hash=digest).exists():
            record = RunnerPairingCode.objects.create(
                worker=worker,
                owner_user=owner_user,
                code_hash=digest,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            return raw, record
    raise RuntimePairingError("A unique pairing code could not be generated. Try again.")


def _safe_text(value, maximum: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:maximum]


def _safe_tools(value) -> dict:
    if not isinstance(value, dict):
        return {}
    allowed = {}
    for key in ("git", "node", "npm", "python", "pytest", "docker"):
        item = value.get(key)
        if item is not None:
            allowed[key] = _safe_text(item, 80)
    return allowed


@transaction.atomic
def consume_pairing_code(
    *,
    raw_code: str,
    device_address: str,
    runner_name: str,
    runner_version: str = "",
    environment: dict | None = None,
) -> PairingResult:
    digest = pairing_code_hash(raw_code)
    try:
        pairing = (
            RunnerPairingCode.objects.select_for_update()
            .select_related("worker", "owner_user")
            .get(code_hash=digest)
        )
    except RunnerPairingCode.DoesNotExist as exc:
        raise RuntimePairingError("Pairing code is invalid or has expired.") from exc

    now = timezone.now()
    if pairing.consumed_at is not None or pairing.cancelled_at is not None:
        raise RuntimePairingError("Pairing code has already been used or cancelled.")
    if pairing.expires_at <= now:
        raise RuntimePairingError("Pairing code has expired. Generate a new code in Veyra.")
    if pairing.worker.owner_user_id != pairing.owner_user_id:
        raise RuntimePairingError("Pairing ownership is invalid.")

    address = (device_address or "").strip().lower()
    if not address.startswith("0x") or len(address) != 42:
        raise RuntimePairingError("Runner device address is invalid.")
    try:
        int(address[2:], 16)
    except ValueError as exc:
        raise RuntimePairingError("Runner device address is invalid.") from exc

    environment = environment if isinstance(environment, dict) else {}
    runner = RunnerDevice.objects.select_for_update().filter(device_address=address).first()
    if runner is not None and runner.owner_user_id != pairing.owner_user_id:
        raise RuntimePairingError("This Runner device is already registered to another owner.")

    defaults = {
        "owner_user": pairing.owner_user,
        "name": _safe_text(runner_name, 120) or "Veyra Runner",
        "status": RunnerDevice.Status.ACTIVE,
        "runner_version": _safe_text(runner_version, 64),
        "os_name": _safe_text(environment.get("os_name"), 80),
        "os_version": _safe_text(environment.get("os_version"), 120),
        "architecture": _safe_text(environment.get("architecture"), 40),
        "python_version": _safe_text(environment.get("python_version"), 40),
        "tools": _safe_tools(environment.get("tools")),
        "revoked_at": None,
    }
    if runner is None:
        runner = RunnerDevice.objects.create(device_address=address, **defaults)
    else:
        for field, value in defaults.items():
            setattr(runner, field, value)
        runner.save()

    existing = RunnerAgentBinding.objects.select_for_update().filter(worker=pairing.worker).first()
    if existing is None:
        binding = RunnerAgentBinding.objects.create(
            worker=pairing.worker,
            runner=runner,
            status=RunnerAgentBinding.Status.ACTIVE,
            paired_at=now,
        )
    else:
        existing.runner = runner
        existing.status = RunnerAgentBinding.Status.ACTIVE
        existing.paired_at = now
        existing.revoked_at = None
        existing.save()
        binding = existing

    pairing.consumed_at = now
    pairing.save(update_fields=["consumed_at", "updated_at"])

    worker = pairing.worker
    worker.engine_connected = False
    worker.engine_provider = WorkerAgent.EngineProvider.CUSTOM
    worker.engine_model = "external-runner"
    worker.engine_version = defaults["runner_version"]
    worker.engine_last_error = "Waiting for the first signed Runner heartbeat."
    worker.engine_connection_metadata = {
        "runner_device_id": str(runner.id),
        "pairing_state": "PAIRED",
    }
    if worker.status == WorkerAgent.Status.ENGINE_CONNECTED:
        worker.status = WorkerAgent.Status.PROFILE_READY
    worker.save()

    return PairingResult(runner=runner, binding=binding, worker=worker)


@transaction.atomic
def record_runner_heartbeat(*, runner: RunnerDevice, payload: dict) -> list[WorkerAgent]:
    if runner.status != RunnerDevice.Status.ACTIVE:
        raise RuntimePairingError("Runner device has been revoked.")

    now = timezone.now()
    environment = payload.get("environment") if isinstance(payload, dict) else {}
    environment = environment if isinstance(environment, dict) else {}
    health_value = str(payload.get("health", "HEALTHY")).upper()
    health = (
        RunnerDevice.Health.HEALTHY
        if health_value == RunnerDevice.Health.HEALTHY
        else RunnerDevice.Health.UNHEALTHY
    )

    runner.runner_version = _safe_text(payload.get("runner_version"), 64) or runner.runner_version
    runner.os_name = _safe_text(environment.get("os_name"), 80) or runner.os_name
    runner.os_version = _safe_text(environment.get("os_version"), 120) or runner.os_version
    runner.architecture = _safe_text(environment.get("architecture"), 40) or runner.architecture
    runner.python_version = _safe_text(environment.get("python_version"), 40) or runner.python_version
    runner.tools = _safe_tools(environment.get("tools")) or runner.tools
    runner.health = health
    runner.health_message = _safe_text(payload.get("health_message"), 240)
    runner.last_seen_at = now
    runner.save()

    requested_ids = payload.get("agent_ids", [])
    requested_ids = {str(value) for value in requested_ids} if isinstance(requested_ids, list) else set()
    bindings = RunnerAgentBinding.objects.select_related("worker").filter(
        runner=runner,
        status=RunnerAgentBinding.Status.ACTIVE,
    )
    if requested_ids:
        bindings = bindings.filter(worker_id__in=requested_ids)

    workers = []
    for binding in bindings:
        worker = binding.worker
        worker.engine_connected = health == RunnerDevice.Health.HEALTHY
        worker.engine_version = runner.runner_version
        worker.engine_last_checked_at = now
        worker.engine_last_error = "" if worker.engine_connected else runner.health_message or "Runner reported an unhealthy state."
        worker.engine_connection_metadata = {
            "runner_device_id": str(runner.id),
            "pairing_state": "ONLINE" if worker.engine_connected else "UNHEALTHY",
            "os_name": runner.os_name,
            "architecture": runner.architecture,
            "tools": runner.tools,
        }
        if worker.engine_connected and worker.status == WorkerAgent.Status.PROFILE_READY:
            worker.status = WorkerAgent.Status.ENGINE_CONNECTED
        elif not worker.engine_connected and worker.status == WorkerAgent.Status.ENGINE_CONNECTED:
            worker.status = WorkerAgent.Status.PROFILE_READY
        worker.save()
        workers.append(worker)
    return workers


@transaction.atomic
def revoke_agent_runtime(*, worker: WorkerAgent, owner_user) -> None:
    if worker.owner_user_id != owner_user.id:
        raise RuntimePairingError("This agent does not belong to the current owner.")
    now = timezone.now()
    try:
        binding = RunnerAgentBinding.objects.select_for_update().get(worker=worker)
    except RunnerAgentBinding.DoesNotExist:
        binding = None
    if binding is not None:
        binding.status = RunnerAgentBinding.Status.REVOKED
        binding.revoked_at = now
        binding.save()

    RunnerPairingCode.objects.filter(
        worker=worker,
        consumed_at__isnull=True,
        cancelled_at__isnull=True,
    ).update(cancelled_at=now)

    worker.engine_connected = False
    worker.engine_last_checked_at = now
    worker.engine_last_error = "Runtime access was revoked by the agent owner."
    worker.engine_connection_metadata = {}
    worker.auto_claim_enabled = False
    worker.discovery_enabled = False
    if worker.status == WorkerAgent.Status.ACTIVE:
        worker.status = WorkerAgent.Status.PAUSED
    elif worker.status == WorkerAgent.Status.ENGINE_CONNECTED:
        worker.status = WorkerAgent.Status.PROFILE_READY
    worker.save()
