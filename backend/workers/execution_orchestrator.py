from __future__ import annotations

from dataclasses import asdict, dataclass

from django.db import transaction
from django.utils import timezone

from jobs.models import VeyraJob
from workers.claiming import (
    WorkerClaimError,
    WorkerClaimPendingError,
    execute_worker_job_claim,
    reconcile_worker_job_claim,
)
from workers.execution_matching import release_assignment, reserve_best_agent_for_job
from workers.execution_control import log_event
from workers.execution_recovery import recover_retryable_runtime_failures
from workers.execution_verification import (
    ExecutionVerificationError,
    ExecutionVerificationPending,
    sync_reputation_for_assignment,
    verify_and_settle_assignment,
)
from workers.verification_matching import reserve_verifier_for_assignment
from workers.models import (
    WorkerJobAssignment,
    WorkerJobQueueItem,
    WorkerVerificationAssignment,
)
from workers.submission import (
    WorkerSubmissionError,
    WorkerSubmissionPendingError,
    execute_worker_job_submission,
    reconcile_worker_job_submission,
)


@dataclass
class ExecutionCycleResult:
    matched: int = 0
    claimed: int = 0
    claim_pending: int = 0
    leased: int = 0
    results_received: int = 0
    submitted: int = 0
    submission_pending: int = 0
    verified: int = 0
    verifier_reserved: int = 0
    settled: int = 0
    released: int = 0
    failed: int = 0
    pending: int = 0
    reputation_synced: int = 0
    runtime_retried: int = 0

    def as_dict(self):
        return asdict(self)



_TRANSIENT_CLAIM_ERROR_MARKERS = (
    "429",
    "too many requests",
    "rate limit",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)


def _is_transient_claim_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return any(marker in message for marker in _TRANSIENT_CLAIM_ERROR_MARKERS)


def _set_assignment_status(assignment_id, status_value: str, **extra) -> WorkerJobAssignment:
    with transaction.atomic():
        assignment = WorkerJobAssignment.objects.select_for_update().get(pk=assignment_id)
        assignment.status = status_value
        fields = ["status", "updated_at"]
        for field, value in extra.items():
            setattr(assignment, field, value)
            fields.append(field)
        assignment.save(update_fields=fields)
        return assignment


def _match_open_jobs(result: ExecutionCycleResult, *, cycle_number: int) -> None:
    jobs = VeyraJob.objects.select_related("draft", "draft__funding_snapshot").filter(
        status="FUNDED",
        client_status="OPEN",
    ).order_by("expires_at", "created_at")
    for job in jobs:
        log_event(
            "job_considered",
            cycle=cycle_number,
            job_id=str(job.id),
            onchain_job_id=job.onchain_job_id,
            status=job.status,
            client_status=job.client_status,
        )
        assignment = WorkerJobAssignment.objects.filter(job=job).first()
        if assignment and assignment.status not in {
            WorkerJobAssignment.Status.RELEASED,
        }:
            log_event(
                "job_skipped",
                cycle=cycle_number,
                job_id=str(job.id),
                onchain_job_id=job.onchain_job_id,
                reason_code="EXISTING_ASSIGNMENT",
                assignment_status=assignment.status,
            )
            continue
        try:
            selected = reserve_best_agent_for_job(job)
        except Exception as exc:
            result.pending += 1
            log_event(
                "job_matching_retryable_error",
                cycle=cycle_number,
                job_id=str(job.id),
                onchain_job_id=job.onchain_job_id,
                error_type=exc.__class__.__name__,
                next_retry_seconds=5,
            )
            __import__("logging").getLogger("veyra.execution").exception(
                "job_matching_traceback"
            )
            continue
        if selected and selected.status == WorkerJobAssignment.Status.RESERVED:
            result.matched += 1
            log_event(
                "assignment_created",
                cycle=cycle_number,
                job_id=str(job.id),
                onchain_job_id=job.onchain_job_id,
                assignment_id=str(selected.id),
                worker_id=str(selected.worker_id),
                candidate_count=int(selected.candidate_count),
            )
        elif selected is None:
            log_event(
                "job_no_eligible_candidate",
                cycle=cycle_number,
                job_id=str(job.id),
                onchain_job_id=job.onchain_job_id,
                next_retry_seconds=5,
            )


def _release_expired_reservations(result: ExecutionCycleResult) -> None:
    now = timezone.now()
    for assignment in WorkerJobAssignment.objects.select_related("queue_item", "job").filter(
        status=WorkerJobAssignment.Status.RESERVED,
        reserved_until__lt=now,
    ):
        release_assignment(
            assignment,
            stage="reservation_expired",
            message="The selected agent did not begin the Arc claim before the reservation expired.",
            terminal=False,
        )
        result.released += 1


def _fail_expired_leases(result: ExecutionCycleResult) -> None:
    now = timezone.now()
    for assignment in WorkerJobAssignment.objects.select_related("queue_item").filter(
        status__in=[
            WorkerJobAssignment.Status.LEASED,
            WorkerJobAssignment.Status.EXECUTING,
        ],
        lease_expires_at__lt=now,
    ):
        with transaction.atomic():
            locked = WorkerJobAssignment.objects.select_for_update().select_related("queue_item").get(pk=assignment.pk)
            if locked.status not in {
                WorkerJobAssignment.Status.LEASED,
                WorkerJobAssignment.Status.EXECUTING,
            }:
                continue
            locked.status = WorkerJobAssignment.Status.FAILED
            locked.failure_stage = "runtime_lease_expired"
            locked.failure_message = (
                "The owner-hosted runtime did not submit work before its execution lease expired. "
                "The job remains claimed on Arc and follows the contract deadline/refund path."
            )
            locked.save(
                update_fields=["status", "failure_stage", "failure_message", "updated_at"]
            )
            item = locked.queue_item
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
        result.failed += 1


def _process_claims(result: ExecutionCycleResult) -> None:
    assignments = list(
        WorkerJobAssignment.objects.select_related("queue_item", "worker", "job").filter(
            status__in=[
                WorkerJobAssignment.Status.RESERVED,
                WorkerJobAssignment.Status.CLAIMING,
            ]
        ).order_by("reserved_at")
    )
    for assignment in assignments:
        try:
            if assignment.status == WorkerJobAssignment.Status.RESERVED:
                if assignment.reserved_until < timezone.now():
                    continue
                _set_assignment_status(
                    assignment.id,
                    WorkerJobAssignment.Status.CLAIMING,
                    failure_stage="",
                    failure_message="",
                )
                claim = execute_worker_job_claim(str(assignment.queue_item_id))
                log_event(
                    "claim_initiated",
                    assignment_id=str(assignment.id),
                    onchain_job_id=assignment.job.onchain_job_id,
                    worker_id=str(assignment.worker_id),
                )
            else:
                item = WorkerJobQueueItem.objects.get(pk=assignment.queue_item_id)
                if item.status == WorkerJobQueueItem.Status.CLAIMED:
                    claim = reconcile_worker_job_claim(str(item.id))
                elif item.status == WorkerJobQueueItem.Status.CLAIM_PENDING:
                    claim = reconcile_worker_job_claim(str(item.id))
                elif item.status == WorkerJobQueueItem.Status.QUEUED:
                    claim = execute_worker_job_claim(str(item.id))
                else:
                    raise WorkerClaimError(f"Unexpected claim queue status {item.status}.")
            if claim is not None:
                _set_assignment_status(
                    assignment.id,
                    WorkerJobAssignment.Status.CLAIMED,
                    failure_stage="",
                    failure_message="",
                )
                result.claimed += 1
                log_event(
                    "claim_confirmed",
                    assignment_id=str(assignment.id),
                    onchain_job_id=assignment.job.onchain_job_id,
                    worker_id=str(assignment.worker_id),
                )
        except WorkerClaimPendingError as exc:
            _set_assignment_status(
                assignment.id,
                WorkerJobAssignment.Status.CLAIMING,
                failure_stage="claim_pending",
                failure_message=str(exc)[:2000],
            )
            result.claim_pending += 1
            log_event(
                "claim_pending",
                assignment_id=str(assignment.id),
                onchain_job_id=assignment.job.onchain_job_id,
                error_type=exc.__class__.__name__,
            )
        except WorkerClaimError as exc:
            item = WorkerJobQueueItem.objects.get(pk=assignment.queue_item_id)
            transaction_unknown = bool(item.claim_circle_transaction_id or item.claim_arc_transaction_hash)
            transient_infrastructure = _is_transient_claim_error(exc)
            if transaction_unknown or transient_infrastructure:
                _set_assignment_status(
                    assignment.id,
                    WorkerJobAssignment.Status.CLAIMING,
                    failure_stage=(
                        "claim_reconciliation_required"
                        if transaction_unknown
                        else "claim_infrastructure"
                    ),
                    failure_message=str(exc)[:2000],
                )
                if transaction_unknown:
                    result.claim_pending += 1
                else:
                    result.pending += 1
            else:
                release_assignment(
                    assignment,
                    stage="claim_failed",
                    message=str(exc),
                    terminal=False,
                )
                result.released += 1
        except Exception as exc:
            _set_assignment_status(
                assignment.id,
                WorkerJobAssignment.Status.CLAIMING,
                failure_stage="claim_infrastructure",
                failure_message=str(exc)[:2000],
            )
            result.pending += 1
            log_event(
                "claim_retryable_error",
                assignment_id=str(assignment.id),
                onchain_job_id=assignment.job.onchain_job_id,
                error_type=exc.__class__.__name__,
            )
            __import__("logging").getLogger("veyra.execution").exception(
                "claim_traceback"
            )


def _process_submissions(result: ExecutionCycleResult) -> None:
    assignments = list(
        WorkerJobAssignment.objects.select_related("queue_item", "worker", "job").filter(
            status__in=[
                WorkerJobAssignment.Status.RESULT_RECEIVED,
                WorkerJobAssignment.Status.SUBMITTING,
            ]
        ).order_by("execution_completed_at", "updated_at")
    )
    for assignment in assignments:
        try:
            item = WorkerJobQueueItem.objects.get(pk=assignment.queue_item_id)
            if item.status == WorkerJobQueueItem.Status.SUBMITTED:
                submission = reconcile_worker_job_submission(str(item.id))
            elif item.status == WorkerJobQueueItem.Status.SUBMISSION_PENDING:
                if assignment.status == WorkerJobAssignment.Status.RESULT_RECEIVED:
                    _set_assignment_status(assignment.id, WorkerJobAssignment.Status.SUBMITTING)
                    submission = execute_worker_job_submission(str(item.id))
                else:
                    submission = reconcile_worker_job_submission(str(item.id))
            else:
                raise WorkerSubmissionError(f"Unexpected submission queue status {item.status}.")
            if submission is not None:
                _set_assignment_status(
                    assignment.id,
                    WorkerJobAssignment.Status.SUBMITTED,
                    failure_stage="",
                    failure_message="",
                )
                result.submitted += 1
        except WorkerSubmissionPendingError as exc:
            _set_assignment_status(
                assignment.id,
                WorkerJobAssignment.Status.SUBMITTING,
                failure_stage="submission_pending",
                failure_message=str(exc)[:2000],
            )
            result.submission_pending += 1
        except WorkerSubmissionError as exc:
            _set_assignment_status(
                assignment.id,
                WorkerJobAssignment.Status.FAILED,
                failure_stage="submission_failed",
                failure_message=str(exc)[:2000],
            )
            result.failed += 1
        except Exception as exc:
            _set_assignment_status(
                assignment.id,
                WorkerJobAssignment.Status.SUBMITTING,
                failure_stage="submission_infrastructure",
                failure_message=str(exc)[:2000],
            )
            result.pending += 1


def _expire_verifier_assignments(result: ExecutionCycleResult) -> None:
    now = timezone.now()
    values = WorkerVerificationAssignment.objects.filter(
        status__in=[
            WorkerVerificationAssignment.Status.RESERVED,
            WorkerVerificationAssignment.Status.LEASED,
            WorkerVerificationAssignment.Status.RUNNING,
        ]
    ).select_related("worker_assignment")
    for value in values:
        expired = (
            value.status == WorkerVerificationAssignment.Status.RESERVED
            and value.reserved_until < now
        ) or (
            value.status in {
                WorkerVerificationAssignment.Status.LEASED,
                WorkerVerificationAssignment.Status.RUNNING,
            }
            and value.lease_expires_at is not None
            and value.lease_expires_at < now
        )
        if not expired:
            continue
        with transaction.atomic():
            locked = WorkerVerificationAssignment.objects.select_for_update().get(
                pk=value.pk
            )
            if locked.status not in {
                WorkerVerificationAssignment.Status.RESERVED,
                WorkerVerificationAssignment.Status.LEASED,
                WorkerVerificationAssignment.Status.RUNNING,
            }:
                continue
            locked.status = WorkerVerificationAssignment.Status.EXPIRED
            locked.failure_message = (
                "The independent verifier did not submit a signed verdict before its reservation or lease expired."
            )
            locked.completed_at = now
            locked.save(
                update_fields=[
                    "status",
                    "failure_message",
                    "completed_at",
                    "updated_at",
                ]
            )
        result.pending += 1


def _process_verification(result: ExecutionCycleResult) -> None:
    assignments = list(
        WorkerJobAssignment.objects.select_related(
            "queue_item",
            "worker",
            "job__draft__funding_snapshot",
            "job__draft__github_repository_access__installation",
        ).filter(
            status__in=[
                WorkerJobAssignment.Status.SUBMITTED,
                WorkerJobAssignment.Status.VERIFYING,
                WorkerJobAssignment.Status.SETTLING,
            ]
        ).order_by("updated_at")
    )
    for assignment in assignments:
        previous = assignment.status
        try:
            if not assignment.verification_report_hash:
                verifier_value = reserve_verifier_for_assignment(assignment)
                if verifier_value is None:
                    raise ExecutionVerificationPending(
                        "No independent verifier agent is online and eligible yet."
                    )
                if verifier_value.status == verifier_value.Status.RESERVED:
                    result.verifier_reserved += 1
            outcome = verify_and_settle_assignment(assignment)
            if outcome.status == WorkerJobAssignment.Status.COMPLETED:
                result.settled += 1
            elif previous == WorkerJobAssignment.Status.SUBMITTED:
                result.verified += 1
        except ExecutionVerificationPending as exc:
            stage = (
                WorkerJobAssignment.Status.SETTLING
                if assignment.settlement_transaction_hash
                else WorkerJobAssignment.Status.VERIFYING
            )
            _set_assignment_status(
                assignment.id,
                stage,
                failure_stage="verification_pending",
                failure_message=str(exc)[:2000],
            )
            result.pending += 1
        except ExecutionVerificationError as exc:
            _set_assignment_status(
                assignment.id,
                WorkerJobAssignment.Status.FAILED,
                failure_stage="verification_failed",
                failure_message=str(exc)[:2000],
            )
            result.failed += 1
        except Exception as exc:
            _set_assignment_status(
                assignment.id,
                previous,
                failure_stage="verification_infrastructure",
                failure_message=str(exc)[:2000],
            )
            result.pending += 1


def _process_reputation_sync(result: ExecutionCycleResult) -> None:
    assignments = list(
        WorkerJobAssignment.objects.select_related("worker", "worker__reputation_snapshot").filter(
            status=WorkerJobAssignment.Status.COMPLETED,
        ).order_by("completed_at")
    )
    for assignment in assignments:
        try:
            snapshot = assignment.worker.reputation_snapshot
        except Exception:
            snapshot = None
        if (
            snapshot is not None
            and snapshot.synced_at is not None
            and assignment.completed_at is not None
            and snapshot.synced_at >= assignment.completed_at
        ):
            continue
        try:
            sync_reputation_for_assignment(assignment)
            result.reputation_synced += 1
        except ExecutionVerificationPending:
            result.pending += 1
        except Exception:
            result.pending += 1


def orchestrate_execution_once(*, cycle_number: int = 0) -> ExecutionCycleResult:
    result = ExecutionCycleResult()
    _release_expired_reservations(result)
    _fail_expired_leases(result)
    result.runtime_retried = recover_retryable_runtime_failures(
        cycle_number=cycle_number
    )
    _match_open_jobs(result, cycle_number=cycle_number)
    _process_claims(result)
    _process_submissions(result)
    _expire_verifier_assignments(result)
    _process_verification(result)
    _process_reputation_sync(result)
    result.leased = WorkerJobAssignment.objects.filter(
        status__in=[WorkerJobAssignment.Status.LEASED, WorkerJobAssignment.Status.EXECUTING]
    ).count()
    result.results_received = WorkerJobAssignment.objects.filter(
        status=WorkerJobAssignment.Status.RESULT_RECEIVED
    ).count()
    return result
