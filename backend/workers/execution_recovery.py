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
)


def _is_retryable_runtime_failure(assignment: WorkerJobAssignment) -> bool:
    if assignment.failure_stage not in {
        "runtime_execution",
        "runtime_infrastructure",
        "runtime_preflight",
    }:
        return False
    message = str(assignment.failure_message or "").casefold()
    return any(marker in message for marker in _RETRYABLE_RUNTIME_MARKERS)


def recover_retryable_runtime_failures(*, cycle_number: int = 0) -> int:
    """Safely requeue claimed work after a bounded infrastructure failure.

    The Arc claim is deliberately preserved. Recovery is refused after the
    claim deadline or once either GitHub or submission evidence exists.
    """
    now = timezone.now()
    max_attempts = max(
        1, int(getattr(settings, "VEYRA_JOB_MAX_RUNTIME_ATTEMPTS", 3))
    )
    recovered = 0
    candidates = WorkerJobAssignment.objects.select_related(
        "queue_item", "job"
    ).filter(status=WorkerJobAssignment.Status.FAILED)

    for candidate in candidates:
        if not _is_retryable_runtime_failure(candidate):
            continue
        with transaction.atomic():
            assignment = (
                WorkerJobAssignment.objects.select_for_update()
                .select_related("queue_item", "job")
                .get(pk=candidate.pk)
            )
            item = WorkerJobQueueItem.objects.select_for_update().get(
                pk=assignment.queue_item_id
            )
            if (
                assignment.status != WorkerJobAssignment.Status.FAILED
                or not _is_retryable_runtime_failure(assignment)
                or int(assignment.assignment_attempt or 0) >= max_attempts
                or not item.claim_arc_transaction_hash
                or not item.claim_confirmed_at
                or (
                    int(assignment.job.claim_deadline or 0)
                    and int(now.timestamp()) >= int(assignment.job.claim_deadline)
                )
                or item.submission_circle_transaction_id
                or item.submission_arc_transaction_hash
                or item.execution_commit_sha
                or item.execution_pull_request_number
                or item.execution_pull_request_url
            ):
                continue

            assignment.status = WorkerJobAssignment.Status.CLAIMED
            assignment.assignment_attempt = int(assignment.assignment_attempt or 0) + 1
            assignment.execution_lease_id = None
            assignment.lease_expires_at = None
            assignment.leased_at = None
            assignment.runtime_last_seen_at = None
            assignment.execution_started_at = None
            assignment.execution_completed_at = None
            assignment.evidence_hash = ""
            assignment.runtime_signature = ""
            assignment.execution_evidence = {}
            assignment.failure_stage = ""
            assignment.failure_message = ""
            assignment.save(
                update_fields=[
                    "status",
                    "assignment_attempt",
                    "execution_lease_id",
                    "lease_expires_at",
                    "leased_at",
                    "runtime_last_seen_at",
                    "execution_started_at",
                    "execution_completed_at",
                    "evidence_hash",
                    "runtime_signature",
                    "execution_evidence",
                    "failure_stage",
                    "failure_message",
                    "updated_at",
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
                    "status",
                    "execution_attempt_count",
                    "execution_branch_name",
                    "execution_workspace_name",
                    "execution_baseline_test_passed",
                    "execution_post_test_passed",
                    "execution_changed_files",
                    "execution_commit_sha",
                    "execution_pull_request_number",
                    "execution_pull_request_url",
                    "execution_engine_output",
                    "execution_baseline_test_output",
                    "execution_test_output",
                    "execution_failure_stage",
                    "execution_failure_message",
                    "execution_started_at",
                    "execution_completed_at",
                    "updated_at",
                ]
            )
            recovered += 1
            log_event(
                "runtime_retry_scheduled",
                cycle=cycle_number,
                assignment_id=str(assignment.id),
                onchain_job_id=assignment.job.onchain_job_id,
                attempt=int(assignment.assignment_attempt),
                max_attempts=max_attempts,
                claim_preserved=True,
            )
    return recovered
