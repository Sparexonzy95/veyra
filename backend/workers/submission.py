from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from web3 import Web3

from blockchain.client import ArcClient
from jobs.models import VeyraJob
from workers.claiming import (
    CIRCLE_PENDING_STATES,
    CIRCLE_TERMINAL_FAILURE_STATES,
    CircleClaimTransaction,
    WorkerClaimError,
    _extract_transaction,
    _plain,
    _receipt_block_number,
    _receipt_status,
)
from workers.github_app_execution import GitHubAppExecutionClient, GitHubExecutionError
from workers.models import WorkerAgent, WorkerJobQueueItem
from workers.test_assignment import GitHubWorkerClient


class WorkerSubmissionError(RuntimeError):
    pass


class WorkerSubmissionPendingError(WorkerSubmissionError):
    pass


@dataclass(frozen=True)
class SubmissionPreflightResult:
    queue_item_id: str
    worker_slug: str
    job_id: int
    repository: str
    issue_number: int
    pull_request_number: int
    pull_request_url: str
    git_commit_sha: str
    commit_hash: str
    deliverable_hash: str
    claim_deadline: int
    seconds_remaining: int
    onchain_status: str
    function_signature: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubmissionExecutionResult:
    queue_item_id: str
    worker_slug: str
    job_id: int
    status: str
    circle_transaction_id: str
    circle_state: str
    arc_transaction_hash: str
    receipt_block_number: int | None
    commit_hash: str
    deliverable_hash: str
    pull_request_number: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_error(exc: Exception) -> str:
    text = str(exc or "").strip() or exc.__class__.__name__
    for name in (
        "CIRCLE_API_KEY",
        "CIRCLE_ENTITY_SECRET",
        "GITHUB_BOT_TOKEN",
        "GITHUB_TOKEN",
        "DJANGO_SECRET_KEY",
    ):
        secret = str(getattr(settings, name, "") or os.environ.get(name, "") or "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:2000] + ("…" if len(text) > 2000 else "")


def git_commit_to_bytes32(commit_sha: str) -> str:
    normalized = str(commit_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise WorkerSubmissionError("Stored Git commit SHA is invalid.")
    return Web3.to_hex(Web3.keccak(text=normalized))


def _get_item(queue_item_id: str) -> WorkerJobQueueItem:
    try:
        return WorkerJobQueueItem.objects.select_related(
            "worker", "job", "job__draft", "job__draft__funding_snapshot"
        ).get(pk=queue_item_id)
    except (WorkerJobQueueItem.DoesNotExist, ValueError) as exc:
        raise WorkerSubmissionError("Worker queue item was not found.") from exc


def _validate_local(item: WorkerJobQueueItem) -> None:
    if item.status != WorkerJobQueueItem.Status.SUBMISSION_PENDING:
        raise WorkerSubmissionError(
            f"Queue item must be SUBMISSION_PENDING, not {item.status}."
        )
    if item.worker.status != WorkerAgent.Status.ACTIVE:
        raise WorkerSubmissionError("Worker must be ACTIVE.")
    if not item.worker.contract_authorised:
        raise WorkerSubmissionError("Worker contract authorisation is missing.")
    if not item.worker.circle_wallet_id or not item.worker.worker_wallet_address:
        raise WorkerSubmissionError("Worker Circle wallet is not configured.")
    if not item.execution_post_test_passed:
        raise WorkerSubmissionError("Post-change validation did not pass.")
    if not item.execution_commit_sha:
        raise WorkerSubmissionError("Execution commit SHA is missing.")
    if not item.execution_pull_request_number or not item.execution_pull_request_url:
        raise WorkerSubmissionError("Execution pull request record is missing.")
    if item.submission_circle_transaction_id or item.submission_arc_transaction_hash:
        raise WorkerSubmissionError(
            "Submission transaction metadata already exists; reconcile it instead."
        )


def _validate_github_pr(item: WorkerJobQueueItem, github: GitHubWorkerClient) -> dict[str, Any]:
    draft = item.job.draft
    payload = github._request(
        "GET",
        f"/repos/{draft.repository_owner}/{draft.repository_name}/pulls/"
        f"{item.execution_pull_request_number}",
        expected=(200,),
    ).json()
    if not isinstance(payload, dict):
        raise WorkerSubmissionError("GitHub returned an invalid pull request record.")
    state = str(payload.get("state") or "").casefold()
    merged = bool(payload.get("merged"))
    if state != "open" and not merged:
        raise WorkerSubmissionError("The worker pull request is no longer open or merged.")
    head = payload.get("head") or {}
    base = payload.get("base") or {}
    head_owner = str((((head.get("repo") or {}).get("owner") or {}).get("login")) or "")
    head_ref = str(head.get("ref") or "")
    head_sha = str(head.get("sha") or "").lower()
    base_ref = str(base.get("ref") or "")
    if head_owner.casefold() != item.worker.github_username.casefold():
        raise WorkerSubmissionError("Pull request head belongs to a different account.")
    if head_ref != item.execution_branch_name:
        raise WorkerSubmissionError("Pull request head branch does not match execution.")
    if head_sha != item.execution_commit_sha.lower():
        raise WorkerSubmissionError("Pull request head SHA does not match execution commit.")
    if base_ref != draft.target_branch:
        raise WorkerSubmissionError("Pull request base branch does not match the committed target.")
    if str(payload.get("html_url") or "") != item.execution_pull_request_url:
        raise WorkerSubmissionError("Pull request URL does not match the stored record.")
    return payload




def _validate_github_app_pr(item: WorkerJobQueueItem) -> dict[str, Any]:
    draft = item.job.draft
    try:
        client = GitHubAppExecutionClient.for_job(item.job)
        snapshot = client.pull_request(
            owner=draft.repository_owner,
            repository=draft.repository_name,
            number=int(item.execution_pull_request_number or 0),
        )
    except GitHubExecutionError as exc:
        raise WorkerSubmissionError(str(exc)) from exc
    if snapshot.state != "open" and not snapshot.merged:
        raise WorkerSubmissionError("The worker pull request is no longer open or merged.")
    if snapshot.head_ref != item.execution_branch_name:
        raise WorkerSubmissionError("Pull request head branch does not match execution.")
    if snapshot.head_sha != item.execution_commit_sha.lower():
        raise WorkerSubmissionError("Pull request head SHA does not match execution commit.")
    if snapshot.base_ref != draft.target_branch:
        raise WorkerSubmissionError("Pull request base branch does not match the committed target.")
    if snapshot.html_url != item.execution_pull_request_url:
        raise WorkerSubmissionError("Pull request URL does not match the stored record.")
    if tuple(sorted(snapshot.changed_files)) != tuple(sorted(item.execution_changed_files)):
        raise WorkerSubmissionError("Pull request changed files do not match the signed runtime evidence.")
    return {
        "number": snapshot.number,
        "html_url": snapshot.html_url,
        "state": snapshot.state,
        "merged": snapshot.merged,
        "head": {"ref": snapshot.head_ref, "sha": snapshot.head_sha},
        "base": {"ref": snapshot.base_ref},
        "changed_files": list(snapshot.changed_files),
    }


def _live_onchain(item: WorkerJobQueueItem, arc: ArcClient) -> dict[str, Any]:
    arc.assert_chain()
    onchain = arc.get_job(item.job.onchain_job_id)
    if onchain.get("status") != "CLAIMED":
        raise WorkerSubmissionError(
            f"Arc reports {onchain.get('status') or 'UNKNOWN'}, not CLAIMED."
        )
    if str(onchain.get("provider") or "").lower() != item.worker.worker_wallet_address.lower():
        raise WorkerSubmissionError("Arc records a different provider.")
    remaining = int(onchain.get("claim_deadline") or 0) - int(time.time())
    minimum = int(getattr(settings, "WORKER_SUBMISSION_MIN_REMAINING_SECONDS", 120))
    if remaining <= minimum:
        raise WorkerSubmissionError(
            f"Only {remaining} seconds remain before the submission deadline."
        )
    return onchain


def preflight_worker_job_submission(
    queue_item_id: str,
    *,
    arc_client: ArcClient | None = None,
    github_client: GitHubWorkerClient | None = None,
) -> SubmissionPreflightResult:
    item = _get_item(queue_item_id)
    _validate_local(item)
    arc = arc_client or ArcClient()
    onchain = _live_onchain(item, arc)
    if item.job.draft.github_repository_access_id:
        _validate_github_app_pr(item)
    else:
        github = github_client or GitHubWorkerClient()
        account = github.authenticated_user()
        if str(account.get("login") or "").casefold() != item.worker.github_username.casefold():
            raise WorkerSubmissionError("GitHub account does not match worker.")
        _validate_github_pr(item, github)
    commit_hash = git_commit_to_bytes32(item.execution_commit_sha)
    deliverable_hash = arc.compute_deliverable_hash(
        item.job.onchain_job_id,
        commit_hash,
        int(item.execution_pull_request_number),
    )
    remaining = int(onchain.get("claim_deadline") or 0) - int(time.time())
    draft = item.job.draft
    return SubmissionPreflightResult(
        queue_item_id=str(item.id),
        worker_slug=item.worker.slug,
        job_id=int(item.job.onchain_job_id),
        repository=f"{draft.repository_owner}/{draft.repository_name}",
        issue_number=int(draft.issue_number),
        pull_request_number=int(item.execution_pull_request_number),
        pull_request_url=item.execution_pull_request_url,
        git_commit_sha=item.execution_commit_sha,
        commit_hash=commit_hash,
        deliverable_hash=deliverable_hash,
        claim_deadline=int(onchain.get("claim_deadline") or 0),
        seconds_remaining=remaining,
        onchain_status=str(onchain.get("status") or "UNKNOWN"),
        function_signature="submitWork(uint256,bytes32,uint64)",
    )


class CircleDeveloperSubmissionClient:
    def __init__(self):
        api_key = str(getattr(settings, "CIRCLE_API_KEY", "") or "").strip()
        entity_secret = str(getattr(settings, "CIRCLE_ENTITY_SECRET", "") or "").strip()
        if not api_key or not entity_secret:
            raise WorkerSubmissionError("Circle developer wallet credentials are not configured.")
        try:
            from circle.web3 import developer_controlled_wallets, utils
        except ImportError as exc:
            raise WorkerSubmissionError("Circle developer wallet SDK is not installed.") from exc
        self._sdk = developer_controlled_wallets
        try:
            client = utils.init_developer_controlled_wallets_client(
                api_key=api_key,
                entity_secret=entity_secret,
            )
            self._transactions = developer_controlled_wallets.TransactionsApi(client)
        except Exception as exc:
            raise WorkerSubmissionError(
                f"Circle submission client initialization failed: {_safe_error(exc)}"
            ) from exc

    def create_submission(
        self,
        *,
        worker_wallet_address: str,
        job_id: int,
        commit_hash: str,
        pull_request_number: int,
        idempotency_key: uuid.UUID,
    ) -> CircleClaimTransaction:
        payload = {
            "idempotencyKey": str(idempotency_key),
            "walletAddress": worker_wallet_address,
            "blockchain": settings.ARC_BLOCKCHAIN,
            "contractAddress": settings.VEYRA_CONTRACT_ADDRESS,
            "abiFunctionSignature": "submitWork(uint256,bytes32,uint64)",
            "abiParameters": [str(job_id), commit_hash, str(pull_request_number)],
            "feeLevel": getattr(settings, "WORKER_SUBMISSION_FEE_LEVEL", "MEDIUM"),
        }
        try:
            request = self._sdk.CreateContractExecutionTransactionForDeveloperRequest.from_dict(payload)
            response = self._transactions.create_developer_transaction_contract_execution(request)
            return _extract_transaction(response)
        except Exception as exc:
            raise WorkerSubmissionError(
                f"Circle submission transaction creation failed: {_safe_error(exc)}"
            ) from exc

    def get_transaction(self, transaction_id: str) -> CircleClaimTransaction:
        try:
            return _extract_transaction(self._transactions.get_transaction(id=transaction_id))
        except Exception as exc:
            raise WorkerSubmissionError(
                f"Circle submission transaction lookup failed: {_safe_error(exc)}"
            ) from exc


@transaction.atomic
def _reserve_submission(queue_item_id: str, commit_hash: str, deliverable_hash: str) -> WorkerJobQueueItem:
    item = WorkerJobQueueItem.objects.select_for_update().select_related(
        "worker", "job", "job__draft"
    ).get(pk=queue_item_id)
    _validate_local(item)
    now = timezone.now()
    item.submission_idempotency_key = item.submission_idempotency_key or uuid.uuid4()
    item.submission_attempt_count += 1
    item.submission_commit_hash = commit_hash
    item.submission_deliverable_hash = deliverable_hash
    item.submission_started_at = now
    item.submission_last_checked_at = now
    item.submission_failure_stage = ""
    item.submission_failure_message = ""
    item.save()
    return item


def _record_submission_snapshot(queue_item_id: str, snapshot: CircleClaimTransaction) -> None:
    with transaction.atomic():
        item = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        if item.submission_circle_transaction_id and item.submission_circle_transaction_id != snapshot.transaction_id:
            raise WorkerSubmissionError("A different Circle submission transaction is already stored.")
        item.submission_circle_transaction_id = snapshot.transaction_id
        item.submission_circle_state = snapshot.state
        if snapshot.tx_hash:
            item.submission_arc_transaction_hash = snapshot.tx_hash
        item.submission_submitted_at = item.submission_submitted_at or timezone.now()
        item.submission_last_checked_at = timezone.now()
        item.save()


def _mark_failure(queue_item_id: str, *, stage: str, message: str, terminal: bool = False) -> None:
    with transaction.atomic():
        item = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        item.submission_failure_stage = stage[:80]
        item.submission_failure_message = message[:2000]
        item.submission_last_checked_at = timezone.now()
        # Keep SUBMISSION_PENDING on both terminal and uncertain failures. The
        # onchain job remains claimed and capacity must remain occupied.
        item.status = WorkerJobQueueItem.Status.SUBMISSION_PENDING
        item.save()


def _wait_circle(
    queue_item_id: str,
    *,
    circle: CircleDeveloperSubmissionClient,
    initial: CircleClaimTransaction,
    sleep_fn: Callable[[float], None],
) -> CircleClaimTransaction:
    timeout = int(getattr(settings, "WORKER_SUBMISSION_TIMEOUT_SECONDS", 180))
    interval = float(getattr(settings, "WORKER_SUBMISSION_POLL_INTERVAL_SECONDS", 2))
    deadline = time.monotonic() + max(timeout, 0)
    current = initial
    while True:
        if current.state == "COMPLETE":
            return current
        if current.state in CIRCLE_TERMINAL_FAILURE_STATES:
            message = current.failure_message or f"Circle ended in state {current.state}."
            _mark_failure(queue_item_id, stage="circle_transaction", message=message, terminal=True)
            raise WorkerSubmissionError(message)
        if time.monotonic() >= deadline:
            message = "Circle submission is still pending. Reconcile; do not resubmit."
            _mark_failure(queue_item_id, stage="circle_pending", message=message)
            raise WorkerSubmissionPendingError(message)
        sleep_fn(max(interval, 0))
        current = circle.get_transaction(current.transaction_id)
        _record_submission_snapshot(queue_item_id, current)


def _wait_receipt(
    queue_item_id: str,
    *,
    arc: ArcClient,
    tx_hash: str,
    sleep_fn: Callable[[float], None],
) -> Any:
    timeout = int(getattr(settings, "WORKER_ARC_RECEIPT_TIMEOUT_SECONDS", 120))
    interval = float(getattr(settings, "WORKER_SUBMISSION_POLL_INTERVAL_SECONDS", 2))
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        receipt = arc.transaction_receipt_or_none(tx_hash)
        if receipt is not None:
            return receipt
        if time.monotonic() >= deadline:
            message = "Circle completed, but Arc receipt is pending. Reconcile; do not resubmit."
            _mark_failure(queue_item_id, stage="arc_receipt_pending", message=message)
            raise WorkerSubmissionPendingError(message)
        sleep_fn(max(interval, 0))


def _verify_event(
    *,
    arc: ArcClient,
    receipt: Any,
    job_id: int,
    provider: str,
    deliverable_hash: str,
    commit_hash: str,
    pull_request_number: int,
) -> None:
    for log in arc.decode_receipt_event("WorkSubmitted", receipt):
        args = log.get("args", {}) if isinstance(log, dict) else getattr(log, "args", {})
        if (
            int(args.get("jobId", -1)) == job_id
            and str(args.get("provider") or "").lower() == provider.lower()
            and Web3.to_hex(args.get("deliverableHash")) == deliverable_hash
            and Web3.to_hex(args.get("commitHash")) == commit_hash
            and int(args.get("pullRequestNumber", 0)) == pull_request_number
        ):
            return
    raise WorkerSubmissionError("Arc receipt did not contain the expected WorkSubmitted event.")


def _finalize(
    queue_item_id: str,
    *,
    arc: ArcClient,
    tx_hash: str,
    receipt: Any,
) -> SubmissionExecutionResult:
    item = _get_item(queue_item_id)
    if _receipt_status(receipt) != 1:
        raise WorkerSubmissionError("Arc submission receipt reports a reverted transaction.")
    job_id = int(item.job.onchain_job_id)
    pr = int(item.execution_pull_request_number)
    _verify_event(
        arc=arc,
        receipt=receipt,
        job_id=job_id,
        provider=item.worker.worker_wallet_address,
        deliverable_hash=item.submission_deliverable_hash,
        commit_hash=item.submission_commit_hash,
        pull_request_number=pr,
    )
    onchain = arc.get_job(job_id)
    if onchain.get("status") != "SUBMITTED":
        raise WorkerSubmissionError(
            f"Arc reports {onchain.get('status') or 'UNKNOWN'} after submission."
        )
    if str(onchain.get("provider") or "").lower() != item.worker.worker_wallet_address.lower():
        raise WorkerSubmissionError("Arc records a different provider after submission.")
    if str(onchain.get("commit_hash") or "").lower() != item.submission_commit_hash.lower():
        raise WorkerSubmissionError("Arc commit hash does not match the submitted commitment.")
    if int(onchain.get("pull_request_number") or 0) != pr:
        raise WorkerSubmissionError("Arc pull request number does not match.")
    if str(onchain.get("deliverable_hash") or "").lower() != item.submission_deliverable_hash.lower():
        raise WorkerSubmissionError("Arc deliverable hash does not match.")

    now = timezone.now()
    block = _receipt_block_number(receipt)
    with transaction.atomic():
        locked = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        locked.status = WorkerJobQueueItem.Status.SUBMITTED
        locked.onchain_status = "SUBMITTED"
        locked.onchain_snapshot = {
            key: value
            for key, value in onchain.items()
            if key not in {"rejection_reason_hash", "report_hash", "evidence_hash"}
        }
        locked.submission_circle_state = "COMPLETE"
        locked.submission_arc_transaction_hash = tx_hash
        locked.submission_receipt_block_number = block
        locked.submission_last_checked_at = now
        locked.submission_confirmed_at = now
        locked.submission_failure_stage = ""
        locked.submission_failure_message = ""
        locked.save()

        job = VeyraJob.objects.select_for_update().get(pk=locked.job_id)
        job.status = "SUBMITTED"
        job.client_status = "UNDER_REVIEW"
        job.commit_hash = locked.submission_commit_hash
        job.deliverable_hash = locked.submission_deliverable_hash
        job.pull_request_number = pr
        job.save(
            update_fields=[
                "status",
                "client_status",
                "commit_hash",
                "deliverable_hash",
                "pull_request_number",
                "updated_at",
            ]
        )

    return SubmissionExecutionResult(
        queue_item_id=str(item.id),
        worker_slug=item.worker.slug,
        job_id=job_id,
        status=WorkerJobQueueItem.Status.SUBMITTED,
        circle_transaction_id=str(item.submission_circle_transaction_id or ""),
        circle_state="COMPLETE",
        arc_transaction_hash=tx_hash,
        receipt_block_number=block,
        commit_hash=item.submission_commit_hash,
        deliverable_hash=item.submission_deliverable_hash,
        pull_request_number=pr,
    )


def execute_worker_job_submission(
    queue_item_id: str,
    *,
    arc_client: ArcClient | None = None,
    github_client: GitHubWorkerClient | None = None,
    circle_client: CircleDeveloperSubmissionClient | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> SubmissionExecutionResult:
    preflight = preflight_worker_job_submission(
        queue_item_id,
        arc_client=arc_client,
        github_client=github_client,
    )
    item = _reserve_submission(
        queue_item_id,
        preflight.commit_hash,
        preflight.deliverable_hash,
    )
    circle = circle_client or CircleDeveloperSubmissionClient()
    try:
        created = circle.create_submission(
            worker_wallet_address=item.worker.worker_wallet_address,
            job_id=int(item.job.onchain_job_id),
            commit_hash=preflight.commit_hash,
            pull_request_number=int(item.execution_pull_request_number),
            idempotency_key=item.submission_idempotency_key,
        )
        _record_submission_snapshot(queue_item_id, created)
    except Exception as exc:
        message = _safe_error(exc)
        _mark_failure(
            queue_item_id,
            stage="circle_submission_unknown",
            message=message + " Outcome may be unknown; reconcile before retry.",
        )
        raise WorkerSubmissionPendingError(message + " Reconcile before retry.") from exc

    completed = _wait_circle(
        queue_item_id,
        circle=circle,
        initial=created,
        sleep_fn=sleep_fn,
    )
    if not (completed.tx_hash.startswith("0x") and len(completed.tx_hash) == 66):
        message = "Circle completed without a valid Arc transaction hash."
        _mark_failure(queue_item_id, stage="missing_tx_hash", message=message)
        raise WorkerSubmissionPendingError(message)
    arc = arc_client or ArcClient()
    receipt = _wait_receipt(
        queue_item_id,
        arc=arc,
        tx_hash=completed.tx_hash,
        sleep_fn=sleep_fn,
    )
    try:
        return _finalize(queue_item_id, arc=arc, tx_hash=completed.tx_hash, receipt=receipt)
    except Exception as exc:
        message = _safe_error(exc)
        _mark_failure(queue_item_id, stage="arc_submission_verification", message=message)
        raise WorkerSubmissionPendingError(message) from exc


def reconcile_worker_job_submission(
    queue_item_id: str,
    *,
    arc_client: ArcClient | None = None,
    circle_client: CircleDeveloperSubmissionClient | None = None,
) -> SubmissionExecutionResult | None:
    item = _get_item(queue_item_id)
    if item.status == WorkerJobQueueItem.Status.SUBMITTED:
        return SubmissionExecutionResult(
            queue_item_id=str(item.id),
            worker_slug=item.worker.slug,
            job_id=int(item.job.onchain_job_id),
            status=item.status,
            circle_transaction_id=str(item.submission_circle_transaction_id or ""),
            circle_state=item.submission_circle_state,
            arc_transaction_hash=str(item.submission_arc_transaction_hash or ""),
            receipt_block_number=item.submission_receipt_block_number,
            commit_hash=item.submission_commit_hash,
            deliverable_hash=item.submission_deliverable_hash,
            pull_request_number=int(item.execution_pull_request_number or 0),
        )
    if item.status != WorkerJobQueueItem.Status.SUBMISSION_PENDING:
        raise WorkerSubmissionError(
            f"Only SUBMISSION_PENDING items can be reconciled; status is {item.status}."
        )
    arc = arc_client or ArcClient()
    arc.assert_chain()
    onchain = arc.get_job(item.job.onchain_job_id)
    if onchain.get("status") == "SUBMITTED":
        tx_hash = str(item.submission_arc_transaction_hash or "")
        if not tx_hash:
            raise WorkerSubmissionPendingError(
                "Arc reports SUBMITTED but the transaction hash is not stored yet."
            )
        receipt = arc.transaction_receipt_or_none(tx_hash)
        if receipt is None:
            raise WorkerSubmissionPendingError("Arc submission receipt is still pending.")
        return _finalize(queue_item_id, arc=arc, tx_hash=tx_hash, receipt=receipt)
    if onchain.get("status") != "CLAIMED":
        raise WorkerSubmissionError(
            f"Arc reports job status {onchain.get('status') or 'UNKNOWN'}."
        )
    if not item.submission_circle_transaction_id:
        raise WorkerSubmissionPendingError(
            "No Circle transaction ID is stored. Do not automatically resubmit."
        )
    circle = circle_client or CircleDeveloperSubmissionClient()
    snapshot = circle.get_transaction(item.submission_circle_transaction_id)
    _record_submission_snapshot(queue_item_id, snapshot)
    if snapshot.state in CIRCLE_TERMINAL_FAILURE_STATES:
        raise WorkerSubmissionError(
            snapshot.failure_message or f"Circle ended in state {snapshot.state}."
        )
    if snapshot.state != "COMPLETE":
        raise WorkerSubmissionPendingError(
            f"Circle submission remains {snapshot.state}; no new transaction was created."
        )
    if not snapshot.tx_hash:
        raise WorkerSubmissionPendingError("Circle completed without an Arc hash yet.")
    receipt = arc.transaction_receipt_or_none(snapshot.tx_hash)
    if receipt is None:
        raise WorkerSubmissionPendingError("Arc submission receipt is still pending.")
    return _finalize(queue_item_id, arc=arc, tx_hash=snapshot.tx_hash, receipt=receipt)
