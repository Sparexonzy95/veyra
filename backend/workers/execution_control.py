from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from workers.models import ExecutionLayerState


logger = logging.getLogger("veyra.execution")
CONTROLLER_KEY = "default"
LEASE_SECONDS = 120


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, "at": timezone.now().isoformat(), **fields}
    logger.info(json.dumps(payload, sort_keys=True, default=str))


def claim_controller() -> uuid.UUID:
    now = timezone.now()
    instance_id = uuid.uuid4()
    with transaction.atomic():
        state, _ = ExecutionLayerState.objects.select_for_update().get_or_create(
            key=CONTROLLER_KEY
        )
        if (
            state.running
            and state.lease_expires_at is not None
            and state.lease_expires_at > now
        ):
            raise RuntimeError(
                "Another execution-layer controller holds the active database lease."
            )
        state.instance_id = instance_id
        state.process_id = os.getpid()
        state.running = True
        state.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        state.last_error_code = ""
        state.last_error_message = ""
        state.save()
    log_event(
        "controller_started",
        instance_id=str(instance_id),
        process_id=os.getpid(),
    )
    return instance_id


def start_cycle(instance_id: uuid.UUID) -> int:
    now = timezone.now()
    with transaction.atomic():
        state = ExecutionLayerState.objects.select_for_update().get(key=CONTROLLER_KEY)
        if state.instance_id != instance_id:
            raise RuntimeError("The execution-layer database lease was replaced.")
        state.cycle_number += 1
        state.running = True
        state.last_cycle_started_at = now
        state.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        state.save(
            update_fields=[
                "cycle_number",
                "running",
                "last_cycle_started_at",
                "lease_expires_at",
                "updated_at",
            ]
        )
        return int(state.cycle_number)


def finish_cycle(
    instance_id: uuid.UUID,
    *,
    delay_seconds: int,
    result: dict[str, Any] | None = None,
    error: Exception | None = None,
    consecutive_failures: int = 0,
) -> None:
    now = timezone.now()
    with transaction.atomic():
        state = ExecutionLayerState.objects.select_for_update().get(key=CONTROLLER_KEY)
        if state.instance_id != instance_id:
            return
        state.running = True
        state.last_cycle_finished_at = now
        state.next_cycle_at = now + timedelta(seconds=max(1, delay_seconds))
        state.lease_expires_at = state.next_cycle_at + timedelta(
            seconds=LEASE_SECONDS
        )
        state.consecutive_failures = consecutive_failures
        state.last_result = result or {}
        state.last_error_code = error.__class__.__name__[:80] if error else ""
        state.last_error_message = (
            "The automatic execution cycle hit a retryable internal error."
            if error
            else ""
        )
        state.save()


def release_controller(instance_id: uuid.UUID) -> None:
    with transaction.atomic():
        state = ExecutionLayerState.objects.select_for_update().filter(
            key=CONTROLLER_KEY
        ).first()
        if state is None or state.instance_id != instance_id:
            return
        state.running = False
        state.lease_expires_at = timezone.now()
        state.save(
            update_fields=["running", "lease_expires_at", "updated_at"]
        )
    log_event("controller_stopped", instance_id=str(instance_id))


def controller_public_snapshot() -> dict[str, Any]:
    state = ExecutionLayerState.objects.filter(key=CONTROLLER_KEY).first()
    now = timezone.now()
    online = bool(
        state
        and state.running
        and state.lease_expires_at
        and state.lease_expires_at > now
        and state.last_cycle_started_at
        and now - state.last_cycle_started_at <= timedelta(seconds=LEASE_SECONDS)
    )
    return {
        "online": online,
        "last_cycle_started_at": (
            state.last_cycle_started_at.isoformat()
            if state and state.last_cycle_started_at
            else None
        ),
        "last_cycle_finished_at": (
            state.last_cycle_finished_at.isoformat()
            if state and state.last_cycle_finished_at
            else None
        ),
        "next_cycle_at": (
            state.next_cycle_at.isoformat()
            if state and state.next_cycle_at
            else None
        ),
        "consecutive_failures": int(state.consecutive_failures) if state else 0,
        "last_error_code": state.last_error_code if state else "",
        "last_error_message": state.last_error_message if state else "",
    }
