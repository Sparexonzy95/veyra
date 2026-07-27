from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from web3 import Web3

from blockchain.client import ArcClient
from common.utils import canonical_json
from jobs.models import Notification
from workers.github_app_execution import GitHubAppExecutionClient, GitHubExecutionError
from workers.models import (
    WorkerJobAssignment,
    WorkerJobQueueItem,
    WorkerReputationSnapshot,
    WorkerVerificationAssignment,
)


ZERO_HASH = "0x" + "00" * 32
PASSING_CHECK_CONCLUSIONS = {"success", "neutral", "skipped"}
FAILING_CHECK_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "action_required",
    "startup_failure",
    "stale",
}


class ExecutionVerificationError(RuntimeError):
    pass


class ExecutionVerificationPending(ExecutionVerificationError):
    pass


@dataclass(frozen=True)
class VerificationResult:
    assignment_id: str
    approved: bool
    report_hash: str
    evidence_hash: str
    reason_hash: str
    settlement_transaction_hash: str
    status: str


def _safe_error(exc: Exception) -> str:
    text = str(exc or "").strip() or exc.__class__.__name__
    for setting_name in (
        "VEYRA_VERIFIER_PRIVATE_KEY",
        "VEYRA_CONTRACT_OWNER_PRIVATE_KEY",
        "CIRCLE_API_KEY",
        "CIRCLE_ENTITY_SECRET",
        "GITHUB_APP_PRIVATE_KEY",
    ):
        secret = str(getattr(settings, setting_name, "") or "").strip()
        if secret:
            text = text.replace(secret, "[REDACTED]")
            text = text.replace(secret.removeprefix("0x"), "[REDACTED]")
    return text[:1200]


def _hash_json(value: Any) -> str:
    return Web3.to_hex(Web3.keccak(text=canonical_json(value)))


def _verifier_signer(arc: ArcClient, assignment: WorkerJobAssignment):
    private_key = str(getattr(settings, "VEYRA_VERIFIER_PRIVATE_KEY", "") or "").strip()
    if not private_key:
        private_key = str(
            getattr(settings, "VEYRA_CONTRACT_OWNER_PRIVATE_KEY", "") or ""
        ).strip()
    if not private_key:
        raise ExecutionVerificationError(
            "VEYRA_VERIFIER_PRIVATE_KEY is not configured. For this MVP deployment it may "
            "match the existing authorised deployer verifier key."
        )
    try:
        account = arc.account_from_key(private_key)
    except Exception as exc:
        raise ExecutionVerificationError("The configured verifier private key is invalid.") from exc
    expected = Web3.to_checksum_address(assignment.job.verifier_address)
    actual = Web3.to_checksum_address(account.address)
    if actual != expected:
        raise ExecutionVerificationError(
            f"The verifier signer {actual} does not match this job's verifier {expected}."
        )
    try:
        if not arc.is_verifier_authorised(actual):
            raise ExecutionVerificationError("The configured verifier is not authorised onchain.")
    except ExecutionVerificationError:
        raise
    except Exception as exc:
        raise ExecutionVerificationError(
            f"Veyra could not read verifier authorisation: {_safe_error(exc)}"
        ) from exc
    return account


def _verification_report(assignment: WorkerJobAssignment) -> tuple[dict[str, Any], bool, str]:
    """Build the final report only after deterministic CI and verifier AI review.

    GitHub CI is a technical gate. It can reject a broken commit, but it can
    never approve payment by itself. Positive settlement always requires a
    separately owned verifier agent with a different runtime signing key.
    """

    item = assignment.queue_item
    job = assignment.job
    if item.status != WorkerJobQueueItem.Status.SUBMITTED:
        raise ExecutionVerificationPending(
            f"The on-chain submission is not ready for verification; queue status is {item.status}."
        )
    if not item.execution_post_test_passed:
        return (
            {
                "version": 2,
                "verification_mode": "CI_PLUS_INDEPENDENT_VERIFIER_AGENT",
                "job_id": int(job.onchain_job_id),
                "failure": "WORKER_POST_TEST_FAILED",
            },
            False,
            "Runtime post-change tests did not pass.",
        )

    try:
        github = GitHubAppExecutionClient.for_job(job)
        pr = github.pull_request(
            owner=job.draft.repository_owner,
            repository=job.draft.repository_name,
            number=int(item.execution_pull_request_number or 0),
        )
        checks = github.check_runs(
            owner=job.draft.repository_owner,
            repository=job.draft.repository_name,
            commit_sha=item.execution_commit_sha,
        )
    except GitHubExecutionError as exc:
        raise ExecutionVerificationPending(str(exc)) from exc

    exact_pr = bool(
        (pr.state == "open" or pr.merged)
        and pr.head_ref == item.execution_branch_name
        and pr.head_sha == item.execution_commit_sha.lower()
        and pr.base_ref == job.draft.target_branch
        and pr.html_url == item.execution_pull_request_url
        and tuple(sorted(pr.changed_files))
        == tuple(sorted(item.execution_changed_files))
    )
    if not exact_pr:
        return (
            {
                "version": 2,
                "verification_mode": "CI_PLUS_INDEPENDENT_VERIFIER_AGENT",
                "job_id": int(job.onchain_job_id),
                "commit_sha": item.execution_commit_sha,
                "pull_request_number": int(item.execution_pull_request_number or 0),
                "exact_pull_request": False,
            },
            False,
            "The pull request no longer matches the signed execution evidence.",
        )

    pending_checks = [
        check
        for check in checks
        if str(check.get("status") or "").casefold() != "completed"
    ]
    if pending_checks:
        raise ExecutionVerificationPending("GitHub CI checks are still running.")
    failed_checks = [
        check
        for check in checks
        if str(check.get("conclusion") or "").casefold()
        in FAILING_CHECK_CONCLUSIONS
    ]
    unknown_checks = [
        check
        for check in checks
        if str(check.get("conclusion") or "").casefold()
        not in PASSING_CHECK_CONCLUSIONS | FAILING_CHECK_CONCLUSIONS
    ]
    require_checks = bool(getattr(settings, "VEYRA_REQUIRE_GITHUB_CHECKS", True))
    if require_checks and not checks:
        raise ExecutionVerificationPending(
            "No GitHub Check Run is available for this exact commit. CI must be configured before verification."
        )
    ci_passed = not failed_checks and not unknown_checks and (
        bool(checks) or not require_checks
    )
    normalized_checks = [
        {
            "name": str(check.get("name") or "")[:160],
            "status": str(check.get("status") or "")[:40],
            "conclusion": str(check.get("conclusion") or "")[:40],
            "details_url": str(check.get("details_url") or "")[:500],
        }
        for check in checks
    ]
    # CI is a deterministic gate, not the final judge. Even a failing CI run
    # still waits for the verifier agent's signed review so the client receives
    # an intelligent explanation of what is wrong with the submitted work.

    try:
        verifier_run = assignment.verifier_assignment
    except WorkerVerificationAssignment.DoesNotExist as exc:
        raise ExecutionVerificationPending(
            "GitHub CI passed. Waiting for an independent verifier agent to be assigned."
        ) from exc
    if verifier_run.status in {
        WorkerVerificationAssignment.Status.RESERVED,
        WorkerVerificationAssignment.Status.LEASED,
        WorkerVerificationAssignment.Status.RUNNING,
        WorkerVerificationAssignment.Status.SUBMITTED,
    }:
        raise ExecutionVerificationPending(
            f"Independent verifier agent is still working ({verifier_run.status})."
        )
    if verifier_run.status in {
        WorkerVerificationAssignment.Status.EXPIRED,
        WorkerVerificationAssignment.Status.FAILED,
    }:
        raise ExecutionVerificationPending(
            "The verifier runtime did not complete its review. Veyra will assign the next independent verifier."
        )
    if verifier_run.status == WorkerVerificationAssignment.Status.INCONCLUSIVE:
        raise ExecutionVerificationPending(
            "The verifier agent returned an inconclusive verdict. Manual or second-verifier review is required."
        )
    if verifier_run.status not in {
        WorkerVerificationAssignment.Status.APPROVED,
        WorkerVerificationAssignment.Status.REJECTED,
    }:
        raise ExecutionVerificationPending(
            f"Independent verifier verdict is not final ({verifier_run.status})."
        )

    verifier_approved = (
        verifier_run.status == WorkerVerificationAssignment.Status.APPROVED
    )
    approved = bool(ci_passed and verifier_approved)
    if not ci_passed:
        reason = "One or more mandatory GitHub CI checks did not pass. " + str(
            verifier_run.report.get("summary")
            or "The independent verifier report is attached."
        )[:700]
    elif not verifier_approved:
        reason = str(
            verifier_run.report.get("summary")
            or "Independent verifier agent rejected the work."
        )[:1000]
    else:
        reason = ""
    report = {
        "version": 2,
        "verification_mode": "CI_PLUS_INDEPENDENT_VERIFIER_AGENT",
        "job_id": int(job.onchain_job_id),
        "assignment_id": str(assignment.id),
        "worker_id": str(assignment.worker_id),
        "provider_address": assignment.worker.worker_wallet_address.lower(),
        "repository": f"{job.draft.repository_owner}/{job.draft.repository_name}",
        "commit_sha": item.execution_commit_sha,
        "pull_request_number": int(item.execution_pull_request_number or 0),
        "pull_request_url": item.execution_pull_request_url,
        "changed_files": sorted(item.execution_changed_files),
        "runtime_evidence_hash": assignment.evidence_hash,
        "worker_runtime_signature_verified": True,
        "github_exact_commit_verified": True,
        "github_ci_passed": bool(ci_passed),
        "github_checks": normalized_checks,
        "verifier_agent": {
            "assignment_id": str(verifier_run.id),
            "agent_id": str(verifier_run.verifier_id),
            "agent_name": verifier_run.verifier.name,
            "report_hash": verifier_run.report_hash,
            "evidence_hash": verifier_run.evidence_hash,
            "runtime_signature_verified": True,
            "verdict": verifier_run.verdict,
            "report": verifier_run.report,
        },
        "approval_rule": "github_ci_passed AND independent_verifier_agent_approved",
        "approved": approved,
        "verified_at": timezone.now().isoformat(),
    }
    return report, approved, reason

def _build_settlement_transaction(
    *,
    assignment: WorkerJobAssignment,
    arc: ArcClient,
    approved: bool,
    report_hash: str,
    evidence_hash: str,
    reason_hash: str,
) -> tuple[str, str, int]:
    signer = _verifier_signer(arc, assignment)
    if approved:
        function_name = "verifyAndPay"
        function_args = (
            int(assignment.job.onchain_job_id),
            bytes.fromhex(
                assignment.queue_item.submission_deliverable_hash.removeprefix("0x")
            ),
            bytes.fromhex(report_hash.removeprefix("0x")),
        )
    else:
        function_name = "rejectAndRefund"
        function_args = (
            int(assignment.job.onchain_job_id),
            bytes.fromhex(assignment.queue_item.submission_deliverable_hash.removeprefix("0x")),
            bytes.fromhex(report_hash.removeprefix("0x")),
            bytes.fromhex(reason_hash.removeprefix("0x")),
        )
    try:
        nonce = arc.get_transaction_count(signer.address, "pending")
        tx_data = {
            "from": signer.address,
            "nonce": nonce,
            "chainId": int(settings.ARC_CHAIN_ID),
        }
        try:
            estimate = arc.estimate_contract_gas(
                function_name,
                function_args,
                {"from": signer.address},
            )
            tx_data["gas"] = max(180_000, int(estimate * 1.25))
        except Exception:
            tx_data["gas"] = 500_000
        try:
            tx_data["gasPrice"] = arc.gas_price()
        except Exception:
            pass
        unsigned = arc.build_contract_transaction(
            function_name,
            function_args,
            tx_data,
        )
        signed = signer.sign_transaction(unsigned)
        raw = arc.signed_transaction_bytes(signed)
        tx_hash = arc.signed_transaction_hash(raw)
    except ExecutionVerificationError:
        raise
    except Exception as exc:
        raise ExecutionVerificationError(
            f"Arc verification transaction failed: {_safe_error(exc)}"
        ) from exc
    return tx_hash, "0x" + raw.hex(), int(nonce)


def _receipt_status(receipt: Any) -> int:
    return int(receipt.get("status", 0) if isinstance(receipt, dict) else receipt.status)


def _receipt_block(receipt: Any) -> int | None:
    value = receipt.get("blockNumber") if isinstance(receipt, dict) else getattr(receipt, "blockNumber", None)
    return int(value) if value is not None else None


def _clear_recovered_failures(
    assignment: WorkerJobAssignment,
    item: WorkerJobQueueItem,
) -> None:
    history = list(assignment.failure_history or [])
    recovered_at = timezone.now().isoformat()
    values = [
        ("assignment", assignment.failure_stage, assignment.failure_message),
        ("claim", item.claim_failure_stage, item.claim_failure_message),
        ("execution", item.execution_failure_stage, item.execution_failure_message),
        ("submission", item.submission_failure_stage, item.submission_failure_message),
    ]
    for source, stage, message in values:
        if stage or message:
            history.append(
                {
                    "source": source,
                    "stage": str(stage or "")[:80],
                    "message": str(message or "")[:2000],
                    "recovered_at": recovered_at,
                }
            )
    assignment.failure_history = history[-20:]
    assignment.failure_stage = ""
    assignment.failure_message = ""
    item.claim_failure_stage = ""
    item.claim_failure_message = ""
    item.execution_failure_stage = ""
    item.execution_failure_message = ""
    item.submission_failure_stage = ""
    item.submission_failure_message = ""


def _sync_reputation(assignment: WorkerJobAssignment, arc: ArcClient) -> WorkerReputationSnapshot:
    address = Web3.to_checksum_address(assignment.worker.worker_wallet_address)
    try:
        karma = int(arc.contract_call("karmaScore", address))
        completed = int(arc.contract_call("completedJobs", address))
        failed = int(arc.contract_call("failedJobs", address))
        abandoned = int(arc.contract_call("abandonedJobs", address))
        earned = int(arc.contract_call("totalEarned", address))
    except Exception as exc:
        raise ExecutionVerificationPending(
            f"Settlement confirmed, but reputation could not be read yet: {_safe_error(exc)}"
        ) from exc
    snapshot, _ = WorkerReputationSnapshot.objects.update_or_create(
        worker=assignment.worker,
        defaults={
            "karma_score": karma,
            "completed_jobs": completed,
            "failed_jobs": failed,
            "abandoned_jobs": abandoned,
            "total_earned_atomic": earned,
            "last_job_id": int(assignment.job.onchain_job_id),
            "synced_at": timezone.now(),
        },
    )
    return snapshot


def sync_reputation_for_assignment(
    assignment: WorkerJobAssignment,
    *,
    arc_client: ArcClient | None = None,
) -> WorkerReputationSnapshot:
    """Refresh the public reputation snapshot from authoritative Arc state."""

    arc = arc_client or ArcClient()
    arc.assert_chain()
    assignment = WorkerJobAssignment.objects.select_related("worker", "job").get(
        pk=assignment.pk
    )
    return _sync_reputation(assignment, arc)


def verify_and_settle_assignment(
    assignment: WorkerJobAssignment,
    *,
    arc_client: ArcClient | None = None,
) -> VerificationResult:
    assignment = WorkerJobAssignment.objects.select_related(
        "worker",
        "queue_item",
        "job__client",
        "job__draft__funding_snapshot",
        "job__draft__github_repository_access__installation",
    ).get(pk=assignment.pk)
    if assignment.status == WorkerJobAssignment.Status.COMPLETED:
        return VerificationResult(
            assignment_id=str(assignment.id),
            approved=assignment.verification_status == "APPROVED",
            report_hash=assignment.verification_report_hash,
            evidence_hash=assignment.verification_evidence_hash,
            reason_hash=assignment.verification_reason_hash,
            settlement_transaction_hash=str(assignment.settlement_transaction_hash or ""),
            status=assignment.status,
        )
    if assignment.status not in {
        WorkerJobAssignment.Status.SUBMITTED,
        WorkerJobAssignment.Status.VERIFYING,
        WorkerJobAssignment.Status.SETTLING,
    }:
        raise ExecutionVerificationError(
            f"Assignment must be SUBMITTED, VERIFYING, or SETTLING, not {assignment.status}."
        )

    arc = arc_client or ArcClient()
    arc.assert_chain()
    onchain = arc.get_job(assignment.job.onchain_job_id)
    if onchain.get("status") in {"COMPLETED", "REJECTED"}:
        approved = onchain.get("status") == "COMPLETED"
        receipt = None
        if assignment.settlement_transaction_hash:
            receipt = arc.transaction_receipt_or_none(assignment.settlement_transaction_hash)
        now = timezone.now()
        with transaction.atomic():
            locked = WorkerJobAssignment.objects.select_for_update().select_related("queue_item", "job").get(pk=assignment.pk)
            locked.status = WorkerJobAssignment.Status.COMPLETED
            locked.verification_status = "APPROVED" if approved else "REJECTED"
            locked.settlement_confirmed_at = now
            locked.settlement_receipt_block_number = _receipt_block(receipt) if receipt is not None else locked.settlement_receipt_block_number
            locked.completed_at = now
            _clear_recovered_failures(locked, locked.queue_item)
            locked.save()
            item = locked.queue_item
            item.status = WorkerJobQueueItem.Status.COMPLETED
            item.onchain_status = onchain.get("status")
            item.save()
            job = locked.job
            job.status = onchain.get("status")
            job.client_status = onchain.get("client_status")
            job.report_hash = onchain.get("report_hash") or job.report_hash
            job.evidence_hash = onchain.get("evidence_hash") or job.evidence_hash
            job.rejection_reason_hash = onchain.get("rejection_reason_hash") or job.rejection_reason_hash
            job.save()
        try:
            _sync_reputation(assignment, arc)
        except ExecutionVerificationPending:
            # Settlement is already final. The control-plane process retries
            # reputation synchronization independently without reopening payment.
            pass
        return VerificationResult(
            assignment_id=str(assignment.id),
            approved=approved,
            report_hash=assignment.verification_report_hash,
            evidence_hash=assignment.verification_evidence_hash,
            reason_hash=assignment.verification_reason_hash,
            settlement_transaction_hash=str(assignment.settlement_transaction_hash or ""),
            status=WorkerJobAssignment.Status.COMPLETED,
        )
    if onchain.get("status") != "SUBMITTED":
        raise ExecutionVerificationPending(
            f"Arc reports {onchain.get('status') or 'UNKNOWN'}; waiting for SUBMITTED."
        )
    if str(onchain.get("provider") or "").lower() != assignment.worker.worker_wallet_address.lower():
        raise ExecutionVerificationError("Arc records a different provider for this submission.")
    if str(onchain.get("deliverable_hash") or "").lower() != assignment.queue_item.submission_deliverable_hash.lower():
        raise ExecutionVerificationError("Arc deliverable hash does not match the stored submission.")

    if assignment.verification_report_hash:
        report = assignment.verification_report
        approved = assignment.verification_status == "APPROVED"
        reason_hash = assignment.verification_reason_hash or ZERO_HASH
        report_hash = assignment.verification_report_hash
        evidence_hash = assignment.verification_evidence_hash
    else:
        report, approved, reason = _verification_report(assignment)
        report_hash = _hash_json(report)
        reason_hash = ZERO_HASH if approved else _hash_json({"reason": reason})
        try:
            value = arc.contract_call(
                "computeEvidenceHash",
                int(assignment.job.onchain_job_id),
                bytes.fromhex(assignment.queue_item.submission_deliverable_hash.removeprefix("0x")),
                bytes.fromhex(report_hash.removeprefix("0x")),
                bool(approved),
                bytes.fromhex(reason_hash.removeprefix("0x")),
            )
            evidence_hash = Web3.to_hex(value)
        except Exception as exc:
            raise ExecutionVerificationPending(
                f"Could not compute the on-chain evidence hash yet: {_safe_error(exc)}"
            ) from exc
        with transaction.atomic():
            locked = WorkerJobAssignment.objects.select_for_update().get(pk=assignment.pk)
            locked.status = WorkerJobAssignment.Status.VERIFYING
            locked.verification_status = "APPROVED" if approved else "REJECTED"
            locked.verification_report = report
            locked.verification_report_hash = report_hash
            locked.verification_evidence_hash = evidence_hash
            locked.verification_reason_hash = reason_hash
            locked.verification_started_at = locked.verification_started_at or timezone.now()
            locked.verification_completed_at = timezone.now()
            locked.save()
            assignment = locked
            assignment.queue_item.status = WorkerJobQueueItem.Status.VERIFYING
            assignment.queue_item.save(update_fields=["status", "updated_at"])

    tx_hash = str(assignment.settlement_transaction_hash or "")
    if not tx_hash:
        with transaction.atomic():
            locked = WorkerJobAssignment.objects.select_for_update().get(pk=assignment.pk)
            if not locked.settlement_transaction_hash:
                tx_hash, raw_transaction, nonce = _build_settlement_transaction(
                    assignment=assignment,
                    arc=arc,
                    approved=approved,
                    report_hash=report_hash,
                    evidence_hash=evidence_hash,
                    reason_hash=reason_hash,
                )
                locked.settlement_transaction_hash = tx_hash
                locked.settlement_raw_transaction = raw_transaction
                locked.settlement_nonce = nonce
                locked.settlement_started_at = timezone.now()
                locked.status = WorkerJobAssignment.Status.SETTLING
                locked.save(
                    update_fields=[
                        "settlement_transaction_hash",
                        "settlement_raw_transaction",
                        "settlement_nonce",
                        "settlement_started_at",
                        "status",
                        "updated_at",
                    ]
                )
                locked.queue_item.status = WorkerJobQueueItem.Status.SETTLING
                locked.queue_item.save(update_fields=["status", "updated_at"])
            else:
                tx_hash = locked.settlement_transaction_hash

    assignment.refresh_from_db()
    raw_hex = str(assignment.settlement_raw_transaction or "")
    if raw_hex:
        try:
            arc.broadcast_signed_transaction(
                bytes.fromhex(raw_hex.removeprefix("0x")),
                tx_hash,
                state_check=lambda provider: int(
                    arc.provider_contract_call(
                        provider,
                        "getJob",
                        int(assignment.job.onchain_job_id),
                    )[16]
                )
                in {4, 5},
            )
        except Exception as exc:
            raise ExecutionVerificationPending(
                "The preserved settlement transaction has an unknown broadcast "
                f"result and will be reconciled: {_safe_error(exc)}"
            ) from exc

    timeout = int(getattr(settings, "VEYRA_SETTLEMENT_TIMEOUT_SECONDS", 180))
    poll = max(1, int(getattr(settings, "VEYRA_SETTLEMENT_POLL_INTERVAL_SECONDS", 3)))
    try:
        receipt = arc.wait_for_transaction_receipt(
            tx_hash, timeout=timeout, poll_latency=poll
        )
    except Exception as exc:
        raise ExecutionVerificationPending(
            f"Settlement transaction is pending and will be reconciled: {_safe_error(exc)}"
        ) from exc
    if _receipt_status(receipt) != 1:
        raise ExecutionVerificationError("The Arc verification and settlement transaction reverted.")

    deadline = time.monotonic() + int(getattr(settings, "WORKER_ARC_RECEIPT_TIMEOUT_SECONDS", 120))
    final = onchain
    while time.monotonic() < deadline:
        final = arc.get_job(assignment.job.onchain_job_id)
        if final.get("status") in {"COMPLETED", "REJECTED"}:
            break
        time.sleep(poll)
    if final.get("status") not in {"COMPLETED", "REJECTED"}:
        raise ExecutionVerificationPending("Settlement succeeded, but the final Arc job state is not visible yet.")

    now = timezone.now()
    with transaction.atomic():
        locked = WorkerJobAssignment.objects.select_for_update().select_related("queue_item", "job").get(pk=assignment.pk)
        locked.status = WorkerJobAssignment.Status.COMPLETED
        locked.settlement_receipt_block_number = _receipt_block(receipt)
        locked.settlement_confirmed_at = now
        locked.completed_at = now
        _clear_recovered_failures(locked, locked.queue_item)
        locked.save()
        item = locked.queue_item
        item.status = WorkerJobQueueItem.Status.COMPLETED
        item.onchain_status = final.get("status")
        item.save()
        job = locked.job
        job.status = final.get("status")
        job.client_status = final.get("client_status")
        job.report_hash = final.get("report_hash") or report_hash
        job.evidence_hash = final.get("evidence_hash") or evidence_hash
        job.rejection_reason_hash = final.get("rejection_reason_hash") or (reason_hash if not approved else "")
        job.save()
        Notification.objects.create(
            user=job.client,
            event_type="JOB_COMPLETED" if approved else "JOB_REJECTED",
            title="Verified work paid" if approved else "Work rejected and refunded",
            body=(
                f"Arc job {job.onchain_job_id} passed independent verification and settlement completed."
                if approved
                else f"Arc job {job.onchain_job_id} did not pass verification and was refunded."
            ),
            resource_type="VeyraJob",
            resource_id=str(job.onchain_job_id),
        )
        if locked.worker.owner_user_id:
            Notification.objects.create(
                user=locked.worker.owner_user,
                event_type="AGENT_JOB_PAID" if approved else "AGENT_JOB_REJECTED",
                title="Agent earned USDC" if approved else "Agent submission rejected",
                body=(
                    f"{locked.worker.name} completed Arc job {job.onchain_job_id}."
                    if approved
                    else f"{locked.worker.name}'s submission for Arc job {job.onchain_job_id} was rejected."
                ),
                resource_type="WorkerJobAssignment",
                resource_id=str(locked.id),
            )
    try:
        _sync_reputation(assignment, arc)
    except ExecutionVerificationPending:
        # Settlement is already final. The control-plane process retries
        # reputation synchronization independently without reopening payment.
        pass
    return VerificationResult(
        assignment_id=str(assignment.id),
        approved=approved,
        report_hash=report_hash,
        evidence_hash=evidence_hash,
        reason_hash=reason_hash,
        settlement_transaction_hash=tx_hash,
        status=WorkerJobAssignment.Status.COMPLETED,
    )
