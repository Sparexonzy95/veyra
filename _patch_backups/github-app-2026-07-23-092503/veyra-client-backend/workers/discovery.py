from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from blockchain.client import ArcClient
from jobs.models import VeyraJob
from workers.github_freshness import (
    GitHubFreshnessError,
    GitHubFreshnessGuard,
)
from workers.models import WorkerAgent, WorkerJobQueueItem

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

DISCOVERY_MUTABLE_STATUSES = {
    WorkerJobQueueItem.Status.DISCOVERED,
    WorkerJobQueueItem.Status.QUEUED,
    WorkerJobQueueItem.Status.DEFERRED,
    WorkerJobQueueItem.Status.INELIGIBLE,
    WorkerJobQueueItem.Status.STALE,
    WorkerJobQueueItem.Status.BLOCKED,
    WorkerJobQueueItem.Status.DUPLICATE,
    WorkerJobQueueItem.Status.FAILED,
}

CAPACITY_STATUSES = {
    WorkerJobQueueItem.Status.QUEUED,
    WorkerJobQueueItem.Status.CLAIM_PENDING,
    WorkerJobQueueItem.Status.CLAIMED,
    WorkerJobQueueItem.Status.EXECUTING,
    WorkerJobQueueItem.Status.SUBMISSION_PENDING,
    WorkerJobQueueItem.Status.SUBMITTED,
}

SKILL_CATEGORIES = {
    "language",
    "runtime",
    "framework",
    "testing",
    "database",
    "infrastructure",
}

SKILL_ALIASES = {
    "next": "nextjs",
    "nextjs": "nextjs",
    "node": "nodejs",
    "nodejs": "nodejs",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "tailwind": "tailwindcss",
    "tailwindcss": "tailwindcss",
    "ts": "typescript",
    "typescript": "typescript",
    "js": "javascript",
    "javascript": "javascript",
    "py": "python",
    "python": "python",
}


class WorkerDiscoveryError(RuntimeError):
    """Raised when discovery cannot be enabled or reconciled safely."""


@dataclass(frozen=True)
class EligibilityResult:
    passed: bool
    code: str
    detail: str
    required_skills: tuple[str, ...]
    matched_skills: tuple[str, ...]
    priority_score: int
    onchain_status: str
    onchain_snapshot: dict[str, Any]
    github_freshness_code: str
    github_snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["required_skills"] = list(self.required_skills)
        value["matched_skills"] = list(self.matched_skills)
        return value


@dataclass(frozen=True)
class QueueResult:
    queue_item_id: str
    job_id: int
    status: str
    eligibility_code: str
    eligibility_detail: str
    priority_score: int
    required_skills: tuple[str, ...]
    matched_skills: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryRunResult:
    worker_id: str
    worker_slug: str
    discovery_enabled: bool
    scanned: int
    queued: int
    deferred: int
    ineligible: int
    stale: int
    blocked: int
    duplicate: int
    results: tuple[QueueResult, ...]
    checked_at: str


def _safe_error(exc: Exception) -> str:
    text = str(exc or "").strip() or exc.__class__.__name__
    return text if len(text) <= 500 else text[:500] + "…"


def _normalise_skill(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    return SKILL_ALIASES.get(compact, compact)


def _required_skills(job: VeyraJob) -> tuple[str, ...]:
    snapshot = getattr(job, "draft", None)
    snapshot = getattr(snapshot, "funding_snapshot", None)
    repository = snapshot.repository_commitment if snapshot else {}
    stack = repository.get("repositoryStack", []) if isinstance(repository, dict) else []

    result: list[str] = []
    seen: set[str] = set()
    for item in stack if isinstance(stack, list) else []:
        if isinstance(item, str):
            name = item
            category = ""
        elif isinstance(item, dict):
            name = str(item.get("name") or "")
            category = str(item.get("category") or "").casefold()
        else:
            continue
        normalised = _normalise_skill(name)
        if not normalised:
            continue
        if category and category not in SKILL_CATEGORIES:
            continue
        if normalised not in seen:
            seen.add(normalised)
            result.append(name.strip() or normalised)
    return tuple(result)


def _matched_skills(worker: WorkerAgent, required: tuple[str, ...]) -> tuple[str, ...]:
    worker_skills = {_normalise_skill(skill) for skill in worker.skills}
    return tuple(skill for skill in required if _normalise_skill(skill) in worker_skills)


def _public_onchain_snapshot(onchain: dict[str, Any]) -> dict[str, Any]:
    allowed = {
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
    return {key: onchain[key] for key in allowed if key in onchain}


def _minimum_budget_atomic(worker: WorkerAgent) -> int:
    scale = Decimal(10) ** int(settings.ARC_USDC_DECIMALS)
    return int(worker.minimum_budget_usdc * scale)


def _priority_score(
    *,
    worker: WorkerAgent,
    onchain: dict[str, Any],
    matched: tuple[str, ...],
    required: tuple[str, ...],
) -> int:
    invited = onchain.get("invited_provider", ZERO_ADDRESS) == worker.worker_wallet_address.lower()
    budget_atomic = int(onchain.get("budget") or 0)
    whole_usdc = budget_atomic // (10 ** int(settings.ARC_USDC_DECIMALS))
    skill_component = 500 if not required else int(500 * len(matched) / len(required))
    return (100_000 if invited else 0) + skill_component + min(whole_usdc, 10_000)


def _fail(
    code: str,
    detail: str,
    *,
    required: tuple[str, ...] = (),
    matched: tuple[str, ...] = (),
    onchain: dict[str, Any] | None = None,
    github_freshness_code: str = "",
    github_snapshot: dict[str, Any] | None = None,
) -> EligibilityResult:
    snapshot = _public_onchain_snapshot(onchain or {})
    return EligibilityResult(
        passed=False,
        code=code,
        detail=detail,
        required_skills=required,
        matched_skills=matched,
        priority_score=0,
        onchain_status=str((onchain or {}).get("status") or "UNKNOWN"),
        onchain_snapshot=snapshot,
        github_freshness_code=github_freshness_code,
        github_snapshot=dict(github_snapshot or {}),
    )


def _duplicate_open_job(job: VeyraJob) -> VeyraJob | None:
    """Return the canonical lower-ID open job when this task is duplicated."""

    draft = job.draft
    canonical = (
        VeyraJob.objects.select_related("draft")
        .filter(
            status="FUNDED",
            client_status="OPEN",
            draft__repository_owner__iexact=draft.repository_owner,
            draft__repository_name__iexact=draft.repository_name,
            draft__issue_number=draft.issue_number,
        )
        .order_by("onchain_job_id", "created_at")
        .first()
    )
    if canonical and canonical.pk != job.pk:
        return canonical
    return None


def evaluate_job(
    worker: WorkerAgent,
    job: VeyraJob,
    *,
    arc_client: ArcClient | None = None,
    now_timestamp: int | None = None,
    github_guard: GitHubFreshnessGuard | None = None,
    require_discovery_enabled: bool = True,
) -> EligibilityResult:
    """Evaluate one projected Veyra job against authoritative Arc state."""

    worker.refresh_from_db()
    job = VeyraJob.objects.select_related("draft", "draft__funding_snapshot").get(pk=job.pk)

    if worker.status != WorkerAgent.Status.ACTIVE:
        return _fail("WORKER_NOT_ACTIVE", "The worker is not ACTIVE.")
    if require_discovery_enabled and not worker.discovery_enabled:
        return _fail("DISCOVERY_DISABLED", "Discovery is disabled for this worker.")
    if not worker.test_assignment_passed:
        return _fail("TEST_NOT_PASSED", "The controlled worker test has not passed.")
    if not worker.contract_authorised:
        return _fail("AGENT_NOT_AUTHORISED", "The worker is not authorised by the escrow contract.")
    if job.status != "FUNDED" or job.client_status != "OPEN":
        return _fail("LOCAL_JOB_NOT_OPEN", "The local job projection is not open.")

    client = arc_client or ArcClient()
    try:
        client.assert_chain()
        onchain = client.get_job(job.onchain_job_id)
    except Exception as exc:
        return _fail("ARC_READ_FAILED", f"Arc job state could not be read: {_safe_error(exc)}")

    required = _required_skills(job)
    matched = _matched_skills(worker, required)

    if onchain.get("status") != "FUNDED":
        return _fail(
            "ONCHAIN_JOB_NOT_OPEN",
            f"Arc reports job status {onchain.get('status') or 'UNKNOWN'}.",
            required=required,
            matched=matched,
            onchain=onchain,
        )
    if onchain.get("provider") != ZERO_ADDRESS:
        return _fail(
            "ALREADY_CLAIMED",
            "The Arc job already has a provider.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    worker_address = worker.worker_wallet_address.lower()
    invited = onchain.get("invited_provider", ZERO_ADDRESS)
    if invited not in {ZERO_ADDRESS, worker_address}:
        return _fail(
            "INVITED_TO_ANOTHER_AGENT",
            "The job is reserved for a different provider wallet.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    snapshot = job.draft.funding_snapshot
    integrity_pairs = {
        "client": (onchain.get("client"), job.client_address.lower()),
        "verifier": (onchain.get("verifier"), job.verifier_address.lower()),
        "invited_provider": (
            onchain.get("invited_provider"),
            job.invited_provider_address.lower(),
        ),
        "budget": (int(onchain.get("budget") or 0), int(job.budget_atomic)),
        "expires_at": (int(onchain.get("expires_at") or 0), int(job.expires_at)),
        "repository_hash": (onchain.get("repository_hash"), job.repository_hash),
        "task_hash": (onchain.get("task_hash"), job.task_hash),
        "policy_hash": (onchain.get("policy_hash"), job.policy_hash),
    }
    mismatched = [name for name, pair in integrity_pairs.items() if pair[0] != pair[1]]
    if mismatched:
        return _fail(
            "COMMITMENT_MISMATCH",
            "Arc and Django commitments differ: " + ", ".join(mismatched),
            required=required,
            matched=matched,
            onchain=onchain,
        )

    if snapshot.repository_hash != job.repository_hash or snapshot.task_hash != job.task_hash or snapshot.policy_hash != job.policy_hash:
        return _fail(
            "SNAPSHOT_MISMATCH",
            "The locked funding snapshot does not match the projected job.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    repository = snapshot.repository_commitment
    policy = snapshot.policy_commitment
    if repository.get("host") != "github.com":
        return _fail(
            "UNSUPPORTED_REPOSITORY_HOST",
            "The MVP worker supports GitHub repositories only.",
            required=required,
            matched=matched,
            onchain=onchain,
        )
    if policy.get("deliveryType", "PULL_REQUEST") != "PULL_REQUEST":
        return _fail(
            "UNSUPPORTED_DELIVERY_TYPE",
            "The MVP worker supports pull-request delivery only.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    if int(onchain.get("budget") or 0) < _minimum_budget_atomic(worker):
        return _fail(
            "BUDGET_BELOW_MINIMUM",
            "The job budget is below the worker minimum.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    now_value = int(now_timestamp if now_timestamp is not None else timezone.now().timestamp())
    minimum_remaining = int(
        getattr(settings, "WORKER_DISCOVERY_MIN_REMAINING_SECONDS", 900)
    )
    if int(onchain.get("expires_at") or 0) - now_value < minimum_remaining:
        return _fail(
            "INSUFFICIENT_TIME_REMAINING",
            f"The job has less than {minimum_remaining} seconds remaining.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    require_match = bool(
        getattr(settings, "WORKER_DISCOVERY_REQUIRE_SKILL_MATCH", True)
    )
    if require_match and required and not matched:
        return _fail(
            "SKILL_MISMATCH",
            "The repository stack does not match the worker's configured skills.",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    duplicate = _duplicate_open_job(job)
    if duplicate is not None:
        return _fail(
            "DUPLICATE_REPOSITORY_ISSUE",
            (
                "Another funded OPEN Arc job already targets this repository issue "
                f"(canonical Arc job #{duplicate.onchain_job_id})."
            ),
            required=required,
            matched=matched,
            onchain=onchain,
        )

    guard = github_guard or GitHubFreshnessGuard()
    try:
        github_result = guard.check(worker, job)
    except GitHubFreshnessError as exc:
        return _fail(
            "GITHUB_READ_FAILED",
            f"GitHub task freshness could not be established: {_safe_error(exc)}",
            required=required,
            matched=matched,
            onchain=onchain,
        )

    github_snapshot = github_result.as_dict()
    if not github_result.passed:
        return _fail(
            github_result.code,
            github_result.detail,
            required=required,
            matched=matched,
            onchain=onchain,
            github_freshness_code=github_result.code,
            github_snapshot=github_snapshot,
        )

    priority = _priority_score(
        worker=worker,
        onchain=onchain,
        matched=matched,
        required=required,
    )
    return EligibilityResult(
        passed=True,
        code="ELIGIBLE",
        detail="The job is open, funded, integrity-matched, and compatible with the worker.",
        required_skills=required,
        matched_skills=matched,
        priority_score=priority,
        onchain_status=str(onchain.get("status") or "UNKNOWN"),
        onchain_snapshot=_public_onchain_snapshot(onchain),
        github_freshness_code=github_result.code,
        github_snapshot=github_snapshot,
    )


def _capacity_used(worker: WorkerAgent, *, exclude_item_id=None) -> int:
    query = WorkerJobQueueItem.objects.filter(
        worker=worker,
        status__in=CAPACITY_STATUSES,
    )
    if exclude_item_id:
        query = query.exclude(pk=exclude_item_id)
    return query.count()


@transaction.atomic
def discover_job(
    worker: WorkerAgent,
    job: VeyraJob,
    *,
    source: str = WorkerJobQueueItem.Source.RECONCILIATION,
    arc_client: ArcClient | None = None,
    github_guard: GitHubFreshnessGuard | None = None,
) -> QueueResult:
    """Create or refresh one idempotent queue item."""

    item, _ = WorkerJobQueueItem.objects.select_for_update().get_or_create(
        worker=worker,
        job=job,
        defaults={"source": source},
    )

    if item.status not in DISCOVERY_MUTABLE_STATUSES:
        return QueueResult(
            queue_item_id=str(item.id),
            job_id=job.onchain_job_id,
            status=item.status,
            eligibility_code=item.eligibility_code,
            eligibility_detail=item.eligibility_detail,
            priority_score=item.priority_score,
            required_skills=tuple(item.required_skills),
            matched_skills=tuple(item.matched_skills),
        )

    result = evaluate_job(
        worker,
        job,
        arc_client=arc_client,
        github_guard=github_guard,
    )
    now = timezone.now()

    item.source = source
    item.eligibility_passed = result.passed
    item.eligibility_code = result.code
    item.eligibility_detail = result.detail
    item.priority_score = result.priority_score
    item.required_skills = list(result.required_skills)
    item.matched_skills = list(result.matched_skills)
    item.onchain_status = result.onchain_status
    item.onchain_snapshot = result.onchain_snapshot
    item.github_freshness_code = result.github_freshness_code
    item.github_snapshot = result.github_snapshot
    checked_at = result.github_snapshot.get("checked_at")
    item.github_last_checked_at = now if checked_at else None
    item.last_checked_at = now

    if result.passed:
        capacity_used = _capacity_used(worker, exclude_item_id=item.id)
        if capacity_used < worker.maximum_active_jobs:
            item.status = WorkerJobQueueItem.Status.QUEUED
            item.queued_at = item.queued_at or now
        else:
            item.status = WorkerJobQueueItem.Status.DEFERRED
            item.eligibility_detail = (
                f"Eligible, but worker capacity is full "
                f"({capacity_used}/{worker.maximum_active_jobs})."
            )
            item.queued_at = None
    elif result.code == "DUPLICATE_REPOSITORY_ISSUE":
        item.status = WorkerJobQueueItem.Status.DUPLICATE
        item.queued_at = None
    elif result.code in {
        "GITHUB_WORKER_PR_OPEN",
        "GITHUB_WORKER_PR_MERGED",
        "GITHUB_WORKER_BRANCH_EXISTS",
        "GITHUB_FORK_COLLISION",
    }:
        item.status = WorkerJobQueueItem.Status.BLOCKED
        item.queued_at = None
    elif result.code in {
        "LOCAL_JOB_NOT_OPEN",
        "ONCHAIN_JOB_NOT_OPEN",
        "ALREADY_CLAIMED",
        "GITHUB_ISSUE_NOT_FOUND",
        "GITHUB_ISSUE_CLOSED",
        "GITHUB_TARGET_IS_PULL_REQUEST",
    }:
        item.status = WorkerJobQueueItem.Status.STALE
        item.queued_at = None
    elif result.code in {
        "ARC_READ_FAILED",
        "DISCOVERY_DISABLED",
        "GITHUB_READ_FAILED",
    }:
        item.status = WorkerJobQueueItem.Status.DEFERRED
        item.queued_at = None
    else:
        item.status = WorkerJobQueueItem.Status.INELIGIBLE
        item.queued_at = None

    item.save()

    return QueueResult(
        queue_item_id=str(item.id),
        job_id=job.onchain_job_id,
        status=item.status,
        eligibility_code=item.eligibility_code,
        eligibility_detail=item.eligibility_detail,
        priority_score=item.priority_score,
        required_skills=tuple(item.required_skills),
        matched_skills=tuple(item.matched_skills),
    )


def reconcile_worker_jobs(
    worker: WorkerAgent,
    *,
    arc_client: ArcClient | None = None,
    github_guard: GitHubFreshnessGuard | None = None,
    source: str = WorkerJobQueueItem.Source.RECONCILIATION,
) -> DiscoveryRunResult:
    worker.refresh_from_db()
    if worker.status != WorkerAgent.Status.ACTIVE:
        raise WorkerDiscoveryError("Worker must be ACTIVE before discovery can run.")
    if not worker.discovery_enabled:
        raise WorkerDiscoveryError("Worker discovery is disabled.")

    client = arc_client or ArcClient()
    try:
        client.assert_chain()
        if client.is_paused():
            raise WorkerDiscoveryError("Veyra escrow is paused.")
        if not client.is_agent_authorised(worker.worker_wallet_address):
            raise WorkerDiscoveryError("Worker wallet is not authorised onchain.")
        if not client.is_verifier_authorised(settings.VEYRA_VERIFIER_ADDRESS):
            raise WorkerDiscoveryError("Verifier wallet is not authorised onchain.")
    except WorkerDiscoveryError:
        raise
    except Exception as exc:
        raise WorkerDiscoveryError(
            f"Arc discovery preflight failed: {_safe_error(exc)}"
        ) from exc

    jobs = list(
        VeyraJob.objects.select_related("draft", "draft__funding_snapshot")
        .filter(status="FUNDED", client_status="OPEN")
        .order_by("expires_at", "created_at")
    )

    guard = github_guard or GitHubFreshnessGuard()
    results = tuple(
        discover_job(
            worker,
            job,
            source=source,
            arc_client=client,
            github_guard=guard,
        )
        for job in jobs
    )
    counts = {
        status: sum(1 for result in results if result.status == status)
        for status in WorkerJobQueueItem.Status.values
    }
    return DiscoveryRunResult(
        worker_id=str(worker.id),
        worker_slug=worker.slug,
        discovery_enabled=worker.discovery_enabled,
        scanned=len(results),
        queued=counts.get(WorkerJobQueueItem.Status.QUEUED, 0),
        deferred=counts.get(WorkerJobQueueItem.Status.DEFERRED, 0),
        ineligible=counts.get(WorkerJobQueueItem.Status.INELIGIBLE, 0),
        stale=counts.get(WorkerJobQueueItem.Status.STALE, 0),
        blocked=counts.get(WorkerJobQueueItem.Status.BLOCKED, 0),
        duplicate=counts.get(WorkerJobQueueItem.Status.DUPLICATE, 0),
        results=results,
        checked_at=timezone.now().isoformat(),
    )


def enable_worker_discovery(
    worker: WorkerAgent,
    *,
    arc_client: ArcClient | None = None,
) -> WorkerAgent:
    worker.refresh_from_db()
    blockers = []
    if worker.status != WorkerAgent.Status.ACTIVE:
        blockers.append("status is not ACTIVE")
    if not worker.test_assignment_passed:
        blockers.append("controlled test assignment has not passed")
    if not worker.engine_connected:
        blockers.append("coding engine is not connected")
    if not worker.github_connected:
        blockers.append("GitHub bot is not connected")
    if not worker.worker_wallet_address:
        blockers.append("worker wallet is missing")
    if not worker.contract_authorised:
        blockers.append("stored contract authorisation is false")
    if blockers:
        raise WorkerDiscoveryError("Discovery cannot be enabled: " + "; ".join(blockers))

    client = arc_client or ArcClient()
    try:
        client.assert_chain()
        if client.is_paused():
            raise WorkerDiscoveryError("Discovery cannot be enabled while escrow is paused.")
        if not client.is_agent_authorised(worker.worker_wallet_address):
            raise WorkerDiscoveryError("Worker wallet is not authorised onchain.")
        if not client.is_verifier_authorised(settings.VEYRA_VERIFIER_ADDRESS):
            raise WorkerDiscoveryError("Verifier wallet is not authorised onchain.")
    except WorkerDiscoveryError:
        raise
    except Exception as exc:
        raise WorkerDiscoveryError(
            f"Discovery enablement preflight failed: {_safe_error(exc)}"
        ) from exc

    worker.discovery_enabled = True
    worker.save(update_fields=["discovery_enabled", "updated_at"])
    return worker


def disable_worker_discovery(worker: WorkerAgent) -> WorkerAgent:
    worker.refresh_from_db()
    worker.discovery_enabled = False
    worker.save(update_fields=["discovery_enabled", "updated_at"])
    return worker


def enqueue_job_created_fast_path(job_id: int) -> tuple[QueueResult, ...]:
    """Queue a freshly projected JobCreated event for every enabled worker.

    This callback is deliberately idempotent. It performs no claim transaction.
    """

    job = VeyraJob.objects.select_related("draft", "draft__funding_snapshot").filter(
        onchain_job_id=job_id
    ).first()
    if not job:
        return ()

    results = []
    for worker in WorkerAgent.objects.filter(
        status=WorkerAgent.Status.ACTIVE,
        discovery_enabled=True,
    ):
        try:
            results.append(
                discover_job(
                    worker,
                    job,
                    source=WorkerJobQueueItem.Source.FAST_PATH,
                )
            )
        except Exception:
            # The periodic reconciliation command is the authoritative fallback.
            continue
    return tuple(results)
