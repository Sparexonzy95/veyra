from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from blockchain.client import ArcClient
from jobs.models import VeyraJob
from workers.discovery import EligibilityResult, evaluate_job
from workers.github_freshness import GitHubFreshnessGuard
from workers.models import WorkerAgent, WorkerJobQueueItem

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
CIRCLE_PENDING_STATES = {
    "INITIATED",
    "PENDING",
    "QUEUED",
    "SENT",
    "CONFIRMED",
}
CIRCLE_TERMINAL_FAILURE_STATES = {"FAILED", "CANCELLED", "DENIED"}


class WorkerClaimError(RuntimeError):
    """Base class for safe worker-claim failures."""


class WorkerClaimPendingError(WorkerClaimError):
    """The claim may still complete and must be reconciled, not resubmitted."""


@dataclass(frozen=True)
class ClaimPreflightResult:
    queue_item_id: str
    worker_slug: str
    job_id: int
    repository: str
    issue_number: int
    issue_title: str
    worker_wallet_address: str
    circle_wallet_id: str
    contract_address: str
    function_signature: str
    eligibility_code: str
    github_freshness_code: str
    onchain_status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CircleClaimTransaction:
    transaction_id: str
    state: str
    tx_hash: str = ""
    block_height: int | None = None
    failure_message: str = ""


@dataclass(frozen=True)
class ClaimExecutionResult:
    queue_item_id: str
    worker_slug: str
    job_id: int
    status: str
    circle_transaction_id: str
    circle_state: str
    arc_transaction_hash: str
    receipt_block_number: int | None
    provider_address: str
    claim_deadline: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_error(exc: Exception) -> str:
    text = str(exc or "").strip() or exc.__class__.__name__
    for secret_name in ("CIRCLE_API_KEY", "CIRCLE_ENTITY_SECRET"):
        secret = str(getattr(settings, secret_name, "") or "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text if len(text) <= 1000 else text[:1000] + "…"


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    actual = getattr(value, "actual_instance", None)
    if actual is not None and actual is not value:
        return _plain(actual)
    for method_name in ("to_dict", "model_dump"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                return _plain(method())
            except Exception:
                pass
    result = {}
    for name in (
        "id",
        "state",
        "tx_hash",
        "txHash",
        "block_height",
        "blockHeight",
        "error_reason",
        "errorReason",
    ):
        if hasattr(value, name):
            result[name] = _plain(getattr(value, name))
    return result or str(value)


def _extract_transaction(value: Any) -> CircleClaimTransaction:
    payload = _plain(getattr(value, "data", value))
    if isinstance(payload, dict) and isinstance(payload.get("transaction"), dict):
        payload = payload["transaction"]
    if not isinstance(payload, dict):
        raise WorkerClaimError("Circle returned an invalid transaction response.")

    transaction_id = str(payload.get("id") or "").strip()
    state = str(payload.get("state") or "UNKNOWN").upper().strip()
    tx_hash = str(payload.get("txHash") or payload.get("tx_hash") or "").strip()
    block_height_raw = payload.get("blockHeight", payload.get("block_height"))
    try:
        block_height = int(block_height_raw) if block_height_raw is not None else None
    except (TypeError, ValueError):
        block_height = None
    failure = str(
        payload.get("errorReason")
        or payload.get("error_reason")
        or payload.get("error")
        or ""
    ).strip()
    if not transaction_id:
        raise WorkerClaimError("Circle transaction ID was missing.")
    return CircleClaimTransaction(
        transaction_id=transaction_id,
        state=state,
        tx_hash=tx_hash,
        block_height=block_height,
        failure_message=failure,
    )


class CircleDeveloperClaimClient:
    """Small SDK adapter for one typed claimJob(uint256) transaction."""

    def __init__(self):
        api_key = str(getattr(settings, "CIRCLE_API_KEY", "") or "").strip()
        entity_secret = str(
            getattr(settings, "CIRCLE_ENTITY_SECRET", "") or ""
        ).strip()
        if not api_key:
            raise WorkerClaimError("CIRCLE_API_KEY is not configured.")
        if not entity_secret:
            raise WorkerClaimError("CIRCLE_ENTITY_SECRET is not configured.")
        try:
            from circle.web3 import developer_controlled_wallets, utils
        except ImportError as exc:
            raise WorkerClaimError(
                "Circle developer-controlled wallet SDK is not installed."
            ) from exc

        self._sdk = developer_controlled_wallets
        try:
            sdk_client = utils.init_developer_controlled_wallets_client(
                api_key=api_key,
                entity_secret=entity_secret,
            )
            self._transactions = developer_controlled_wallets.TransactionsApi(
                sdk_client
            )
        except Exception as exc:
            raise WorkerClaimError(
                f"Circle developer transaction client initialization failed: {_safe_error(exc)}"
            ) from exc

    def create_claim(
        self,
        *,
        worker_wallet_address: str,
        job_id: int,
        idempotency_key: uuid.UUID,
    ) -> CircleClaimTransaction:
        payload = {
            "idempotencyKey": str(idempotency_key),
            "walletAddress": worker_wallet_address,
            "blockchain": settings.ARC_BLOCKCHAIN,
            "contractAddress": settings.VEYRA_CONTRACT_ADDRESS,
            "abiFunctionSignature": "claimJob(uint256)",
            "abiParameters": [str(job_id)],
            "feeLevel": getattr(settings, "WORKER_CLAIM_FEE_LEVEL", "MEDIUM"),
        }
        try:
            request = self._sdk.CreateContractExecutionTransactionForDeveloperRequest.from_dict(
                payload
            )
            response = self._transactions.create_developer_transaction_contract_execution(
                request
            )
            return _extract_transaction(response)
        except WorkerClaimError:
            raise
        except Exception as exc:
            raise WorkerClaimError(
                f"Circle claim transaction creation failed: {_safe_error(exc)}"
            ) from exc

    def get_transaction(self, transaction_id: str) -> CircleClaimTransaction:
        try:
            response = self._transactions.get_transaction(id=transaction_id)
            return _extract_transaction(response)
        except WorkerClaimError:
            raise
        except Exception as exc:
            raise WorkerClaimError(
                f"Circle claim transaction lookup failed: {_safe_error(exc)}"
            ) from exc


def _get_item(queue_item_id: str) -> WorkerJobQueueItem:
    try:
        return WorkerJobQueueItem.objects.select_related(
            "worker", "job", "job__draft", "job__draft__funding_snapshot"
        ).get(pk=queue_item_id)
    except (WorkerJobQueueItem.DoesNotExist, ValueError) as exc:
        raise WorkerClaimError("Worker queue item was not found.") from exc


def _validate_queue_for_preflight(item: WorkerJobQueueItem) -> None:
    worker = item.worker
    if item.status != WorkerJobQueueItem.Status.QUEUED:
        raise WorkerClaimError(
            f"Queue item must be QUEUED, but its status is {item.status}."
        )
    if not item.eligibility_passed or item.eligibility_code != "ELIGIBLE":
        raise WorkerClaimError("Queue item is not eligible for claiming.")
    if worker.status != WorkerAgent.Status.ACTIVE:
        raise WorkerClaimError("Worker must be ACTIVE before claiming a job.")
    if not worker.contract_authorised:
        raise WorkerClaimError("Worker contract authorisation is not confirmed.")
    if not worker.circle_wallet_id or not worker.worker_wallet_address:
        raise WorkerClaimError("Worker Circle wallet is not configured.")
    if worker.wallet_blockchain != "ARC-TESTNET" or worker.wallet_account_type != "SCA":
        raise WorkerClaimError("Worker claim wallet must be an ARC-TESTNET SCA wallet.")
    if item.claim_circle_transaction_id or item.claim_arc_transaction_hash:
        raise WorkerClaimError(
            "Queue item already contains claim transaction metadata; reconcile it instead."
        )

    capacity = WorkerJobQueueItem.objects.filter(
        worker=worker,
        status__in=[
            WorkerJobQueueItem.Status.CLAIM_PENDING,
            WorkerJobQueueItem.Status.CLAIMED,
            WorkerJobQueueItem.Status.EXECUTING,
            WorkerJobQueueItem.Status.SUBMISSION_PENDING,
            WorkerJobQueueItem.Status.SUBMITTED,
        ],
    ).exclude(pk=item.pk).count()
    if capacity >= worker.maximum_active_jobs:
        raise WorkerClaimError(
            f"Worker capacity is full ({capacity}/{worker.maximum_active_jobs})."
        )


def _live_eligibility(
    item: WorkerJobQueueItem,
    *,
    arc_client: ArcClient,
    github_guard: GitHubFreshnessGuard,
) -> EligibilityResult:
    result = evaluate_job(
        item.worker,
        item.job,
        arc_client=arc_client,
        github_guard=github_guard,
        require_discovery_enabled=False,
    )
    if not result.passed:
        raise WorkerClaimError(
            f"Live claim guard failed [{result.code}]: {result.detail}"
        )
    if result.github_freshness_code != "GITHUB_FRESH":
        raise WorkerClaimError(
            "Live claim guard did not return GITHUB_FRESH."
        )
    return result


def preflight_worker_job_claim(
    queue_item_id: str,
    *,
    arc_client: ArcClient | None = None,
    github_guard: GitHubFreshnessGuard | None = None,
) -> ClaimPreflightResult:
    """Read-only claim preflight. No database status or external state is changed."""

    item = _get_item(queue_item_id)
    _validate_queue_for_preflight(item)
    client = arc_client or ArcClient()
    guard = github_guard or GitHubFreshnessGuard()

    try:
        client.assert_chain()
        if client.is_paused():
            raise WorkerClaimError("Veyra escrow is paused.")
        if not client.is_agent_authorised(item.worker.worker_wallet_address):
            raise WorkerClaimError("Worker wallet is not authorised onchain.")
        if not client.is_verifier_authorised(settings.VEYRA_VERIFIER_ADDRESS):
            raise WorkerClaimError("Verifier wallet is not authorised onchain.")
    except WorkerClaimError:
        raise
    except Exception as exc:
        raise WorkerClaimError(
            f"Arc claim preflight failed: {_safe_error(exc)}"
        ) from exc

    result = _live_eligibility(item, arc_client=client, github_guard=guard)
    draft = item.job.draft
    return ClaimPreflightResult(
        queue_item_id=str(item.id),
        worker_slug=item.worker.slug,
        job_id=int(item.job.onchain_job_id),
        repository=f"{draft.repository_owner}/{draft.repository_name}",
        issue_number=int(draft.issue_number),
        issue_title=draft.issue_title,
        worker_wallet_address=item.worker.worker_wallet_address,
        circle_wallet_id=item.worker.circle_wallet_id,
        contract_address=settings.VEYRA_CONTRACT_ADDRESS,
        function_signature="claimJob(uint256)",
        eligibility_code=result.code,
        github_freshness_code=result.github_freshness_code,
        onchain_status=result.onchain_status,
    )


@transaction.atomic
def _reserve_claim(queue_item_id: str) -> WorkerJobQueueItem:
    try:
        item = WorkerJobQueueItem.objects.select_for_update().select_related(
            "worker", "job", "job__draft", "job__draft__funding_snapshot"
        ).get(pk=queue_item_id)
    except (WorkerJobQueueItem.DoesNotExist, ValueError) as exc:
        raise WorkerClaimError("Worker queue item was not found.") from exc

    _validate_queue_for_preflight(item)
    now = timezone.now()
    item.status = WorkerJobQueueItem.Status.CLAIM_PENDING
    item.claim_idempotency_key = item.claim_idempotency_key or uuid.uuid4()
    item.claim_attempt_count += 1
    item.claim_started_at = now
    item.claim_last_checked_at = now
    item.claim_failure_stage = ""
    item.claim_failure_message = ""
    item.save()
    return item


def _status_for_guard_failure(message: str) -> str:
    if "DUPLICATE_REPOSITORY_ISSUE" in message:
        return WorkerJobQueueItem.Status.DUPLICATE
    if any(
        code in message
        for code in (
            "GITHUB_WORKER_PR_OPEN",
            "GITHUB_WORKER_PR_MERGED",
            "GITHUB_WORKER_BRANCH_EXISTS",
            "GITHUB_FORK_COLLISION",
        )
    ):
        return WorkerJobQueueItem.Status.BLOCKED
    if any(
        code in message
        for code in (
            "GITHUB_ISSUE_CLOSED",
            "GITHUB_ISSUE_NOT_FOUND",
            "GITHUB_TARGET_IS_PULL_REQUEST",
            "ONCHAIN_JOB_NOT_OPEN",
            "ALREADY_CLAIMED",
        )
    ):
        return WorkerJobQueueItem.Status.STALE
    return WorkerJobQueueItem.Status.QUEUED


def _record_guard_failure(queue_item_id: str, exc: Exception) -> None:
    message = _safe_error(exc)
    with transaction.atomic():
        item = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        if item.claim_circle_transaction_id:
            return
        item.status = _status_for_guard_failure(message)
        item.claim_failure_stage = "live_preflight"
        item.claim_failure_message = message
        item.claim_last_checked_at = timezone.now()
        item.save()


def _record_circle_submission(
    queue_item_id: str,
    snapshot: CircleClaimTransaction,
) -> WorkerJobQueueItem:
    with transaction.atomic():
        item = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        if item.status != WorkerJobQueueItem.Status.CLAIM_PENDING:
            raise WorkerClaimError(
                f"Claim reservation changed unexpectedly to {item.status}."
            )
        if item.claim_circle_transaction_id and (
            item.claim_circle_transaction_id != snapshot.transaction_id
        ):
            raise WorkerClaimError("A different Circle claim transaction is already stored.")
        item.claim_circle_transaction_id = snapshot.transaction_id
        item.claim_circle_state = snapshot.state
        if snapshot.tx_hash:
            item.claim_arc_transaction_hash = snapshot.tx_hash
        item.claim_submitted_at = item.claim_submitted_at or timezone.now()
        item.claim_last_checked_at = timezone.now()
        item.save()
        return item


def _update_circle_snapshot(
    queue_item_id: str,
    snapshot: CircleClaimTransaction,
) -> WorkerJobQueueItem:
    with transaction.atomic():
        item = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        item.claim_circle_state = snapshot.state
        if snapshot.tx_hash:
            item.claim_arc_transaction_hash = snapshot.tx_hash
        item.claim_last_checked_at = timezone.now()
        item.save()
        return item


def _mark_claim_failure(
    queue_item_id: str,
    *,
    stage: str,
    message: str,
    terminal: bool,
) -> None:
    with transaction.atomic():
        item = WorkerJobQueueItem.objects.select_for_update().get(pk=queue_item_id)
        item.claim_failure_stage = stage
        item.claim_failure_message = message[:2000]
        item.claim_last_checked_at = timezone.now()
        if terminal:
            item.status = WorkerJobQueueItem.Status.FAILED
        item.save()


def _receipt_status(receipt: Any) -> int:
    value = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
    return int(value) if value is not None else 0


def _receipt_block_number(receipt: Any) -> int | None:
    value = (
        receipt.get("blockNumber")
        if isinstance(receipt, dict)
        else getattr(receipt, "blockNumber", None)
    )
    return int(value) if value is not None else None


def _public_onchain_snapshot(onchain: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "job_id",
        "client",
        "invited_provider",
        "provider",
        "verifier",
        "budget",
        "expires_at",
        "claim_deadline",
        "repository_hash",
        "task_hash",
        "policy_hash",
        "status",
        "status_code",
        "client_status",
        "created_at",
        "claimed_at",
        "submitted_at",
        "resolved_at",
    }
    return {key: onchain[key] for key in keys if key in onchain}


def _verify_job_claimed_event(
    *,
    arc_client: ArcClient,
    receipt: Any,
    job_id: int,
    provider_address: str,
) -> None:
    logs = arc_client.decode_receipt_event("JobClaimed", receipt)
    expected_provider = provider_address.lower()
    for log in logs:
        args = log.get("args", {}) if isinstance(log, dict) else getattr(log, "args", {})
        log_job_id = int(args.get("jobId", -1))
        log_provider = str(args.get("provider") or "").lower()
        if log_job_id == job_id and log_provider == expected_provider:
            return
    raise WorkerClaimError(
        "Arc receipt did not contain the expected JobClaimed event."
    )


def _finalize_claim(
    queue_item_id: str,
    *,
    arc_client: ArcClient,
    tx_hash: str,
    receipt: Any,
) -> ClaimExecutionResult:
    item = _get_item(queue_item_id)
    worker_address = item.worker.worker_wallet_address.lower()
    job_id = int(item.job.onchain_job_id)

    if _receipt_status(receipt) != 1:
        raise WorkerClaimError("Arc claim receipt reports a reverted transaction.")
    _verify_job_claimed_event(
        arc_client=arc_client,
        receipt=receipt,
        job_id=job_id,
        provider_address=worker_address,
    )
    onchain = arc_client.get_job(job_id)
    if onchain.get("status") != "CLAIMED":
        raise WorkerClaimError(
            f"Arc reports {onchain.get('status') or 'UNKNOWN'} after claim confirmation."
        )
    if str(onchain.get("provider") or "").lower() != worker_address:
        raise WorkerClaimError("Arc records a different provider for the claimed job.")

    block_number = _receipt_block_number(receipt)
    confirmed_at = timezone.now()
    with transaction.atomic():
        locked = WorkerJobQueueItem.objects.select_for_update().select_related(
            "worker", "job"
        ).get(pk=queue_item_id)
        locked.status = WorkerJobQueueItem.Status.CLAIMED
        locked.onchain_status = "CLAIMED"
        locked.onchain_snapshot = _public_onchain_snapshot(onchain)
        locked.claim_circle_state = "COMPLETE"
        locked.claim_arc_transaction_hash = tx_hash
        locked.claim_receipt_block_number = block_number
        locked.claim_last_checked_at = confirmed_at
        locked.claim_confirmed_at = confirmed_at
        locked.claim_failure_stage = ""
        locked.claim_failure_message = ""
        locked.save()

        job = VeyraJob.objects.select_for_update().get(pk=locked.job_id)
        job.status = "CLAIMED"
        job.client_status = "AGENT_WORKING"
        job.provider_address = worker_address
        job.claim_deadline = int(onchain.get("claim_deadline") or 0)
        job.save(
            update_fields=[
                "status",
                "client_status",
                "provider_address",
                "claim_deadline",
                "updated_at",
            ]
        )

    return ClaimExecutionResult(
        queue_item_id=str(item.id),
        worker_slug=item.worker.slug,
        job_id=job_id,
        status=WorkerJobQueueItem.Status.CLAIMED,
        circle_transaction_id=str(item.claim_circle_transaction_id or ""),
        circle_state="COMPLETE",
        arc_transaction_hash=tx_hash,
        receipt_block_number=block_number,
        provider_address=worker_address,
        claim_deadline=int(onchain.get("claim_deadline") or 0),
    )


def _wait_for_circle(
    queue_item_id: str,
    *,
    circle_client: CircleDeveloperClaimClient,
    initial: CircleClaimTransaction,
    sleep_fn: Callable[[float], None],
) -> CircleClaimTransaction:
    timeout = int(getattr(settings, "WORKER_CLAIM_TIMEOUT_SECONDS", 180))
    interval = float(getattr(settings, "WORKER_CLAIM_POLL_INTERVAL_SECONDS", 3))
    deadline = time.monotonic() + max(timeout, 0)
    current = initial
    while True:
        if current.state == "COMPLETE":
            return current
        if current.state in CIRCLE_TERMINAL_FAILURE_STATES:
            message = current.failure_message or f"Circle ended in state {current.state}."
            _mark_claim_failure(
                queue_item_id,
                stage="circle_transaction",
                message=message,
                terminal=True,
            )
            raise WorkerClaimError(message)
        if time.monotonic() >= deadline:
            message = (
                "Circle claim transaction is still pending. Reconcile this queue item; "
                "do not submit another claim transaction."
            )
            _mark_claim_failure(
                queue_item_id,
                stage="circle_pending",
                message=message,
                terminal=False,
            )
            raise WorkerClaimPendingError(message)
        sleep_fn(max(interval, 0))
        current = circle_client.get_transaction(current.transaction_id)
        _update_circle_snapshot(queue_item_id, current)


def _wait_for_receipt(
    queue_item_id: str,
    *,
    arc_client: ArcClient,
    tx_hash: str,
    sleep_fn: Callable[[float], None],
) -> Any:
    timeout = int(getattr(settings, "WORKER_ARC_RECEIPT_TIMEOUT_SECONDS", 120))
    interval = float(getattr(settings, "WORKER_CLAIM_POLL_INTERVAL_SECONDS", 3))
    deadline = time.monotonic() + max(timeout, 0)
    while True:
        receipt = arc_client.transaction_receipt_or_none(tx_hash)
        if receipt is not None:
            return receipt
        if time.monotonic() >= deadline:
            message = (
                "Circle completed the claim, but the Arc receipt is not available yet. "
                "Reconcile this queue item; do not resubmit."
            )
            _mark_claim_failure(
                queue_item_id,
                stage="arc_receipt_pending",
                message=message,
                terminal=False,
            )
            raise WorkerClaimPendingError(message)
        sleep_fn(max(interval, 0))


def execute_worker_job_claim(
    queue_item_id: str,
    *,
    arc_client: ArcClient | None = None,
    github_guard: GitHubFreshnessGuard | None = None,
    circle_client: CircleDeveloperClaimClient | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ClaimExecutionResult:
    """Submit exactly one typed Circle claimJob transaction and verify Arc state."""

    reserved = _reserve_claim(queue_item_id)
    arc = arc_client or ArcClient()
    guard = github_guard or GitHubFreshnessGuard()

    try:
        arc.assert_chain()
        if arc.is_paused():
            raise WorkerClaimError("Veyra escrow is paused.")
        if not arc.is_agent_authorised(reserved.worker.worker_wallet_address):
            raise WorkerClaimError("Worker wallet is not authorised onchain.")
        if not arc.is_verifier_authorised(settings.VEYRA_VERIFIER_ADDRESS):
            raise WorkerClaimError("Verifier wallet is not authorised onchain.")
        _live_eligibility(reserved, arc_client=arc, github_guard=guard)
    except Exception as exc:
        _record_guard_failure(queue_item_id, exc)
        if isinstance(exc, WorkerClaimError):
            raise
        raise WorkerClaimError(_safe_error(exc)) from exc

    circle = circle_client or CircleDeveloperClaimClient()
    try:
        created = circle.create_claim(
            worker_wallet_address=reserved.worker.worker_wallet_address,
            job_id=int(reserved.job.onchain_job_id),
            idempotency_key=reserved.claim_idempotency_key,
        )
        _record_circle_submission(queue_item_id, created)
    except Exception as exc:
        message = _safe_error(exc)
        _mark_claim_failure(
            queue_item_id,
            stage="circle_submission_unknown",
            message=(
                message
                + " The submission outcome may be unknown; reconcile before any retry."
            ),
            terminal=False,
        )
        if isinstance(exc, WorkerClaimError):
            raise WorkerClaimPendingError(
                message + " Reconcile before any retry."
            ) from exc
        raise WorkerClaimPendingError(message) from exc

    completed = _wait_for_circle(
        queue_item_id,
        circle_client=circle,
        initial=created,
        sleep_fn=sleep_fn,
    )
    if not (completed.tx_hash.startswith("0x") and len(completed.tx_hash) == 66):
        message = "Circle completed the claim without a valid Arc transaction hash."
        _mark_claim_failure(
            queue_item_id,
            stage="circle_complete_missing_tx_hash",
            message=message,
            terminal=False,
        )
        raise WorkerClaimPendingError(message)

    receipt = _wait_for_receipt(
        queue_item_id,
        arc_client=arc,
        tx_hash=completed.tx_hash,
        sleep_fn=sleep_fn,
    )
    try:
        return _finalize_claim(
            queue_item_id,
            arc_client=arc,
            tx_hash=completed.tx_hash,
            receipt=receipt,
        )
    except Exception as exc:
        message = _safe_error(exc)
        _mark_claim_failure(
            queue_item_id,
            stage="arc_claim_verification",
            message=message,
            terminal=False,
        )
        if isinstance(exc, WorkerClaimError):
            raise WorkerClaimPendingError(message) from exc
        raise WorkerClaimPendingError(message) from exc


def reconcile_worker_job_claim(
    queue_item_id: str,
    *,
    arc_client: ArcClient | None = None,
    circle_client: CircleDeveloperClaimClient | None = None,
) -> ClaimExecutionResult | None:
    """Reconcile a pending claim without ever creating a new transaction."""

    item = _get_item(queue_item_id)
    if item.status == WorkerJobQueueItem.Status.CLAIMED:
        onchain = item.onchain_snapshot or {}
        return ClaimExecutionResult(
            queue_item_id=str(item.id),
            worker_slug=item.worker.slug,
            job_id=int(item.job.onchain_job_id),
            status=item.status,
            circle_transaction_id=str(item.claim_circle_transaction_id or ""),
            circle_state=item.claim_circle_state,
            arc_transaction_hash=str(item.claim_arc_transaction_hash or ""),
            receipt_block_number=item.claim_receipt_block_number,
            provider_address=str(onchain.get("provider") or item.worker.worker_wallet_address),
            claim_deadline=int(onchain.get("claim_deadline") or item.job.claim_deadline or 0),
        )
    if item.status != WorkerJobQueueItem.Status.CLAIM_PENDING:
        raise WorkerClaimError(
            f"Only CLAIM_PENDING items can be reconciled; status is {item.status}."
        )

    arc = arc_client or ArcClient()
    arc.assert_chain()
    onchain = arc.get_job(item.job.onchain_job_id)
    worker_address = item.worker.worker_wallet_address.lower()
    if onchain.get("status") == "CLAIMED":
        if str(onchain.get("provider") or "").lower() != worker_address:
            message = "Arc shows the job was claimed by a different provider."
            _mark_claim_failure(
                queue_item_id,
                stage="claimed_by_another_provider",
                message=message,
                terminal=True,
            )
            raise WorkerClaimError(message)
        tx_hash = str(item.claim_arc_transaction_hash or "")
        if not tx_hash:
            message = (
                "Arc shows the worker as provider, but the claim transaction hash is not "
                "stored yet. Wait for Circle reconciliation; no new claim was submitted."
            )
            _mark_claim_failure(
                queue_item_id,
                stage="claim_hash_pending",
                message=message,
                terminal=False,
            )
            raise WorkerClaimPendingError(message)
        receipt = arc.transaction_receipt_or_none(tx_hash)
        if receipt is None:
            raise WorkerClaimPendingError("Arc claim receipt is still pending.")
        return _finalize_claim(
            queue_item_id,
            arc_client=arc,
            tx_hash=tx_hash,
            receipt=receipt,
        )

    if onchain.get("status") != "FUNDED":
        message = f"Arc reports job status {onchain.get('status') or 'UNKNOWN'}."
        _mark_claim_failure(
            queue_item_id,
            stage="onchain_not_claimable",
            message=message,
            terminal=True,
        )
        raise WorkerClaimError(message)

    if not item.claim_circle_transaction_id:
        message = (
            "No Circle transaction ID is stored and Arc still reports FUNDED. The prior "
            "submission outcome is uncertain; no automatic resubmission was performed."
        )
        _mark_claim_failure(
            queue_item_id,
            stage="submission_outcome_unknown",
            message=message,
            terminal=False,
        )
        raise WorkerClaimPendingError(message)

    circle = circle_client or CircleDeveloperClaimClient()
    snapshot = circle.get_transaction(item.claim_circle_transaction_id)
    _update_circle_snapshot(queue_item_id, snapshot)
    if snapshot.state in CIRCLE_TERMINAL_FAILURE_STATES:
        message = snapshot.failure_message or f"Circle ended in state {snapshot.state}."
        _mark_claim_failure(
            queue_item_id,
            stage="circle_transaction",
            message=message,
            terminal=True,
        )
        raise WorkerClaimError(message)
    if snapshot.state != "COMPLETE":
        raise WorkerClaimPendingError(
            f"Circle claim transaction is still {snapshot.state}; no new transaction was submitted."
        )
    if not (snapshot.tx_hash.startswith("0x") and len(snapshot.tx_hash) == 66):
        raise WorkerClaimPendingError(
            "Circle completed the claim but has not exposed a valid Arc transaction hash."
        )
    receipt = arc.transaction_receipt_or_none(snapshot.tx_hash)
    if receipt is None:
        raise WorkerClaimPendingError("Arc claim receipt is still pending.")
    return _finalize_claim(
        queue_item_id,
        arc_client=arc,
        tx_hash=snapshot.tx_hash,
        receipt=receipt,
    )
