from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from jobs.models import VeyraJob
from workers.discovery import discover_job
from workers.hosted_agent_connection import runtime_is_online
from workers.models import (
    HostedAgentConnection,
    WorkerAgent,
    WorkerJobAssignment,
    WorkerJobQueueItem,
)


ACTIVE_ASSIGNMENT_STATUSES = {
    WorkerJobAssignment.Status.RESERVED,
    WorkerJobAssignment.Status.CLAIMING,
    WorkerJobAssignment.Status.CLAIMED,
    WorkerJobAssignment.Status.LEASED,
    WorkerJobAssignment.Status.EXECUTING,
    WorkerJobAssignment.Status.RESULT_RECEIVED,
    WorkerJobAssignment.Status.SUBMITTING,
    WorkerJobAssignment.Status.SUBMITTED,
    WorkerJobAssignment.Status.VERIFYING,
    WorkerJobAssignment.Status.SETTLING,
}


class ExecutionMatchingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RankedCandidate:
    worker_id: str
    queue_item_id: str
    score: int
    recent_jobs: int
    last_assignment_at: object | None
    reason: str


@dataclass(frozen=True)
class AssignmentSelection:
    assignment_id: str
    job_id: int
    worker_id: str
    worker_slug: str
    queue_item_id: str
    score: int
    candidate_count: int
    status: str


def _reservation_seconds() -> int:
    return max(30, int(getattr(settings, "VEYRA_JOB_RESERVATION_SECONDS", 90)))


def _active_capacity(worker: WorkerAgent) -> int:
    return WorkerJobAssignment.objects.filter(
        worker=worker,
        status__in=ACTIVE_ASSIGNMENT_STATUSES,
    ).count()


def _runtime_online(worker: WorkerAgent) -> bool:
    try:
        connection = worker.hosted_connection
    except HostedAgentConnection.DoesNotExist:
        return False
    return bool(connection.provider_ready and runtime_is_online(connection))


def _candidate_score(worker: WorkerAgent, queue_item: WorkerJobQueueItem, recent_jobs: int) -> int:
    try:
        reputation = worker.reputation_snapshot
    except Exception:
        reputation = None
    completed = int(getattr(reputation, "completed_jobs", 0) or 0)
    failed = int(getattr(reputation, "failed_jobs", 0) or 0)
    reliability = int(1000 * completed / max(1, completed + failed)) if completed else 500
    karma = min(int(getattr(reputation, "karma_score", 0) or 0), 2000)
    availability = 1000 if _active_capacity(worker) == 0 else 300
    fairness = max(0, 1000 - min(recent_jobs, 10) * 100)
    return int(queue_item.priority_score) + reliability + karma + availability + fairness


def rank_candidates_for_job(job: VeyraJob, *, excluded_worker_ids: Iterable[str] = ()) -> list[RankedCandidate]:
    excluded = {str(value) for value in excluded_worker_ids}
    workers = list(
        WorkerAgent.objects.filter(
            agent_role=WorkerAgent.AgentRole.WORKER,
            status=WorkerAgent.Status.ACTIVE,
            test_assignment_passed=True,
            contract_authorised=True,
            auto_claim_enabled=True,
            discovery_enabled=True,
        ).select_related("hosted_connection", "reputation_snapshot")
    )
    since = timezone.now() - timedelta(days=7)
    recent = {
        str(row["worker_id"]): int(row["count"])
        for row in WorkerJobAssignment.objects.filter(
            status=WorkerJobAssignment.Status.COMPLETED,
            completed_at__gte=since,
        )
        .values("worker_id")
        .annotate(count=Count("id"))
    }
    last = {
        str(row["worker_id"]): row["last_at"]
        for row in WorkerJobAssignment.objects.values("worker_id").annotate(
            last_at=Max("created_at")
        )
    }

    candidates: list[RankedCandidate] = []
    for worker in workers:
        if str(worker.id) in excluded:
            continue
        if not _runtime_online(worker):
            continue
        if _active_capacity(worker) >= int(worker.maximum_active_jobs):
            continue
        try:
            result = discover_job(
                worker,
                job,
                source=WorkerJobQueueItem.Source.FAST_PATH,
            )
        except Exception:
            continue
        if result.status != WorkerJobQueueItem.Status.QUEUED:
            continue
        item = WorkerJobQueueItem.objects.get(pk=result.queue_item_id)
        recent_jobs = recent.get(str(worker.id), 0)
        score = _candidate_score(worker, item, recent_jobs)
        candidates.append(
            RankedCandidate(
                worker_id=str(worker.id),
                queue_item_id=str(item.id),
                score=score,
                recent_jobs=recent_jobs,
                last_assignment_at=last.get(str(worker.id)),
                reason=(
                    f"Eligible with {len(item.matched_skills)}/{len(item.required_skills) or 0} "
                    f"required skills, live runtime, available capacity, and policy match."
                ),
            )
        )

    if not candidates:
        return []
    best_score = max(candidate.score for candidate in candidates)
    fairness_band = max(0, int(getattr(settings, "VEYRA_MATCHING_FAIRNESS_BAND", 200)))
    top_band = [candidate for candidate in candidates if best_score - candidate.score <= fairness_band]
    top_band.sort(
        key=lambda candidate: (
            candidate.recent_jobs,
            candidate.last_assignment_at or (timezone.now() - timedelta(days=36500)),
            -candidate.score,
            candidate.worker_id,
        )
    )
    selected = top_band[0]
    others = sorted(
        (candidate for candidate in candidates if candidate.worker_id != selected.worker_id),
        key=lambda candidate: (-candidate.score, candidate.recent_jobs, candidate.worker_id),
    )
    return [selected, *others]


def _history_worker_ids(assignment: WorkerJobAssignment | None) -> list[str]:
    if assignment is None or not isinstance(assignment.selection_history, list):
        return []
    values = []
    for item in assignment.selection_history:
        if isinstance(item, dict) and item.get("worker_id"):
            values.append(str(item["worker_id"]))
    if assignment and assignment.worker_id:
        values.append(str(assignment.worker_id))
    return values


def reserve_best_agent_for_job(job: VeyraJob) -> WorkerJobAssignment | None:
    job = VeyraJob.objects.select_related("draft", "draft__funding_snapshot").get(pk=job.pk)
    if job.status != "FUNDED" or job.client_status != "OPEN":
        return None

    existing = WorkerJobAssignment.objects.filter(job=job).first()
    if existing and existing.status in ACTIVE_ASSIGNMENT_STATUSES | {WorkerJobAssignment.Status.COMPLETED}:
        return existing

    excluded = _history_worker_ids(existing)
    ranked = rank_candidates_for_job(job, excluded_worker_ids=excluded)
    if not ranked:
        return None

    for rank, candidate in enumerate(ranked, start=1):
        try:
            with transaction.atomic():
                locked_job = VeyraJob.objects.select_for_update().get(pk=job.pk)
                if locked_job.status != "FUNDED" or locked_job.client_status != "OPEN":
                    return None
                locked_worker = WorkerAgent.objects.select_for_update().get(pk=candidate.worker_id)
                if (
                    locked_worker.agent_role != WorkerAgent.AgentRole.WORKER
                    or locked_worker.status != WorkerAgent.Status.ACTIVE
                    or not locked_worker.auto_claim_enabled
                    or _active_capacity(locked_worker) >= int(locked_worker.maximum_active_jobs)
                ):
                    continue
                queue_item = WorkerJobQueueItem.objects.select_for_update().get(
                    pk=candidate.queue_item_id,
                    worker=locked_worker,
                    job=locked_job,
                    status=WorkerJobQueueItem.Status.QUEUED,
                    eligibility_passed=True,
                )
                now = timezone.now()
                defaults = {
                    "worker": locked_worker,
                    "queue_item": queue_item,
                    "status": WorkerJobAssignment.Status.RESERVED,
                    "candidate_count": len(ranked),
                    "matching_score": candidate.score,
                    "fairness_rank": rank,
                    "selection_reason": candidate.reason,
                    "reserved_at": now,
                    "reserved_until": now + timedelta(seconds=_reservation_seconds()),
                    "failure_stage": "",
                    "failure_message": "",
                    "released_at": None,
                }
                if existing is None:
                    assignment = WorkerJobAssignment.objects.create(job=locked_job, **defaults)
                else:
                    assignment = WorkerJobAssignment.objects.select_for_update().get(pk=existing.pk)
                    history = list(assignment.selection_history or [])
                    history.append(
                        {
                            "worker_id": str(assignment.worker_id),
                            "queue_item_id": str(assignment.queue_item_id),
                            "status": assignment.status,
                            "failure_stage": assignment.failure_stage,
                            "failure_message": assignment.failure_message[:300],
                            "released_at": now.isoformat(),
                        }
                    )
                    for field, value in defaults.items():
                        setattr(assignment, field, value)
                    assignment.assignment_attempt += 1
                    assignment.reservation_token = __import__("uuid").uuid4()
                    assignment.execution_lease_id = None
                    assignment.lease_expires_at = None
                    assignment.leased_at = None
                    assignment.execution_evidence = {}
                    assignment.evidence_hash = ""
                    assignment.runtime_signature = ""
                    assignment.selection_history = history
                    assignment.save()
                return assignment
        except (IntegrityError, WorkerJobQueueItem.DoesNotExist):
            current = WorkerJobAssignment.objects.filter(job=job).first()
            if current and current.status in ACTIVE_ASSIGNMENT_STATUSES:
                return current
            continue
    return None


def release_assignment(
    assignment: WorkerJobAssignment,
    *,
    stage: str,
    message: str,
    terminal: bool = False,
) -> WorkerJobAssignment:
    with transaction.atomic():
        locked = WorkerJobAssignment.objects.select_for_update().select_related("queue_item").get(pk=assignment.pk)
        locked.status = WorkerJobAssignment.Status.FAILED if terminal else WorkerJobAssignment.Status.RELEASED
        locked.failure_stage = str(stage or "execution")[:80]
        locked.failure_message = str(message or "")[:2000]
        locked.released_at = timezone.now()
        locked.save(
            update_fields=[
                "status",
                "failure_stage",
                "failure_message",
                "released_at",
                "updated_at",
            ]
        )
        item = locked.queue_item
        if item.status not in {WorkerJobQueueItem.Status.COMPLETED, WorkerJobQueueItem.Status.SUBMITTED}:
            item.status = WorkerJobQueueItem.Status.FAILED
            item.execution_failure_stage = locked.failure_stage
            item.execution_failure_message = locked.failure_message
            item.save(
                update_fields=[
                    "status",
                    "execution_failure_stage",
                    "execution_failure_message",
                    "updated_at",
                ]
            )
        return locked
