from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from workers.hosted_agent_connection import runtime_is_online
from workers.models import (
    HostedAgentConnection,
    WorkerAgent,
    WorkerJobAssignment,
    WorkerVerificationAssignment,
)


ACTIVE_VERIFICATION_STATUSES = {
    WorkerVerificationAssignment.Status.RESERVED,
    WorkerVerificationAssignment.Status.LEASED,
    WorkerVerificationAssignment.Status.RUNNING,
}


class VerificationMatchingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RankedVerifier:
    verifier_id: str
    score: int
    recent_reviews: int
    matched_skills: tuple[str, ...]
    reason: str


def _reservation_seconds() -> int:
    return max(
        30,
        int(getattr(settings, "VEYRA_VERIFIER_RESERVATION_SECONDS", 90)),
    )


def _same_owner(worker: WorkerAgent, verifier: WorkerAgent) -> bool:
    if worker.owner_user_id and verifier.owner_user_id:
        return worker.owner_user_id == verifier.owner_user_id
    return (
        worker.owner_type == WorkerAgent.OwnerType.VEYRA
        and verifier.owner_type == WorkerAgent.OwnerType.VEYRA
    )


def _runtime_connection(worker: WorkerAgent) -> HostedAgentConnection | None:
    try:
        connection = worker.hosted_connection
    except HostedAgentConnection.DoesNotExist:
        return None
    if not connection.provider_ready or not runtime_is_online(connection):
        return None
    return connection


def _active_reviews(verifier: WorkerAgent) -> int:
    return WorkerVerificationAssignment.objects.filter(
        verifier=verifier,
        status__in=ACTIVE_VERIFICATION_STATUSES,
    ).count()


def _skill_set(agent: WorkerAgent) -> set[str]:
    values = [
        *list(agent.skills or []),
        *list(agent.languages or []),
        *list(agent.frameworks or []),
        *list(agent.testing_tools or []),
        *list(agent.task_types or []),
    ]
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def rank_verifiers_for_assignment(
    assignment: WorkerJobAssignment,
    *,
    excluded_verifier_ids: set[str] | None = None,
) -> list[RankedVerifier]:
    assignment = WorkerJobAssignment.objects.select_related(
        "worker",
        "worker__hosted_connection",
        "queue_item",
    ).get(pk=assignment.pk)
    worker = assignment.worker
    excluded = {str(value) for value in (excluded_verifier_ids or set())}
    worker_connection = _runtime_connection(worker)
    required = {
        str(value).strip().casefold()
        for value in list(assignment.queue_item.required_skills or [])
        if str(value).strip()
    }
    since = timezone.now() - timedelta(days=7)
    recent = {
        str(row["verifier_id"]): int(row["count"])
        for row in WorkerVerificationAssignment.objects.filter(
            status__in=[
                WorkerVerificationAssignment.Status.APPROVED,
                WorkerVerificationAssignment.Status.REJECTED,
                WorkerVerificationAssignment.Status.INCONCLUSIVE,
            ],
            completed_at__gte=since,
        )
        .values("verifier_id")
        .annotate(count=Count("id"))
    }
    history: dict[str, dict[str, int]] = {}
    for row in (
        WorkerVerificationAssignment.objects.filter(
            status__in=[
                WorkerVerificationAssignment.Status.APPROVED,
                WorkerVerificationAssignment.Status.REJECTED,
                WorkerVerificationAssignment.Status.INCONCLUSIVE,
            ],
        )
        .values("verifier_id", "status")
        .annotate(count=Count("id"))
    ):
        key = str(row["verifier_id"])
        bucket = history.setdefault(key, {"total": 0, "approved": 0})
        count = int(row["count"])
        bucket["total"] += count
        if row["status"] == WorkerVerificationAssignment.Status.APPROVED:
            bucket["approved"] += count

    candidates: list[RankedVerifier] = []
    verifiers = WorkerAgent.objects.filter(
        agent_role=WorkerAgent.AgentRole.VERIFIER,
        status=WorkerAgent.Status.ACTIVE,
        test_assignment_passed=True,
        engine_connected=True,
    ).select_related("hosted_connection")
    for verifier in verifiers:
        if str(verifier.id) in excluded:
            continue
        if verifier.id == worker.id or _same_owner(worker, verifier):
            continue
        connection = _runtime_connection(verifier)
        if connection is None:
            continue
        if worker_connection and (
            connection.runtime_id == worker_connection.runtime_id
            or connection.public_key_fingerprint
            == worker_connection.public_key_fingerprint
        ):
            continue
        if _active_reviews(verifier) >= int(verifier.maximum_active_jobs):
            continue
        skills = _skill_set(verifier)
        matched = tuple(sorted(required & skills))
        if required and len(matched) != len(required):
            continue
        recent_reviews = recent.get(str(verifier.id), 0)
        skill_score = 3000
        quality = history.get(str(verifier.id), {"total": 0, "approved": 0})
        approval_score = (
            int(2000 * quality["approved"] / quality["total"])
            if quality["total"]
            else 1000
        )
        availability = 1000 if _active_reviews(verifier) == 0 else 300
        fairness = max(0, 100 - min(recent_reviews, 10) * 10)
        score = skill_score + approval_score + availability + fairness
        candidates.append(
            RankedVerifier(
                verifier_id=str(verifier.id),
                score=score,
                recent_reviews=recent_reviews,
                matched_skills=matched,
                reason=(
                    f"Independent verifier with {len(matched)}/{len(required)} matched "
                    "task skills, separate owner, separate runtime identity, and available capacity."
                ),
            )
        )

    candidates.sort(
        key=lambda value: (
            -value.score,
            value.recent_reviews,
            value.verifier_id,
        )
    )
    return candidates


def _history_verifier_ids(value: WorkerVerificationAssignment | None) -> set[str]:
    result: set[str] = set()
    if value is None:
        return result
    for item in list(value.selection_history or []):
        if isinstance(item, dict) and item.get("verifier_id"):
            result.add(str(item["verifier_id"]))
    if value.verifier_id:
        result.add(str(value.verifier_id))
    return result


def reserve_verifier_for_assignment(
    assignment: WorkerJobAssignment,
) -> WorkerVerificationAssignment | None:
    existing = WorkerVerificationAssignment.objects.filter(
        worker_assignment=assignment
    ).first()
    if existing and existing.status not in {
        WorkerVerificationAssignment.Status.EXPIRED,
        WorkerVerificationAssignment.Status.FAILED,
    }:
        return existing
    excluded = _history_verifier_ids(existing)
    if (
        existing is not None
        and existing.status == WorkerVerificationAssignment.Status.EXPIRED
        and existing.assignment_attempt < 2
    ):
        # A transient offline period may expire a lease. Give the same
        # independent verifier one fresh lease before moving to another agent.
        excluded.discard(str(existing.verifier_id))
    ranked = rank_verifiers_for_assignment(
        assignment,
        excluded_verifier_ids=excluded,
    )
    if not ranked:
        return existing

    for rank, candidate in enumerate(ranked, start=1):
        try:
            with transaction.atomic():
                locked_assignment = WorkerJobAssignment.objects.select_for_update().select_related(
                    "worker",
                    "queue_item",
                ).get(pk=assignment.pk)
                if locked_assignment.status not in {
                    WorkerJobAssignment.Status.SUBMITTED,
                    WorkerJobAssignment.Status.VERIFYING,
                }:
                    return None
                current = WorkerVerificationAssignment.objects.select_for_update().filter(
                    worker_assignment=locked_assignment
                ).first()
                if current and current.status not in {
                    WorkerVerificationAssignment.Status.EXPIRED,
                    WorkerVerificationAssignment.Status.FAILED,
                }:
                    return current
                # hosted_connection is a nullable reverse one-to-one relation,
                # so PostgreSQL renders it as an outer join. Lock only the
                # authoritative worker row; `FOR UPDATE` across that nullable
                # join is rejected by PostgreSQL.
                verifier = (
                    WorkerAgent.objects.select_for_update(of=("self",))
                    .select_related("hosted_connection")
                    .get(pk=candidate.verifier_id)
                )
                if (
                    verifier.agent_role != WorkerAgent.AgentRole.VERIFIER
                    or verifier.status != WorkerAgent.Status.ACTIVE
                    or not verifier.test_assignment_passed
                    or _same_owner(locked_assignment.worker, verifier)
                    or _active_reviews(verifier) >= int(verifier.maximum_active_jobs)
                ):
                    continue
                connection = _runtime_connection(verifier)
                worker_connection = _runtime_connection(locked_assignment.worker)
                if connection is None:
                    continue
                if worker_connection and (
                    connection.runtime_id == worker_connection.runtime_id
                    or connection.public_key_fingerprint
                    == worker_connection.public_key_fingerprint
                ):
                    continue
                now = timezone.now()
                if current is None:
                    value = WorkerVerificationAssignment.objects.create(
                        worker_assignment=locked_assignment,
                        verifier=verifier,
                        status=WorkerVerificationAssignment.Status.RESERVED,
                        matching_score=candidate.score,
                        candidate_count=len(ranked),
                        fairness_rank=rank,
                        selection_reason=candidate.reason,
                        reserved_at=now,
                        reserved_until=now
                        + timedelta(seconds=_reservation_seconds()),
                    )
                else:
                    history = list(current.selection_history or [])
                    history.append(
                        {
                            "verifier_id": str(current.verifier_id),
                            "status": current.status,
                            "failure_message": current.failure_message[:300],
                            "completed_at": (
                                current.completed_at.isoformat()
                                if current.completed_at
                                else None
                            ),
                        }
                    )
                    current.verifier = verifier
                    current.status = WorkerVerificationAssignment.Status.RESERVED
                    current.assignment_attempt += 1
                    current.matching_score = candidate.score
                    current.candidate_count = len(ranked)
                    current.fairness_rank = rank
                    current.selection_reason = candidate.reason
                    current.selection_history = history
                    current.reservation_token = __import__("uuid").uuid4()
                    current.reserved_at = now
                    current.reserved_until = now + timedelta(
                        seconds=_reservation_seconds()
                    )
                    current.lease_id = None
                    current.lease_expires_at = None
                    current.leased_at = None
                    current.started_at = None
                    current.completed_at = None
                    current.verdict = ""
                    current.report = {}
                    current.report_hash = ""
                    current.evidence_hash = ""
                    current.runtime_signature = ""
                    current.failure_message = ""
                    current.save()
                    value = current
                locked_assignment.status = WorkerJobAssignment.Status.VERIFYING
                locked_assignment.verification_status = "VERIFIER_RESERVED"
                locked_assignment.verification_started_at = (
                    locked_assignment.verification_started_at or now
                )
                locked_assignment.failure_stage = ""
                locked_assignment.failure_message = ""
                locked_assignment.save(
                    update_fields=[
                        "status",
                        "verification_status",
                        "verification_started_at",
                        "failure_stage",
                        "failure_message",
                        "updated_at",
                    ]
                )
                return value
        except IntegrityError:
            current = WorkerVerificationAssignment.objects.filter(
                worker_assignment=assignment
            ).first()
            if current:
                return current
    return None
