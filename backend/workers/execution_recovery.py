from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from workers.execution_control import log_event
from workers.models import WorkerJobAssignment, WorkerJobQueueItem


_RETRYABLE_RUNTIME_MARKERS = (
    "[winerror 2]",
    "file not found",
    "no such file or directory",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "too many requests",
    "rate limit",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "expecting value: line 1 column",
    "returned malformed json",
    "returned malformed or incomplete json",
    "could not read as json",
    "returned an empty response",
    "returned no changed files",
    "returned no valid changed files",
    "unknown funded path id",
    "instead of json",
)


def is_retryable_runtime_failure(assignment: WorkerJobAssignment) -> bool:
    if assignment.failure_stage not in {
        "runtime_execution",
        "runtime_infrastructure",
        "runtime_preflight",
    }:
        return False
    message = str(assignment.failure_message or "").casefold()
    return any(marker in message for marker in _RETRYABLE_RUNTIME_MARKERS)


def can_retry_existing_runtime_assignment(
    assignment: WorkerJobAssignment,
) -> bool:
    """Whether the existing claimed assignment can safely rerun execution.

    This is a read-only eligibility check for public status responses. The
    transactional retry function below repeats the checks while holding row
    locks and remains the authority when a retry is requested.
    """
    if assignment.status != WorkerJobAssignment.Status.FAILED:
        return False
    if not is_retryable_runtime_failure(assignment):
        return False

    max_attempts = max(
        1, int(getattr(settings, "VEYRA_JOB_MAX_RUNTIME_ATTEMPTS", 3))
    )
    if int(assignment.assignment_attempt or 0) >= max_attempts:
        return False

    item = assignment.queue_item
    if not item.claim_arc_transaction_hash or not item.claim_confirmed_at:
        return False
    if (
        int(assignment.job.claim_deadline or 0)
        and int(timezone.now().timestamp()) >= int(assignment.job.claim_deadline)
    ):
        return False
    if item.submission_circle_transaction_id or item.submission_arc_transaction_hash:
        return False
    if (
        item.execution_commit_sha
        or item.execution_pull_request_number
        or item.execution_pull_request_url
    ):
        return False
    return True


class RuntimeRetryRefused(RuntimeError):
    """The existing claimed assignment cannot safely be retried."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def retry_existing_runtime_assignment(
    assignment: WorkerJobAssignment,
    *,
    cycle_number: int = 0,
) -> tuple[WorkerJobAssignment, bool]:
    """Atomically requeue only the failed runtime step for one claimed job.

    Returns ``(assignment, changed)``. Repeated requests after a successful
    retry are idempotent: they return the already-CLAIMED assignment without
    incrementing attempts again. Funding, assignment identity, Arc claim
    metadata, and all submission/settlement fields are never changed.
    """
    now = timezone.now()
    max_attempts = max(
        1, int(getattr(settings, "VEYRA_JOB_MAX_RUNTIME_ATTEMPTS", 3))
    )
    with transaction.atomic():
        locked = (
            WorkerJobAssignment.objects.select_for_update()
            .select_related("queue_item", "job")
            .get(pk=assignment.pk)
        )
        item = WorkerJobQueueItem.objects.select_for_update().get(
            pk=locked.queue_item_id
        )

        if (
            locked.status == WorkerJobAssignment.Status.CLAIMED
            and item.status == WorkerJobQueueItem.Status.CLAIMED
            and not locked.failure_stage
            and not locked.failure_message
        ):
            return locked, False
        if locked.status != WorkerJobAssignment.Status.FAILED:
            raise RuntimeRetryRefused(
                "ASSIGNMENT_NOT_FAILED",
                f"This assignment is {locked.status}, so there is no failed execution step to retry.",
            )
        if not is_retryable_runtime_failure(locked):
            raise RuntimeRetryRefused(
                "FAILURE_NOT_RETRYABLE",
                "This failure is not a retryable runtime or AI-response failure.",
            )
        if int(locked.assignment_attempt or 0) >= max_attempts:
            raise RuntimeRetryRefused(
                "ATTEMPT_LIMIT_REACHED",
                f"This assignment has reached the retry limit of {max_attempts} attempts.",
            )
        if not item.claim_arc_transaction_hash or not item.claim_confirmed_at:
            raise RuntimeRetryRefused(
                "CLAIM_NOT_CONFIRMED",
                "The original Arc claim is not confirmed, so execution retry was refused.",
            )
        if (
            int(locked.job.claim_deadline or 0)
            and int(now.timestamp()) >= int(locked.job.claim_deadline)
        ):
            raise RuntimeRetryRefused(
                "CLAIM_DEADLINE_EXPIRED",
                "The original Arc claim deadline has expired, so execution retry was refused.",
            )
        if item.submission_circle_transaction_id or item.submission_arc_transaction_hash:
            raise RuntimeRetryRefused(
                "SUBMISSION_EXISTS",
                "A submission transaction already exists, so execution retry was refused.",
            )
        if (
            item.execution_commit_sha
            or item.execution_pull_request_number
            or item.execution_pull_request_url
        ):
            raise RuntimeRetryRefused(
                "GITHUB_EVIDENCE_EXISTS",
                "GitHub execution evidence already exists, so execution retry was refused.",
            )

        locked.status = WorkerJobAssignment.Status.CLAIMED
        locked.assignment_attempt = int(locked.assignment_attempt or 0) + 1
        locked.execution_lease_id = None
        locked.lease_expires_at = None
        locked.leased_at = None
        locked.runtime_last_seen_at = None
        locked.execution_started_at = None
        locked.execution_completed_at = None
        locked.evidence_hash = ""
        locked.runtime_signature = ""
        locked.execution_evidence = {}
        locked.failure_stage = ""
        locked.failure_message = ""
        locked.save(
            update_fields=[
                "status", "assignment_attempt", "execution_lease_id",
                "lease_expires_at", "leased_at", "runtime_last_seen_at",
                "execution_started_at", "execution_completed_at", "evidence_hash",
                "runtime_signature", "execution_evidence", "failure_stage",
                "failure_message", "updated_at",
            ]
        )

        item.status = WorkerJobQueueItem.Status.CLAIMED
        item.execution_attempt_count = int(item.execution_attempt_count or 0) + 1
        item.execution_branch_name = ""
        item.execution_workspace_name = ""
        item.execution_baseline_test_passed = None
        item.execution_post_test_passed = False
        item.execution_changed_files = []
        item.execution_commit_sha = ""
        item.execution_pull_request_number = None
        item.execution_pull_request_url = ""
        item.execution_engine_output = ""
        item.execution_baseline_test_output = ""
        item.execution_test_output = ""
        item.execution_failure_stage = ""
        item.execution_failure_message = ""
        item.execution_started_at = None
        item.execution_completed_at = None
        item.save(
            update_fields=[
                "status", "execution_attempt_count", "execution_branch_name",
                "execution_workspace_name", "execution_baseline_test_passed",
                "execution_post_test_passed", "execution_changed_files",
                "execution_commit_sha", "execution_pull_request_number",
                "execution_pull_request_url", "execution_engine_output",
                "execution_baseline_test_output", "execution_test_output",
                "execution_failure_stage", "execution_failure_message",
                "execution_started_at", "execution_completed_at", "updated_at",
            ]
        )
        log_event(
            "runtime_retry_scheduled",
            cycle=cycle_number,
            assignment_id=str(locked.id),
            onchain_job_id=locked.job.onchain_job_id,
            attempt=int(locked.assignment_attempt),
            max_attempts=max_attempts,
            claim_preserved=True,
        )
        return locked, True


def recover_retryable_runtime_failures(*, cycle_number: int = 0) -> int:
    """Safely requeue claimed work after a bounded infrastructure failure.

    The Arc claim is deliberately preserved. Recovery is refused after the
    claim deadline or once either GitHub or submission evidence exists.
    """
    recovered = 0
    candidates = WorkerJobAssignment.objects.select_related(
        "queue_item", "job"
    ).filter(status=WorkerJobAssignment.Status.FAILED)

    for candidate in candidates:
        if not is_retryable_runtime_failure(candidate):
            continue
        try:
            _, changed = retry_existing_runtime_assignment(
                candidate,
                cycle_number=cycle_number,
            )
        except RuntimeRetryRefused:
            continue
        recovered += int(changed)
    return recovered
