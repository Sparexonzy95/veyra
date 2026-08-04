from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from web3 import Web3

from common.utils import canonical_json
from jobs.github_app import GitHubAppError, token_for_repository
from workers.models import (
    HostedAgentConnection,
    WorkerAgent,
    WorkerJobAssignment,
    WorkerVerificationAssignment,
)


LEASE_SALT = "veyra.verifier-agent.lease.v1"
FINAL_STATUSES = {
    WorkerVerificationAssignment.Status.APPROVED,
    WorkerVerificationAssignment.Status.REJECTED,
    WorkerVerificationAssignment.Status.INCONCLUSIVE,
}


class VerificationTransportError(RuntimeError):
    pass


def _lease_minutes() -> int:
    return max(5, int(getattr(settings, "VEYRA_VERIFIER_LEASE_MINUTES", 30)))


def _safe_text(value: Any, *, limit: int = 4000) -> str:
    text = str(value or "").strip()
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
    return text[:limit]


def _b64url_decode(value: str) -> bytes:
    raw = str(value or "").strip()
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw + padding)
    except Exception as exc:
        raise VerificationTransportError("The verifier signing data is invalid.") from exc


def _report_hash(report: dict[str, Any]) -> str:
    return "0x" + hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()


def _lease_token(value: WorkerVerificationAssignment) -> str:
    return signing.dumps(
        {
            "verification_id": str(value.id),
            "worker_assignment_id": str(value.worker_assignment_id),
            "verifier_id": str(value.verifier_id),
            "lease_id": str(value.lease_id),
        },
        salt=LEASE_SALT,
        compress=True,
    )


def _verify_lease(value: WorkerVerificationAssignment, token: str) -> None:
    try:
        payload = signing.loads(
            str(token or ""),
            salt=LEASE_SALT,
            max_age=_lease_minutes() * 60 + 120,
        )
    except signing.BadSignature as exc:
        raise VerificationTransportError("The verifier lease is invalid or expired.") from exc
    if (
        str(payload.get("verification_id") or "") != str(value.id)
        or str(payload.get("worker_assignment_id") or "")
        != str(value.worker_assignment_id)
        or str(payload.get("verifier_id") or "") != str(value.verifier_id)
        or str(payload.get("lease_id") or "") != str(value.lease_id)
    ):
        raise VerificationTransportError("The verifier lease does not match this review.")
    if value.lease_expires_at and value.lease_expires_at < timezone.now():
        raise VerificationTransportError("The verifier lease expired.")


def _assert_independent(
    value: WorkerVerificationAssignment,
    connection: HostedAgentConnection,
) -> None:
    worker = value.worker_assignment.worker
    verifier = value.verifier
    if connection.worker_id != verifier.id:
        raise VerificationTransportError("This verifier lease belongs to another agent.")
    if verifier.agent_role != WorkerAgent.AgentRole.VERIFIER:
        raise VerificationTransportError("This runtime is not connected to a verifier agent.")
    if worker.id == verifier.id:
        raise VerificationTransportError("A worker cannot verify its own submission.")
    if worker.owner_user_id and verifier.owner_user_id == worker.owner_user_id:
        raise VerificationTransportError(
            "The verifier is controlled by the same owner as the worker."
        )
    if (
        worker.owner_type == WorkerAgent.OwnerType.VEYRA
        and verifier.owner_type == WorkerAgent.OwnerType.VEYRA
    ):
        raise VerificationTransportError(
            "A Veyra-owned worker requires a separately operated verifier."
        )
    try:
        worker_connection = worker.hosted_connection
    except HostedAgentConnection.DoesNotExist:
        worker_connection = None
    if worker_connection and (
        worker_connection.runtime_id == connection.runtime_id
        or worker_connection.public_key_fingerprint
        == connection.public_key_fingerprint
    ):
        raise VerificationTransportError(
            "Worker and verifier must use separate runtime identities and signing keys."
        )


def verification_task_for_connection(
    connection: HostedAgentConnection,
) -> dict[str, Any] | None:
    if connection.worker.agent_role != WorkerAgent.AgentRole.VERIFIER:
        return None
    value = (
        WorkerVerificationAssignment.objects.select_related(
            "verifier",
            "worker_assignment__worker__hosted_connection",
            "worker_assignment__queue_item",
            "worker_assignment__job__draft__funding_snapshot",
            "worker_assignment__job__draft__github_repository_access__installation",
        )
        .filter(
            verifier=connection.worker,
            status__in=[
                WorkerVerificationAssignment.Status.RESERVED,
                WorkerVerificationAssignment.Status.LEASED,
                WorkerVerificationAssignment.Status.RUNNING,
            ],
        )
        .order_by("reserved_at")
        .first()
    )
    if value is None:
        return None
    _assert_independent(value, connection)
    now = timezone.now()
    if value.status == WorkerVerificationAssignment.Status.RESERVED:
        if value.reserved_until < now:
            value.status = WorkerVerificationAssignment.Status.EXPIRED
            value.failure_message = "The verifier did not lease the review before reservation expiry."
            value.completed_at = now
            value.save(
                update_fields=[
                    "status",
                    "failure_message",
                    "completed_at",
                    "updated_at",
                ]
            )
            return None
        value.lease_id = __import__("uuid").uuid4()
        value.lease_expires_at = now + timedelta(minutes=_lease_minutes())
        value.leased_at = now
        value.status = WorkerVerificationAssignment.Status.LEASED
        value.save(
            update_fields=[
                "lease_id",
                "lease_expires_at",
                "leased_at",
                "status",
                "updated_at",
            ]
        )
    if value.lease_expires_at and value.lease_expires_at < now:
        value.status = WorkerVerificationAssignment.Status.EXPIRED
        value.failure_message = "The verifier lease expired before a signed verdict was submitted."
        value.completed_at = now
        value.save(
            update_fields=[
                "status",
                "failure_message",
                "completed_at",
                "updated_at",
            ]
        )
        return None

    assignment = value.worker_assignment
    item = assignment.queue_item
    job = assignment.job
    commitment = job.draft.funding_snapshot.task_commitment or {}
    policy = job.draft.funding_snapshot.policy_commitment or {}
    api_root = str(
        getattr(settings, "VEYRA_PUBLIC_API_URL", "http://127.0.0.1:8000")
    ).rstrip("/")
    return {
        "id": str(value.id),
        "type": "independent_verification",
        "worker_assignment_id": str(assignment.id),
        "job_id": int(job.onchain_job_id),
        "lease_id": str(value.lease_id),
        "lease_token": _lease_token(value),
        "lease_expires_at": value.lease_expires_at.isoformat(),
        "repository": {
            "owner": job.draft.repository_owner,
            "name": job.draft.repository_name,
            "full_name": f"{job.draft.repository_owner}/{job.draft.repository_name}",
            "clone_url": f"https://github.com/{job.draft.repository_owner}/{job.draft.repository_name}.git",
            "target_branch": job.draft.target_branch,
        },
        "submission": {
            "commit_sha": item.execution_commit_sha,
            "pull_request_number": int(item.execution_pull_request_number or 0),
            "pull_request_url": item.execution_pull_request_url,
            "branch": item.execution_branch_name,
            "changed_files": sorted(item.execution_changed_files or []),
            "worker_evidence_hash": assignment.evidence_hash,
            "worker_test_command": item.execution_post_test_command,
            "worker_test_passed": bool(item.execution_post_test_passed),
        },
        "work": {
            "title": str(commitment.get("title") or job.draft.issue_title),
            "description": str(commitment.get("description") or job.draft.issue_body),
            "acceptance_criteria": list(commitment.get("acceptanceCriteria") or []),
            "technical_requirements": list(commitment.get("technicalRequirements") or []),
        },
        "policy": {
            "allowed_paths": list(policy.get("allowedPaths") or []),
            "forbidden_paths": list(policy.get("forbiddenPaths") or []),
            "required_commands": list(policy.get("requiredCommands") or []),
            "maximum_review_minutes": _lease_minutes(),
        },
        "credential_url": f"{api_root}/api/v1/agent-runtime/verification/credential/",
        "submit_url": f"{api_root}/api/v1/agent-runtime/verification/result/",
    }


def repository_credential_for_verifier(
    connection: HostedAgentConnection,
    *,
    verification_id: str,
    lease_token: str,
) -> dict[str, Any]:
    try:
        value = WorkerVerificationAssignment.objects.select_related(
            "verifier",
            "worker_assignment__worker__hosted_connection",
            "worker_assignment__job__draft__github_repository_access__installation",
        ).get(pk=verification_id)
    except (WorkerVerificationAssignment.DoesNotExist, ValueError) as exc:
        raise VerificationTransportError("The verifier assignment was not found.") from exc
    _assert_independent(value, connection)
    _verify_lease(value, lease_token)
    if value.status not in {
        WorkerVerificationAssignment.Status.LEASED,
        WorkerVerificationAssignment.Status.RUNNING,
    }:
        raise VerificationTransportError(
            f"Repository access is unavailable while review status is {value.status}."
        )
    job = value.worker_assignment.job
    access = job.draft.github_repository_access
    if not access or not access.active:
        raise VerificationTransportError(
            "The funded repository is no longer approved for Veyra verification."
        )
    try:
        token = token_for_repository(
            access,
            permissions={
                "contents": "read",
                "pull_requests": "read",
                "checks": "read",
            },
            use_cache=False,
        )
    except GitHubAppError as exc:
        raise VerificationTransportError(str(exc)) from exc
    if value.status == WorkerVerificationAssignment.Status.LEASED:
        value.status = WorkerVerificationAssignment.Status.RUNNING
        value.started_at = value.started_at or timezone.now()
        value.save(update_fields=["status", "started_at", "updated_at"])
    return {
        "token": token.token,
        "expires_at": token.expires_at,
        "repository": access.full_name,
        "clone_url": f"https://github.com/{access.full_name}.git",
        "permissions": {
            "contents": "read",
            "pull_requests": "read",
            "checks": "read",
            "metadata": "read",
        },
        "write_access": False,
    }


def _canonical_report(
    value: WorkerVerificationAssignment,
    report: dict[str, Any],
) -> dict[str, Any]:
    assignment = value.worker_assignment
    item = assignment.queue_item
    job = assignment.job
    verdict = str(report.get("verdict") or "").strip().upper()
    if verdict not in {"APPROVED", "REJECTED", "INCONCLUSIVE"}:
        raise VerificationTransportError("The verifier returned an invalid verdict.")
    commit_sha = str(report.get("commit_sha") or "").strip().lower()
    if commit_sha != item.execution_commit_sha.lower():
        raise VerificationTransportError("The verifier reviewed a different commit SHA.")
    if int(report.get("pull_request_number") or 0) != int(
        item.execution_pull_request_number or 0
    ):
        raise VerificationTransportError("The verifier reviewed a different pull request.")
    changed_files = sorted(
        {
            str(path).replace("\\", "/").strip().lstrip("/")
            for path in list(report.get("changed_files") or [])
            if str(path).strip()
        }
    )
    if changed_files != sorted(item.execution_changed_files or []):
        raise VerificationTransportError(
            "The verifier report does not match the exact submitted changed-file set."
        )
    try:
        test_return_code = int(report.get("independent_test_return_code"))
    except (TypeError, ValueError) as exc:
        raise VerificationTransportError(
            "The verifier report has no independent test return code."
        ) from exc
    criteria = report.get("acceptance_criteria") or []
    if not isinstance(criteria, list):
        raise VerificationTransportError("Acceptance-criteria results must be a list.")
    expected = list(
        job.draft.funding_snapshot.task_commitment.get("acceptanceCriteria") or []
    )
    if len(criteria) != len(expected):
        raise VerificationTransportError(
            "The verifier must return one result for every funded acceptance criterion."
        )
    cleaned_criteria: list[dict[str, Any]] = []
    for index, expected_value in enumerate(expected):
        item_result = criteria[index]
        if not isinstance(item_result, dict):
            raise VerificationTransportError("An acceptance-criteria result is invalid.")
        statement = (
            str(expected_value.get("statement") or expected_value)
            if isinstance(expected_value, dict)
            else str(expected_value)
        )
        cleaned_criteria.append(
            {
                "statement": statement[:500],
                "passed": bool(item_result.get("passed")),
                "evidence": _safe_text(item_result.get("evidence"), limit=1200),
            }
        )
    findings = report.get("security_findings") or []
    if not isinstance(findings, list):
        raise VerificationTransportError("Security findings must be a list.")
    cleaned_findings: list[dict[str, str]] = []
    for finding in findings[:30]:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "LOW").strip().upper()
        if severity not in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            severity = "LOW"
        cleaned_findings.append(
            {
                "severity": severity,
                "title": _safe_text(finding.get("title"), limit=240),
                "detail": _safe_text(finding.get("detail"), limit=1200),
            }
        )
    all_criteria_passed = all(entry["passed"] for entry in cleaned_criteria)
    blocking_finding = any(
        entry["severity"] in {"HIGH", "CRITICAL"}
        for entry in cleaned_findings
    )
    if verdict == "APPROVED" and (
        test_return_code != 0 or not all_criteria_passed or blocking_finding
    ):
        raise VerificationTransportError(
            "An approval requires passing independent tests, every acceptance criterion, and no high-severity finding."
        )
    return {
        "version": 1,
        "verification_mode": "INDEPENDENT_VERIFIER_AGENT",
        "verification_assignment_id": str(value.id),
        "worker_assignment_id": str(assignment.id),
        "job_id": int(job.onchain_job_id),
        "worker_id": str(assignment.worker_id),
        "verifier_id": str(value.verifier_id),
        "repository": f"{job.draft.repository_owner}/{job.draft.repository_name}",
        "commit_sha": commit_sha,
        "pull_request_number": int(item.execution_pull_request_number or 0),
        "pull_request_url": item.execution_pull_request_url,
        "changed_files": changed_files,
        "independent_test_command": _safe_text(
            report.get("independent_test_command"), limit=500
        ),
        "independent_test_return_code": test_return_code,
        "independent_test_output": _safe_text(
            report.get("independent_test_output"), limit=12000
        ),
        "acceptance_criteria": cleaned_criteria,
        "security_findings": cleaned_findings,
        "summary": _safe_text(report.get("summary"), limit=3000),
        "verdict": verdict,
        "provider": _safe_text(report.get("provider"), limit=80),
        "model": _safe_text(report.get("model"), limit=160),
        "runtime_version": _safe_text(report.get("runtime_version"), limit=80),
        "started_at": _safe_text(report.get("started_at"), limit=80),
        "completed_at": _safe_text(report.get("completed_at"), limit=80),
    }


def submit_verifier_result(
    *,
    connection: HostedAgentConnection,
    payload: dict[str, Any],
) -> WorkerVerificationAssignment:
    verification_id = str(payload.get("verification_id") or "").strip()
    lease_token = str(payload.get("lease_token") or "").strip()
    signature = str(payload.get("signature") or "").strip()
    raw_report = payload.get("report") or {}
    if not verification_id or not lease_token or not signature or not isinstance(raw_report, dict):
        raise VerificationTransportError("The verifier result is incomplete.")
    try:
        value = WorkerVerificationAssignment.objects.select_related(
            "verifier",
            "worker_assignment__worker__hosted_connection",
            "worker_assignment__queue_item",
            "worker_assignment__job__draft__funding_snapshot",
        ).get(pk=verification_id)
    except (WorkerVerificationAssignment.DoesNotExist, ValueError) as exc:
        raise VerificationTransportError("The verifier assignment was not found.") from exc
    _assert_independent(value, connection)
    _verify_lease(value, lease_token)
    signed_payload_hash = "0x" + hashlib.sha256(
        canonical_json(raw_report).encode("utf-8")
    ).hexdigest()
    message = (
        f"veyra-verifier-result-v1:{value.id}:{value.lease_id}:{signed_payload_hash}"
    ).encode("utf-8")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            _b64url_decode(connection.public_key)
        )
        public_key.verify(_b64url_decode(signature), message)
    except (ValueError, InvalidSignature) as exc:
        raise VerificationTransportError(
            "The independent verifier signature is invalid."
        ) from exc
    report = _canonical_report(value, raw_report)
    report_hash = _report_hash(report)

    if value.status in FINAL_STATUSES:
        if value.report_hash != report_hash:
            raise VerificationTransportError(
                "This verifier assignment already has a different final report."
            )
        return value
    if value.status not in {
        WorkerVerificationAssignment.Status.LEASED,
        WorkerVerificationAssignment.Status.RUNNING,
    }:
        raise VerificationTransportError(
            f"A verifier result cannot be submitted while status is {value.status}."
        )

    verdict = report["verdict"]
    status_value = {
        "APPROVED": WorkerVerificationAssignment.Status.APPROVED,
        "REJECTED": WorkerVerificationAssignment.Status.REJECTED,
        "INCONCLUSIVE": WorkerVerificationAssignment.Status.INCONCLUSIVE,
    }[verdict]
    evidence_hash = Web3.to_hex(
        Web3.keccak(
            text=canonical_json(
                {
                    "report_hash": report_hash,
                    "signed_payload_hash": signed_payload_hash,
                    "signature": signature,
                    "verifier_id": str(value.verifier_id),
                }
            )
        )
    )
    now = timezone.now()
    with transaction.atomic():
        locked = WorkerVerificationAssignment.objects.select_for_update().get(pk=value.pk)
        if locked.status in FINAL_STATUSES:
            if locked.report_hash != report_hash:
                raise VerificationTransportError(
                    "This verifier assignment already has a different final report."
                )
            return locked
        locked.status = status_value
        locked.verdict = verdict
        locked.report = report
        locked.report_hash = report_hash
        locked.evidence_hash = evidence_hash
        locked.runtime_signature = signature
        locked.completed_at = now
        locked.failure_message = ""
        locked.save(
            update_fields=[
                "status",
                "verdict",
                "report",
                "report_hash",
                "evidence_hash",
                "runtime_signature",
                "completed_at",
                "failure_message",
                "updated_at",
            ]
        )
        assignment = WorkerJobAssignment.objects.select_for_update().get(
            pk=locked.worker_assignment_id
        )
        # The verifier-agent report is stored on its own assignment. The final
        # WorkerJobAssignment report/hash is created only after Veyra combines
        # this signed verdict with exact-commit GitHub CI evidence.
        assignment.verification_status = f"VERIFIER_{verdict}"
        assignment.failure_stage = ""
        assignment.failure_message = ""
        assignment.save(
            update_fields=[
                "verification_status",
                "failure_stage",
                "failure_message",
                "updated_at",
            ]
        )
        return locked
