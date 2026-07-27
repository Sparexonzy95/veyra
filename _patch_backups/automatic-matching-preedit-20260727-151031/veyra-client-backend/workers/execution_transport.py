from __future__ import annotations

import base64
from fnmatch import fnmatchcase
import hashlib
import json
import re
import uuid
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from common.utils import canonical_json
from jobs.github_app import token_for_repository
from workers.github_app_execution import GitHubAppExecutionClient, GitHubExecutionError
from workers.models import (
    HostedAgentConnection,
    WorkerAgent,
    WorkerJobAssignment,
    WorkerJobQueueItem,
)


LEASE_SALT = "veyra.execution-lease.v1"


class ExecutionTransportError(RuntimeError):
    pass


def _safe_text(value: Any, *, limit: int = 2000) -> str:
    text = str(value or "").strip()
    for setting_name in (
        "CIRCLE_API_KEY",
        "CIRCLE_ENTITY_SECRET",
        "GITHUB_APP_PRIVATE_KEY",
        "VEYRA_CONTRACT_OWNER_PRIVATE_KEY",
        "VEYRA_VERIFIER_PRIVATE_KEY",
    ):
        secret = str(getattr(settings, setting_name, "") or "").strip()
        if secret:
            text = text.replace(secret, "[REDACTED]")
            text = text.replace(secret.removeprefix("0x"), "[REDACTED]")
    return text[:limit]


def _b64url_decode(value: str) -> bytes:
    text = str(value or "").strip()
    padding = "=" * ((4 - len(text) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except Exception as exc:
        raise ExecutionTransportError("The runtime signature encoding is invalid.") from exc


def _lease_seconds(worker) -> int:
    configured = int(getattr(settings, "VEYRA_JOB_LEASE_GRACE_SECONDS", 120))
    return max(600, int(worker.maximum_execution_minutes) * 60 + configured)


def _branch_name(assignment: WorkerJobAssignment) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", assignment.worker.slug.casefold()).strip("-")[:32]
    return f"veyra/job-{assignment.job.onchain_job_id}-{slug}-{assignment.assignment_attempt}"


def _lease_token(assignment: WorkerJobAssignment) -> str:
    return signing.dumps(
        {
            "assignment_id": str(assignment.id),
            "worker_id": str(assignment.worker_id),
            "queue_item_id": str(assignment.queue_item_id),
            "lease_id": str(assignment.execution_lease_id),
            "attempt": int(assignment.assignment_attempt),
        },
        salt=LEASE_SALT,
        compress=True,
    )


def _verify_lease(assignment: WorkerJobAssignment, token: str) -> None:
    max_age = _lease_seconds(assignment.worker) + 120
    try:
        payload = signing.loads(token, salt=LEASE_SALT, max_age=max_age)
    except signing.BadSignature as exc:
        raise ExecutionTransportError("The execution lease is invalid or expired.") from exc
    expected = {
        "assignment_id": str(assignment.id),
        "worker_id": str(assignment.worker_id),
        "queue_item_id": str(assignment.queue_item_id),
        "lease_id": str(assignment.execution_lease_id),
        "attempt": int(assignment.assignment_attempt),
    }
    if any(str(payload.get(key)) != str(value) for key, value in expected.items()):
        raise ExecutionTransportError("The execution lease does not match this job.")
    if not assignment.lease_expires_at or assignment.lease_expires_at < timezone.now():
        raise ExecutionTransportError("The execution lease has expired.")


def _normalised_paths(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        path = str(value or "").replace("\\", "/").strip().lstrip("/")
        if not path or ".." in path.split("/"):
            continue
        key = path.casefold()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _required_commands(assignment: WorkerJobAssignment) -> list[str]:
    policy = assignment.job.draft.funding_snapshot.policy_commitment or {}
    values = policy.get("requiredCommands") if isinstance(policy, dict) else []
    commands = [str(item).strip() for item in values if isinstance(item, str) and item.strip()]
    if commands:
        return commands[:4]
    skills = {str(value).casefold() for value in assignment.worker.skills}
    if "python" in skills or "pytest" in skills:
        return ["python -m pytest -q"]
    return []


def _task_payload(assignment: WorkerJobAssignment) -> dict[str, Any]:
    snapshot = assignment.job.draft.funding_snapshot
    repository = snapshot.repository_commitment or {}
    task = snapshot.task_commitment or {}
    policy = snapshot.policy_commitment or {}
    draft = assignment.job.draft
    api_root = str(getattr(settings, "VEYRA_PUBLIC_API_URL", "http://127.0.0.1:8000")).rstrip("/")
    return {
        "id": str(assignment.id),
        "type": "veyra_paid_job",
        "job_id": int(assignment.job.onchain_job_id),
        "queue_item_id": str(assignment.queue_item_id),
        "assignment_attempt": int(assignment.assignment_attempt),
        "lease_id": str(assignment.execution_lease_id),
        "lease_token": _lease_token(assignment),
        "lease_expires_at": assignment.lease_expires_at.isoformat(),
        "credential_url": f"{api_root}/api/v1/agent-runtime/job/credential/",
        "submit_url": f"{api_root}/api/v1/agent-runtime/job/result/",
        "repository": {
            "owner": draft.repository_owner,
            "name": draft.repository_name,
            "full_name": f"{draft.repository_owner}/{draft.repository_name}",
            "private": bool(draft.github_repository_access.private) if draft.github_repository_access_id else False,
            "target_branch": str(repository.get("targetBranch") or draft.target_branch),
            "clone_url": f"https://github.com/{draft.repository_owner}/{draft.repository_name}.git",
        },
        "work": {
            "title": str(task.get("title") or draft.issue_title),
            "description": str(task.get("description") or draft.issue_body),
            "issue_number": int(repository.get("issueNumber") or draft.issue_number),
            "issue_url": draft.github_issue_url,
            "technical_requirements": task.get("technicalRequirements") or [],
            "acceptance_criteria": task.get("acceptanceCriteria") or [
                {"statement": item, "verificationMethod": "AUTOMATED_TEST"}
                for item in draft.acceptance_criteria
            ],
        },
        "policy": {
            "allowed_paths": _normalised_paths(policy.get("allowedPaths") or []),
            "forbidden_paths": _normalised_paths(
                [
                    *list(policy.get("forbiddenPaths") or []),
                    *list(assignment.worker.protected_paths or []),
                ]
            ),
            "allow_new_dependencies": bool(assignment.worker.allow_new_dependencies),
            "allow_database_migrations": bool(assignment.worker.allow_database_migrations),
            "maximum_execution_minutes": int(assignment.worker.maximum_execution_minutes),
            "required_commands": _required_commands(assignment),
            "maximum_repair_attempts": max(0, int(getattr(settings, "VEYRA_JOB_MAX_REPAIR_ATTEMPTS", 2))),
        },
        "delivery": {
            "branch": _branch_name(assignment),
            "pull_request_title": f"Veyra Job #{assignment.job.onchain_job_id}: {draft.issue_title}"[:240],
            "pull_request_body_prefix": (
                f"Veyra Job #{assignment.job.onchain_job_id}\n\n"
                f"Closes #{draft.issue_number}\n\n"
            ),
        },
    }


def execution_task_for_connection(connection: HostedAgentConnection) -> dict[str, Any] | None:
    if connection.worker.agent_role != WorkerAgent.AgentRole.WORKER:
        return None
    assignment = (
        WorkerJobAssignment.objects.select_related(
            "worker",
            "queue_item",
            "job__draft__funding_snapshot",
            "job__draft__github_repository_access",
        )
        .filter(
            worker=connection.worker,
            status__in=[
                WorkerJobAssignment.Status.CLAIMED,
                WorkerJobAssignment.Status.LEASED,
                WorkerJobAssignment.Status.EXECUTING,
            ],
        )
        .order_by("created_at")
        .first()
    )
    if assignment is None:
        return None
    now = timezone.now()
    claim_deadline = int(assignment.job.claim_deadline or 0)
    if claim_deadline and int(now.timestamp()) >= claim_deadline:
        message = (
            "The Arc claim deadline expired before the hosted runtime could lease "
            "the job. The job must follow the contract refund path."
        )
        with transaction.atomic():
            locked = (
                WorkerJobAssignment.objects.select_for_update(of=("self",))
                .select_related("queue_item")
                .get(pk=assignment.pk)
            )
            if locked.status in {
                WorkerJobAssignment.Status.CLAIMED,
                WorkerJobAssignment.Status.LEASED,
                WorkerJobAssignment.Status.EXECUTING,
            }:
                locked.status = WorkerJobAssignment.Status.FAILED
                locked.failure_stage = "claim_deadline_expired"
                locked.failure_message = message
                locked.save(
                    update_fields=[
                        "status",
                        "failure_stage",
                        "failure_message",
                        "updated_at",
                    ]
                )
                item = locked.queue_item
                item.status = WorkerJobQueueItem.Status.FAILED
                item.execution_failure_stage = "claim_deadline_expired"
                item.execution_failure_message = message
                item.save(
                    update_fields=[
                        "status",
                        "execution_failure_stage",
                        "execution_failure_message",
                        "updated_at",
                    ]
                )
        return None
    if assignment.lease_expires_at and assignment.lease_expires_at < now:
        return None

    if assignment.status == WorkerJobAssignment.Status.CLAIMED:
        with transaction.atomic():
            assignment = WorkerJobAssignment.objects.select_for_update(of=("self",)).select_related(
                "worker",
                "queue_item",
                "job__draft__funding_snapshot",
                "job__draft__github_repository_access",
            ).get(pk=assignment.pk)
            if assignment.status == WorkerJobAssignment.Status.CLAIMED:
                assignment.execution_lease_id = uuid.uuid4()
                assignment.leased_at = now
                assignment.lease_expires_at = now + timedelta(seconds=_lease_seconds(assignment.worker))
                assignment.runtime_last_seen_at = now
                assignment.status = WorkerJobAssignment.Status.LEASED
                assignment.save(
                    update_fields=[
                        "execution_lease_id",
                        "leased_at",
                        "lease_expires_at",
                        "runtime_last_seen_at",
                        "status",
                        "updated_at",
                    ]
                )
                item = assignment.queue_item
                item.status = WorkerJobQueueItem.Status.LEASED
                item.execution_branch_name = _branch_name(assignment)
                item.execution_workspace_name = f"job-{assignment.job.onchain_job_id}-{assignment.id.hex[:8]}"
                item.execution_started_at = now
                item.save(
                    update_fields=[
                        "status",
                        "execution_branch_name",
                        "execution_workspace_name",
                        "execution_started_at",
                        "updated_at",
                    ]
                )
    else:
        assignment.runtime_last_seen_at = now
        if assignment.status == WorkerJobAssignment.Status.LEASED:
            assignment.status = WorkerJobAssignment.Status.EXECUTING
            if assignment.execution_started_at is None:
                assignment.execution_started_at = now
        assignment.save(
            update_fields=[
                "runtime_last_seen_at",
                "status",
                "execution_started_at",
                "updated_at",
            ]
        )
        if assignment.queue_item.status == WorkerJobQueueItem.Status.LEASED:
            assignment.queue_item.status = WorkerJobQueueItem.Status.EXECUTING
            assignment.queue_item.save(update_fields=["status", "updated_at"])
    return _task_payload(assignment)


def repository_credential_for_connection(
    connection: HostedAgentConnection,
    *,
    assignment_id: str,
    lease_token: str,
) -> dict[str, Any]:
    try:
        assignment = WorkerJobAssignment.objects.select_related(
            "worker", "job__draft__github_repository_access__installation"
        ).get(pk=assignment_id, worker=connection.worker)
    except (WorkerJobAssignment.DoesNotExist, ValueError) as exc:
        raise ExecutionTransportError("The execution assignment was not found.") from exc
    if assignment.status not in {
        WorkerJobAssignment.Status.LEASED,
        WorkerJobAssignment.Status.EXECUTING,
    }:
        raise ExecutionTransportError("This assignment is not leased for execution.")
    _verify_lease(assignment, lease_token)
    access = assignment.job.draft.github_repository_access
    if not access:
        raise ExecutionTransportError("The funded job has no GitHub App repository access.")
    try:
        credential = token_for_repository(access)
    except Exception as exc:
        raise ExecutionTransportError(f"GitHub App credential creation failed: {_safe_text(exc)}") from exc
    return {
        "token": credential.token,
        "expires_at": credential.expires_at,
        "repository": access.full_name,
        "clone_url": f"https://github.com/{access.full_name}.git",
        "permissions": {
            "contents": "write",
            "pull_requests": "write",
            "checks": "read",
        },
    }


def _verify_runtime_signature(
    connection: HostedAgentConnection,
    *,
    assignment: WorkerJobAssignment,
    evidence_hash: str,
    signature: str,
) -> None:
    message = (
        f"veyra-job-result-v1:{assignment.id}:{assignment.execution_lease_id}:{evidence_hash}"
    ).encode("utf-8")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(connection.public_key))
        public_key.verify(_b64url_decode(signature), message)
    except (ValueError, InvalidSignature) as exc:
        raise ExecutionTransportError("The runtime execution signature is invalid.") from exc


def _path_matches_policy_rule(path: str, rule: str) -> bool:
    clean_path = path.replace("\\", "/").casefold().strip("/")
    clean_rule = rule.replace("\\", "/").casefold().strip("/")
    if not clean_path or not clean_rule:
        return False
    if clean_rule.endswith("/**"):
        prefix = clean_rule[:-3].rstrip("/")
        return bool(prefix) and (clean_path == prefix or clean_path.startswith(prefix + "/"))
    if any(marker in clean_rule for marker in ("*", "?", "[")):
        return fnmatchcase(clean_path, clean_rule)
    return clean_path == clean_rule or clean_path.startswith(clean_rule + "/")


def _validate_paths(assignment: WorkerJobAssignment, changed_files: list[str]) -> None:
    policy = assignment.job.draft.funding_snapshot.policy_commitment or {}
    forbidden = _normalised_paths(
        [*list(policy.get("forbiddenPaths") or []), *list(assignment.worker.protected_paths or [])]
    )
    allowed = _normalised_paths(policy.get("allowedPaths") or [])
    always_forbidden = [".env", ".git", ".github/workflows"]
    for path in changed_files:
        basename = path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if basename == ".env" or basename.startswith(".env."):
            raise ExecutionTransportError(f"The runtime changed protected environment path: {path}")
        if any(_path_matches_policy_rule(path, value) for value in [*forbidden, *always_forbidden]):
            raise ExecutionTransportError(f"The runtime changed protected path: {path}")
        if allowed and not any(_path_matches_policy_rule(path, value) for value in allowed):
            raise ExecutionTransportError(f"The runtime changed a path outside the funded policy: {path}")


def submit_execution_result(
    *,
    connection: HostedAgentConnection,
    payload: dict[str, Any],
) -> WorkerJobAssignment:
    assignment_id = str(payload.get("assignment_id") or "").strip()
    lease_token = str(payload.get("lease_token") or "").strip()
    evidence = payload.get("evidence")
    evidence_hash = str(payload.get("evidence_hash") or "").strip().lower()
    signature = str(payload.get("signature") or "").strip()
    if not assignment_id or not lease_token or not isinstance(evidence, dict):
        raise ExecutionTransportError("The execution result is incomplete.")
    try:
        assignment = WorkerJobAssignment.objects.select_related(
            "worker",
            "queue_item",
            "job__draft__funding_snapshot",
            "job__draft__github_repository_access__installation",
        ).get(pk=assignment_id, worker=connection.worker)
    except (WorkerJobAssignment.DoesNotExist, ValueError) as exc:
        raise ExecutionTransportError("The execution assignment was not found.") from exc
    if assignment.status not in {
        WorkerJobAssignment.Status.LEASED,
        WorkerJobAssignment.Status.EXECUTING,
    }:
        if assignment.status in {
            WorkerJobAssignment.Status.RESULT_RECEIVED,
            WorkerJobAssignment.Status.SUBMITTING,
            WorkerJobAssignment.Status.SUBMITTED,
            WorkerJobAssignment.Status.VERIFYING,
            WorkerJobAssignment.Status.SETTLING,
            WorkerJobAssignment.Status.COMPLETED,
        }:
            return assignment
        if assignment.status == WorkerJobAssignment.Status.FAILED and assignment.evidence_hash == evidence_hash:
            return assignment
        raise ExecutionTransportError("This assignment is not accepting an execution result.")
    _verify_lease(assignment, lease_token)

    calculated = "0x" + hashlib.sha256(canonical_json(evidence).encode("utf-8")).hexdigest()
    if evidence_hash != calculated:
        raise ExecutionTransportError("The execution evidence hash does not match the payload.")
    _verify_runtime_signature(
        connection,
        assignment=assignment,
        evidence_hash=evidence_hash,
        signature=signature,
    )

    if str(evidence.get("assignment_id") or "") != str(assignment.id):
        raise ExecutionTransportError("The evidence belongs to a different assignment.")
    if str(evidence.get("lease_id") or "") != str(assignment.execution_lease_id):
        raise ExecutionTransportError("The evidence belongs to a different execution lease.")
    if int(evidence.get("job_id") or 0) != int(assignment.job.onchain_job_id):
        raise ExecutionTransportError("The evidence belongs to a different Arc job.")

    outcome = str(evidence.get("outcome") or "SUCCEEDED").upper().strip()
    if outcome == "FAILED":
        stage = str(evidence.get("failure_stage") or "runtime_execution")[:80]
        message = _safe_text(evidence.get("failure_message"), limit=2000)
        if not message:
            raise ExecutionTransportError("The signed runtime failure has no diagnostic message.")
        now = timezone.now()
        with transaction.atomic():
            locked = WorkerJobAssignment.objects.select_for_update().select_related("queue_item").get(pk=assignment.pk)
            if locked.status == WorkerJobAssignment.Status.FAILED and locked.evidence_hash == evidence_hash:
                return locked
            if locked.status not in {
                WorkerJobAssignment.Status.LEASED,
                WorkerJobAssignment.Status.EXECUTING,
            }:
                raise ExecutionTransportError("This assignment is not accepting a runtime failure result.")
            locked.status = WorkerJobAssignment.Status.FAILED
            locked.evidence_hash = evidence_hash
            locked.runtime_signature = signature
            locked.execution_evidence = evidence
            locked.execution_completed_at = now
            locked.failure_stage = stage
            locked.failure_message = message
            locked.save(
                update_fields=[
                    "status", "evidence_hash", "runtime_signature", "execution_evidence",
                    "execution_completed_at", "failure_stage", "failure_message", "updated_at",
                ]
            )
            item = locked.queue_item
            item.status = WorkerJobQueueItem.Status.FAILED
            item.execution_post_test_passed = False
            item.execution_failure_stage = stage
            item.execution_failure_message = message
            item.execution_engine_output = _safe_text(evidence.get("summary"), limit=12000)
            item.execution_test_output = _safe_text(evidence.get("test_output"), limit=12000)
            item.execution_completed_at = now
            item.save(
                update_fields=[
                    "status", "execution_post_test_passed", "execution_failure_stage",
                    "execution_failure_message", "execution_engine_output", "execution_test_output",
                    "execution_completed_at", "updated_at",
                ]
            )
            return locked
    if outcome != "SUCCEEDED":
        raise ExecutionTransportError("The execution outcome is invalid.")

    commit_sha = str(evidence.get("commit_sha") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ExecutionTransportError("The submitted Git commit SHA is invalid.")
    pr_number = int(evidence.get("pull_request_number") or 0)
    pr_url = str(evidence.get("pull_request_url") or "").strip()
    changed_files = _normalised_paths(evidence.get("changed_files") or [])
    if not pr_number or not pr_url or not changed_files:
        raise ExecutionTransportError("The execution result has no valid pull request or changed files.")
    if "test_return_code" not in evidence:
        raise ExecutionTransportError("The execution result is missing its post-change test result.")
    try:
        test_return_code = int(evidence.get("test_return_code"))
    except (TypeError, ValueError) as exc:
        raise ExecutionTransportError("The execution test return code is invalid.") from exc
    if test_return_code != 0:
        raise ExecutionTransportError("The runtime's post-change test did not pass.")
    _validate_paths(assignment, changed_files)

    try:
        github = GitHubAppExecutionClient.for_job(assignment.job)
        pr = github.pull_request(
            owner=assignment.job.draft.repository_owner,
            repository=assignment.job.draft.repository_name,
            number=pr_number,
        )
    except GitHubExecutionError as exc:
        raise ExecutionTransportError(str(exc)) from exc
    if pr.state != "open" and not pr.merged:
        raise ExecutionTransportError("The submitted pull request is not open or merged.")
    if pr.head_ref != assignment.queue_item.execution_branch_name:
        raise ExecutionTransportError("The pull request branch does not match the execution lease.")
    if pr.base_ref != assignment.job.draft.target_branch:
        raise ExecutionTransportError("The pull request targets the wrong base branch.")
    if pr.head_sha != commit_sha:
        raise ExecutionTransportError("The pull request commit does not match the signed evidence.")
    if pr.html_url != pr_url:
        raise ExecutionTransportError("The pull request URL does not match GitHub.")
    if tuple(sorted(changed_files)) != tuple(sorted(pr.changed_files)):
        raise ExecutionTransportError("The signed changed-file list does not match GitHub.")

    now = timezone.now()
    with transaction.atomic():
        locked = WorkerJobAssignment.objects.select_for_update().select_related("queue_item").get(pk=assignment.pk)
        if locked.status in {
            WorkerJobAssignment.Status.RESULT_RECEIVED,
            WorkerJobAssignment.Status.SUBMITTING,
            WorkerJobAssignment.Status.SUBMITTED,
            WorkerJobAssignment.Status.VERIFYING,
            WorkerJobAssignment.Status.SETTLING,
            WorkerJobAssignment.Status.COMPLETED,
        }:
            return locked
        locked.status = WorkerJobAssignment.Status.RESULT_RECEIVED
        locked.evidence_hash = evidence_hash
        locked.runtime_signature = signature
        locked.execution_evidence = evidence
        locked.execution_completed_at = now
        locked.failure_stage = ""
        locked.failure_message = ""
        locked.save(
            update_fields=[
                "status",
                "evidence_hash",
                "runtime_signature",
                "execution_evidence",
                "execution_completed_at",
                "failure_stage",
                "failure_message",
                "updated_at",
            ]
        )
        item = locked.queue_item
        item.status = WorkerJobQueueItem.Status.SUBMISSION_PENDING
        item.execution_post_test_passed = True
        item.execution_baseline_test_command = str(evidence.get("baseline_test_command") or "")[:240]
        item.execution_post_test_command = str(evidence.get("test_command") or "")[:240]
        try:
            baseline_return_code = int(evidence.get("baseline_test_return_code"))
        except (TypeError, ValueError):
            baseline_return_code = 1
        item.execution_baseline_test_passed = baseline_return_code == 0
        item.execution_changed_files = changed_files
        item.execution_commit_sha = commit_sha
        item.execution_pull_request_number = pr_number
        item.execution_pull_request_url = pr_url
        item.execution_engine_output = _safe_text(evidence.get("summary"), limit=12000)
        item.execution_baseline_test_output = _safe_text(evidence.get("baseline_test_output"), limit=12000)
        item.execution_test_output = _safe_text(evidence.get("test_output"), limit=12000)
        item.execution_failure_stage = ""
        item.execution_failure_message = ""
        item.execution_completed_at = now
        item.save(
            update_fields=[
                "status",
                "execution_post_test_passed",
                "execution_baseline_test_command",
                "execution_post_test_command",
                "execution_baseline_test_passed",
                "execution_changed_files",
                "execution_commit_sha",
                "execution_pull_request_number",
                "execution_pull_request_url",
                "execution_engine_output",
                "execution_baseline_test_output",
                "execution_test_output",
                "execution_failure_stage",
                "execution_failure_message",
                "execution_completed_at",
                "updated_at",
            ]
        )
        return locked
