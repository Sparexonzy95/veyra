from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.utils import timezone

from blockchain.client import redact_rpc_text
from workers.models import (
    WorkerAgent,
    WorkerJobAssignment,
    WorkerJobQueueItem,
    WorkerVerificationAssignment,
)
from workers.execution_control import controller_public_snapshot
from workers.runtime_status import runtime_snapshot


ACTIVE_STATUSES = {
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

STAGE_LABELS = {
    WorkerJobAssignment.Status.RESERVED: "Agent selected",
    WorkerJobAssignment.Status.CLAIMING: "Claiming on Arc",
    WorkerJobAssignment.Status.CLAIMED: "Claim confirmed",
    WorkerJobAssignment.Status.LEASED: "Delivered to runtime",
    WorkerJobAssignment.Status.EXECUTING: "Agent working",
    WorkerJobAssignment.Status.RESULT_RECEIVED: "Result received",
    WorkerJobAssignment.Status.SUBMITTING: "Submitting on Arc",
    WorkerJobAssignment.Status.SUBMITTED: "Submitted for verification",
    WorkerJobAssignment.Status.VERIFYING: "Independent verification",
    WorkerJobAssignment.Status.SETTLING: "USDC settlement",
    WorkerJobAssignment.Status.COMPLETED: "Completed",
    WorkerJobAssignment.Status.RELEASED: "Released for reassignment",
    WorkerJobAssignment.Status.FAILED: "Needs attention",
}


def _iso(value):
    return value.isoformat() if value else None


def assignment_public_snapshot(assignment: WorkerJobAssignment | None) -> dict[str, Any] | None:
    if assignment is None:
        return None
    item = assignment.queue_item
    job = assignment.job
    worker = assignment.worker
    title = (job.draft.advanced_options or {}).get("job_title") or job.draft.issue_title
    try:
        verifier_value = assignment.verifier_assignment
    except WorkerVerificationAssignment.DoesNotExist:
        verifier_value = None
    runtime_value = runtime_snapshot(worker)
    runtime_public = {
        "status": runtime_value.get("status"),
        "connected": bool(runtime_value.get("connected")),
        "provider_ready": bool(runtime_value.get("provider_ready")),
        "last_seen_at": _iso(runtime_value.get("last_seen_at")),
        "health_message": str(runtime_value.get("health_message") or ""),
    }
    attention_code = ""
    attention_message = ""
    if assignment.status in {
        WorkerJobAssignment.Status.CLAIMED,
        WorkerJobAssignment.Status.LEASED,
        WorkerJobAssignment.Status.EXECUTING,
    } and not runtime_public["connected"]:
        attention_code = "RUNTIME_OFFLINE"
        attention_message = (
            "The selected agent runtime is offline, so Veyra cannot deliver or continue this job. "
            "Reconnect the same runtime; do not create or claim another job."
        )
    elif (
        assignment.status == WorkerJobAssignment.Status.CLAIMED
        and runtime_public["connected"]
        and timezone.now() - assignment.updated_at > timedelta(seconds=45)
    ):
        attention_code = "JOB_DELIVERY_STALLED"
        attention_message = (
            "The Arc claim is confirmed and the runtime is online, but no execution lease was created. "
            "Check the runtime heartbeat delivery error."
        )

    verifier = None
    if verifier_value is not None:
        verifier = {
            "id": str(verifier_value.id),
            "status": verifier_value.status,
            "verdict": verifier_value.verdict,
            "assignment_attempt": int(verifier_value.assignment_attempt),
            "candidate_count": int(verifier_value.candidate_count),
            "matching_score": int(verifier_value.matching_score),
            "fairness_rank": int(verifier_value.fairness_rank),
            "selection_reason": verifier_value.selection_reason,
            "agent": {
                "id": str(verifier_value.verifier_id),
                "name": verifier_value.verifier.name,
                "slug": verifier_value.verifier.slug,
            },
            "leased_at": _iso(verifier_value.leased_at),
            "lease_expires_at": _iso(verifier_value.lease_expires_at),
            "started_at": _iso(verifier_value.started_at),
            "completed_at": _iso(verifier_value.completed_at),
            "report_hash": verifier_value.report_hash,
            "evidence_hash": verifier_value.evidence_hash,
            "summary": str((verifier_value.report or {}).get("summary") or ""),
            "failure_message": verifier_value.failure_message,
        }
    failure_history = [
        {
            **entry,
            "message": redact_rpc_text(str(entry.get("message") or "")),
        }
        for entry in list(assignment.failure_history or [])
        if isinstance(entry, dict)
    ]
    active_failure_stage = assignment.failure_stage
    active_failure_message = assignment.failure_message
    if assignment.status == WorkerJobAssignment.Status.COMPLETED:
        if active_failure_stage or active_failure_message:
            failure_history.append(
                {
                    "source": "assignment",
                    "stage": active_failure_stage,
                    "message": redact_rpc_text(active_failure_message),
                    "recovered_at": _iso(
                        assignment.completed_at or assignment.updated_at
                    ),
                }
            )
        active_failure_stage = ""
        active_failure_message = ""
    return {
        "id": str(assignment.id),
        "job_id": int(job.onchain_job_id),
        "job_title": title,
        "status": assignment.status,
        "stage_label": STAGE_LABELS.get(assignment.status, assignment.status.replace("_", " ").title()),
        "assignment_attempt": int(assignment.assignment_attempt),
        "candidate_count": int(assignment.candidate_count),
        "matching_score": int(assignment.matching_score),
        "fairness_rank": int(assignment.fairness_rank),
        "selection_reason": assignment.selection_reason,
        "agent": {
            "id": str(worker.id),
            "name": worker.name,
            "slug": worker.slug,
            "wallet_address": worker.worker_wallet_address,
        },
        "runtime": runtime_public,
        "runtime_last_seen_at": _iso(assignment.runtime_last_seen_at),
        "attention_required": bool(attention_code),
        "attention_code": attention_code,
        "attention_message": attention_message,
        "repository": f"{job.draft.repository_owner}/{job.draft.repository_name}",
        "issue_number": int(job.draft.issue_number),
        "reserved_at": _iso(assignment.reserved_at),
        "reserved_until": _iso(assignment.reserved_until),
        "leased_at": _iso(assignment.leased_at),
        "lease_expires_at": _iso(assignment.lease_expires_at),
        "execution_started_at": _iso(assignment.execution_started_at or item.execution_started_at),
        "execution_completed_at": _iso(assignment.execution_completed_at or item.execution_completed_at),
        "branch": item.execution_branch_name,
        "commit_sha": item.execution_commit_sha,
        "pull_request_number": item.execution_pull_request_number,
        "pull_request_url": item.execution_pull_request_url,
        "changed_files": item.execution_changed_files,
        "baseline_tests_passed": item.execution_baseline_test_passed,
        "post_change_tests_passed": bool(item.execution_post_test_passed),
        "claim_transaction_hash": str(item.claim_arc_transaction_hash or ""),
        "submission_transaction_hash": str(item.submission_arc_transaction_hash or ""),
        "verification_status": assignment.verification_status,
        "verification_report_hash": assignment.verification_report_hash,
        "verification_evidence_hash": assignment.verification_evidence_hash,
        "independent_verifier": verifier,
        "settlement_transaction_hash": str(assignment.settlement_transaction_hash or ""),
        "settlement_confirmed_at": _iso(assignment.settlement_confirmed_at),
        "failure_stage": active_failure_stage,
        "failure_message": redact_rpc_text(active_failure_message),
        "failure_history": failure_history,
        "created_at": _iso(assignment.created_at),
        "updated_at": _iso(assignment.updated_at),
    }


def job_execution_snapshot(job) -> dict[str, Any]:
    try:
        assignment = job.worker_assignment
    except WorkerJobAssignment.DoesNotExist:
        assignment = None
    controller = controller_public_snapshot()
    matching_status = "ASSIGNED" if assignment else "IDLE"
    matching_reason_code = ""
    matching_next_retry_at = None
    message = "No autonomous execution assignment exists for this job yet."
    if assignment is None and job.status == "FUNDED":
        items = list(
            WorkerJobQueueItem.objects.filter(job=job)
            .select_related("worker")
            .order_by("-last_checked_at", "-updated_at")
        )
        retry_item = next(
            (
                value
                for value in items
                if value.matching_next_retry_at
                and value.matching_next_retry_at > timezone.now()
            ),
            None,
        )
        if not controller["online"]:
            matching_status = "PAUSED"
            matching_reason_code = "EXECUTION_LAYER_OFFLINE"
            message = (
                "Automatic matching is paused because the execution layer is offline."
            )
        elif retry_item is not None:
            matching_status = "RETRYING"
            matching_reason_code = retry_item.eligibility_code
            matching_next_retry_at = _iso(retry_item.matching_next_retry_at)
            message = retry_item.eligibility_detail or (
                "A temporary dependency failed. Veyra will retry automatically."
            )
        elif items and all(
            value.status
            in {
                WorkerJobQueueItem.Status.INELIGIBLE,
                WorkerJobQueueItem.Status.BLOCKED,
                WorkerJobQueueItem.Status.DUPLICATE,
                WorkerJobQueueItem.Status.DEFERRED,
            }
            for value in items
        ):
            matching_status = "NO_ELIGIBLE_AGENT"
            selected = items[0]
            matching_reason_code = selected.eligibility_code or selected.status
            message = selected.eligibility_detail or (
                "No active eligible agent is currently available. "
                "Veyra will continue checking automatically."
            )
        else:
            matching_status = "MATCHING"
            message = "Veyra is matching this funded job with eligible active agents."
    elif assignment is not None:
        message = STAGE_LABELS.get(assignment.status, assignment.status)
    return {
        "automatic": True,
        "assignment": assignment_public_snapshot(assignment),
        "matching_status": matching_status,
        "matching_reason_code": matching_reason_code,
        "matching_next_retry_at": matching_next_retry_at,
        "controller": controller,
        "message": message,
    }


def worker_execution_snapshot(worker: WorkerAgent) -> dict[str, Any]:
    queryset = WorkerJobAssignment.objects.select_related(
        "job__draft", "queue_item", "worker"
    ).filter(worker=worker)
    current = queryset.filter(status__in=ACTIVE_STATUSES).order_by("created_at").first()
    recent = list(queryset.exclude(status__in=ACTIVE_STATUSES).order_by("-updated_at")[:5])
    try:
        reputation = worker.reputation_snapshot
    except Exception:
        reputation = None
    total_atomic = Decimal(getattr(reputation, "total_earned_atomic", 0) or 0)
    return {
        "auto_claim_enabled": bool(worker.auto_claim_enabled),
        "discovery_enabled": bool(worker.discovery_enabled),
        "active_jobs": queryset.filter(status__in=ACTIVE_STATUSES).count(),
        "capacity": int(worker.maximum_active_jobs),
        "current_assignment": assignment_public_snapshot(current),
        "recent_assignments": [assignment_public_snapshot(value) for value in recent],
        "reputation": {
            "karma_score": int(getattr(reputation, "karma_score", 0) or 0),
            "completed_jobs": int(getattr(reputation, "completed_jobs", 0) or 0),
            "failed_jobs": int(getattr(reputation, "failed_jobs", 0) or 0),
            "abandoned_jobs": int(getattr(reputation, "abandoned_jobs", 0) or 0),
            "total_earned_atomic": str(int(total_atomic)),
            "total_earned_usdc": str((total_atomic / Decimal(1_000_000)).quantize(Decimal("0.000001"))),
            "synced_at": _iso(getattr(reputation, "synced_at", None)),
        },
    }
