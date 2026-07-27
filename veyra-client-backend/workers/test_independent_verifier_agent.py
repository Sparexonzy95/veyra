from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from common.utils import canonical_json
from jobs.models import (
    GitHubAppInstallation,
    GitHubRepositoryAccess,
    JobDraft,
    JobFundingSnapshot,
    VeyraJob,
)
from workers.execution_verification import (
    ExecutionVerificationPending,
    _verification_report,
)
from workers.github_app_execution import PullRequestSnapshot
from workers.hosted_agent_connection import (
    HostedAgentConnectionError,
    connect_hosted_agent,
)
from workers.models import (
    HostedAgentConnection,
    WorkerAgent,
    WorkerJobAssignment,
    WorkerJobQueueItem,
    WorkerVerificationAssignment,
)
from workers.verification_matching import reserve_verifier_for_assignment
from workers.verification_transport import (
    repository_credential_for_verifier,
    submit_verifier_result,
    verification_task_for_connection,
)


CLIENT = "0x1111111111111111111111111111111111111111"
VERIFIER_ADDRESS = "0x0EdBC6F8506e72478CE78a4AE934C7b21cb7050A"
ZERO = "0x0000000000000000000000000000000000000000"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@override_settings(
    VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS=60,
    VEYRA_VERIFIER_RESERVATION_SECONDS=90,
    VEYRA_VERIFIER_LEASE_MINUTES=30,
    VEYRA_REQUIRE_GITHUB_CHECKS=True,
    VEYRA_PUBLIC_API_URL="http://127.0.0.1:8000",
)
class IndependentVerifierAgentTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(handle="verifier-client")
        installation = GitHubAppInstallation.objects.create(
            client=self.client_user,
            installation_id=9001,
            account_id=9002,
            account_login="example",
            account_type="Organization",
            repository_selection="selected",
            permissions={
                "contents": "write",
                "pull_requests": "write",
                "checks": "read",
            },
            status=GitHubAppInstallation.Status.CONNECTED,
            last_checked_at=timezone.now(),
        )
        access = GitHubRepositoryAccess.objects.create(
            installation=installation,
            github_repository_id=9003,
            owner="example",
            name="flask-repo",
            full_name="example/flask-repo",
            private=False,
            default_branch="main",
            html_url="https://github.com/example/flask-repo",
            permissions={
                "contents": "write",
                "pull_requests": "write",
                "checks": "read",
            },
            active=True,
            last_synced_at=timezone.now(),
        )
        deadline = timezone.now() + timedelta(hours=3)
        draft = JobDraft.objects.create(
            client=self.client_user,
            status=JobDraft.Status.FUNDED,
            github_issue_url="https://github.com/example/flask-repo/issues/44",
            github_repository_access=access,
            repository_owner="example",
            repository_name="flask-repo",
            target_branch="main",
            issue_number=44,
            issue_title="Add Flask health endpoint",
            issue_body="Add a tested health endpoint.",
            budget_usdc="3.000000",
            deadline=deadline,
            acceptance_criteria=["Pytest passes"],
            advanced_options={},
        )
        JobFundingSnapshot.objects.create(
            draft=draft,
            repository_commitment={
                "version": 2,
                "owner": "example",
                "repository": "flask-repo",
                "targetBranch": "main",
                "issueNumber": 44,
            },
            task_commitment={
                "version": 2,
                "title": draft.issue_title,
                "description": draft.issue_body,
                "technicalRequirements": [],
                "acceptanceCriteria": [
                    {
                        "statement": "Pytest passes",
                        "verificationMethod": "AUTOMATED_TEST",
                    }
                ],
            },
            policy_commitment={
                "version": 2,
                "requiredCommands": ["python -m pytest -q"],
                "allowedPaths": [],
                "forbiddenPaths": [".env", ".github/workflows"],
                "deliveryType": "PULL_REQUEST",
                "agentAccess": "OPEN",
            },
            repository_hash="0x" + "11" * 32,
            task_hash="0x" + "22" * 32,
            policy_hash="0x" + "33" * 32,
            budget_atomic=3_000_000,
            expires_at=int(deadline.timestamp()),
            verifier_address=VERIFIER_ADDRESS,
            invited_provider_address=ZERO,
        )
        self.job = VeyraJob.objects.create(
            client=self.client_user,
            draft=draft,
            onchain_job_id=44,
            status="SUBMITTED",
            client_status="UNDER_REVIEW",
            client_address=CLIENT,
            invited_provider_address=ZERO,
            provider_address="0x" + "21" * 20,
            verifier_address=VERIFIER_ADDRESS,
            budget_atomic=3_000_000,
            expires_at=int(deadline.timestamp()),
            repository_hash="0x" + "11" * 32,
            task_hash="0x" + "22" * 32,
            policy_hash="0x" + "33" * 32,
            creation_tx_hash="0x" + "44" * 32,
        )
        self.worker_owner = User.objects.create_user(handle="worker-owner")
        self.worker, self.worker_connection, _ = self._agent(
            slug="logicbloom-worker",
            role=WorkerAgent.AgentRole.WORKER,
            owner=self.worker_owner,
            runtime_id="worker-runtime",
            fingerprint="1" * 64,
            port=9100,
        )
        self.verifier, self.verifier_connection, self.verifier_key = self._agent(
            slug="codesentinel-verifier",
            role=WorkerAgent.AgentRole.VERIFIER,
            owner=None,
            runtime_id="verifier-runtime",
            fingerprint="2" * 64,
            port=9200,
        )
        item = WorkerJobQueueItem.objects.create(
            worker=self.worker,
            job=self.job,
            status=WorkerJobQueueItem.Status.SUBMITTED,
            source=WorkerJobQueueItem.Source.FAST_PATH,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            priority_score=1000,
            required_skills=["Python", "Flask", "Pytest"],
            matched_skills=["Python", "Flask", "Pytest"],
            onchain_status="SUBMITTED",
            claim_arc_transaction_hash="0x" + "ab" * 32,
            claim_confirmed_at=timezone.now(),
            execution_branch_name="veyra/job-44-logicbloom",
            execution_post_test_command="python -m pytest -q",
            execution_post_test_passed=True,
            execution_changed_files=["app.py", "tests/test_app.py"],
            execution_commit_sha="c" * 40,
            execution_pull_request_number=42,
            execution_pull_request_url="https://github.com/example/flask-repo/pull/42",
            submission_commit_hash="0x" + "cc" * 32,
            submission_deliverable_hash="0x" + "dd" * 32,
            submission_arc_transaction_hash="0x" + "ee" * 32,
            submission_confirmed_at=timezone.now(),
        )
        self.assignment = WorkerJobAssignment.objects.create(
            job=self.job,
            worker=self.worker,
            queue_item=item,
            status=WorkerJobAssignment.Status.SUBMITTED,
            reserved_until=timezone.now() + timedelta(seconds=90),
            matching_score=3000,
            candidate_count=1,
            evidence_hash="0x" + "aa" * 32,
            runtime_signature="worker-signature",
        )

    def _agent(self, *, slug, role, owner, runtime_id, fingerprint, port):
        worker = WorkerAgent.objects.create(
            slug=slug,
            name=slug.replace("-", " ").title(),
            description="Independent Veyra agent",
            owner_type=(
                WorkerAgent.OwnerType.EXTERNAL
                if owner is not None
                else WorkerAgent.OwnerType.VEYRA
            ),
            owner_user=owner,
            agent_role=role,
            status=WorkerAgent.Status.ACTIVE,
            specialisation=(
                WorkerAgent.Specialisation.PYTHON_BACKEND
                if role == WorkerAgent.AgentRole.WORKER
                else WorkerAgent.Specialisation.TESTING_QA
            ),
            languages=["Python"],
            frameworks=["Flask"],
            testing_tools=["Pytest"],
            task_types=["API endpoint" if role == WorkerAgent.AgentRole.WORKER else "Verification"],
            skills=["Python", "Flask", "Pytest", "Verification"],
            minimum_budget_usdc="1.000000",
            maximum_budget_usdc="5.000000",
            auto_claim_enabled=role == WorkerAgent.AgentRole.WORKER,
            discovery_enabled=role == WorkerAgent.AgentRole.WORKER,
            maximum_active_jobs=1,
            maximum_execution_minutes=30,
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="zai-org/glm-5.2",
            engine_connected=True,
            engine_version="test-runtime/1.1",
            engine_last_checked_at=timezone.now(),
            worker_wallet_address=(
                "0x" + "21" * 20
                if role == WorkerAgent.AgentRole.WORKER
                else ""
            ),
            payout_wallet_address=(
                "0x" + "21" * 20
                if role == WorkerAgent.AgentRole.WORKER
                else ""
            ),
            contract_authorised=role == WorkerAgent.AgentRole.WORKER,
            test_assignment_passed=True,
            activated_at=timezone.now(),
        )
        key = Ed25519PrivateKey.generate()
        public_key = _b64url(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        connection = HostedAgentConnection.objects.create(
            worker=worker,
            runtime_id=runtime_id,
            runtime_url=f"http://localhost:{port}",
            public_key=public_key,
            public_key_fingerprint=fingerprint,
            protocol_version=1,
            runtime_version="test-runtime/1.1",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={
                "role": role,
                "coding": role == WorkerAgent.AgentRole.WORKER,
                "verification": role == WorkerAgent.AgentRole.VERIFIER,
                "testing": True,
            },
            credential_hash=hashlib.sha256(runtime_id.encode()).hexdigest(),
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        return worker, connection, key

    def _approval_report(self):
        return {
            "verdict": "APPROVED",
            "summary": "Exact commit satisfies the funded task.",
            "commit_sha": "c" * 40,
            "pull_request_number": 42,
            "changed_files": ["app.py", "tests/test_app.py"],
            "independent_test_command": "python -m pytest -q",
            "independent_test_return_code": 0,
            "independent_test_output": "3 passed",
            "acceptance_criteria": [
                {"passed": True, "evidence": "Independent Pytest run passed."}
            ],
            "security_findings": [],
            "provider": "aiand",
            "model": "zai-org/glm-5.2",
            "runtime_version": "test-runtime/1.1",
            "started_at": timezone.now().isoformat(),
            "completed_at": timezone.now().isoformat(),
        }

    def _signed_submission(self, value, task, report):
        payload_hash = "0x" + hashlib.sha256(
            canonical_json(report).encode("utf-8")
        ).hexdigest()
        message = (
            f"veyra-verifier-result-v1:{value.id}:{value.lease_id}:{payload_hash}"
        ).encode("utf-8")
        return {
            "verification_id": str(value.id),
            "lease_token": task["lease_token"],
            "report": report,
            "signature": _b64url(self.verifier_key.sign(message)),
        }


    @override_settings(DEBUG=True, VEYRA_ALLOW_LOCAL_AGENT_RUNTIME=True)
    def test_worker_runtime_cannot_be_connected_as_verifier(self):
        candidate = WorkerAgent.objects.create(
            slug="role-mismatch-verifier",
            name="Role Mismatch Verifier",
            owner_type=WorkerAgent.OwnerType.VEYRA,
            owner_user=None,
            agent_role=WorkerAgent.AgentRole.VERIFIER,
            status=WorkerAgent.Status.PROFILE_READY,
            specialisation=WorkerAgent.Specialisation.TESTING_QA,
            languages=["Python"],
            frameworks=["Flask"],
            testing_tools=["Pytest"],
            task_types=["Verification"],
            skills=["Python", "Flask", "Pytest", "Verification"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="zai-org/glm-5.2",
        )
        key = Ed25519PrivateKey.generate()
        public_key = _b64url(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        claim_calls = 0

        def handler(request: httpx.Request):
            nonlocal claim_calls
            payload = json.loads(request.content.decode("utf-8"))
            if request.url.path == "/veyra/connect/challenge":
                challenge = payload["challenge"]
                runtime_id = "advertised-worker-runtime"
                signature = key.sign(
                    f"veyra-connect-v1:{challenge}:{runtime_id}".encode("utf-8")
                )
                return httpx.Response(
                    200,
                    json={
                        "runtime_id": runtime_id,
                        "challenge": challenge,
                        "signature": _b64url(signature),
                        "public_key": public_key,
                        "runtime_version": "test-runtime/1.1",
                        "protocol_version": 1,
                        "provider": "aiand",
                        "model": "zai-org/glm-5.2",
                        "provider_ready": True,
                        "capabilities": {
                            "role": "WORKER",
                            "coding": True,
                            "verification": False,
                        },
                    },
                )
            if request.url.path == "/veyra/connect/claim":
                claim_calls += 1
                return httpx.Response(201, json={"connected": True})
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(HostedAgentConnectionError):
            connect_hosted_agent(
                worker=candidate,
                connection_link=(
                    "veyra-connect://localhost:9200/connect/"
                    "abcdefghijklmnopqrstuvwxyz123456?protocol=1"
                ),
                client=client,
                expected_role="VERIFIER",
            )
        self.assertEqual(claim_calls, 0)

    def test_separate_verifier_is_reserved_and_worker_is_never_selected(self):
        value = reserve_verifier_for_assignment(self.assignment)

        self.assertIsNotNone(value)
        self.assertEqual(value.verifier_id, self.verifier.id)
        self.assertNotEqual(value.verifier_id, self.worker.id)
        self.assertEqual(value.status, WorkerVerificationAssignment.Status.RESERVED)

    def test_same_owner_verifier_is_excluded(self):
        same_owner, _, _ = self._agent(
            slug="same-owner-verifier",
            role=WorkerAgent.AgentRole.VERIFIER,
            owner=self.worker_owner,
            runtime_id="same-owner-runtime",
            fingerprint="3" * 64,
            port=9300,
        )
        self.verifier.status = WorkerAgent.Status.PAUSED
        self.verifier.save(update_fields=["status", "updated_at"])

        value = reserve_verifier_for_assignment(self.assignment)

        self.assertIsNone(value)
        self.assertFalse(
            WorkerVerificationAssignment.objects.filter(verifier=same_owner).exists()
        )

    @patch("workers.verification_transport.token_for_repository")
    def test_verifier_receives_read_only_repository_credential(self, token_for_repository):
        token_for_repository.return_value = SimpleNamespace(
            token="github-read-only-token-value",
            expires_at="2026-07-23T16:00:00Z",
        )
        value = reserve_verifier_for_assignment(self.assignment)
        task = verification_task_for_connection(self.verifier_connection)
        value.refresh_from_db()

        credential = repository_credential_for_verifier(
            self.verifier_connection,
            verification_id=str(value.id),
            lease_token=task["lease_token"],
        )

        self.assertFalse(credential["write_access"])
        self.assertEqual(credential["permissions"]["contents"], "read")
        _, kwargs = token_for_repository.call_args
        self.assertEqual(kwargs["permissions"]["pull_requests"], "read")
        self.assertFalse(kwargs["use_cache"])

    def test_signed_verifier_approval_is_stored_idempotently(self):
        value = reserve_verifier_for_assignment(self.assignment)
        task = verification_task_for_connection(self.verifier_connection)
        value.refresh_from_db()
        payload = self._signed_submission(value, task, self._approval_report())

        first = submit_verifier_result(
            connection=self.verifier_connection,
            payload=payload,
        )
        second = submit_verifier_result(
            connection=self.verifier_connection,
            payload=payload,
        )

        self.assertEqual(first.id, second.id)
        first.refresh_from_db()
        self.assertEqual(first.status, WorkerVerificationAssignment.Status.APPROVED)
        self.assertEqual(first.verdict, "APPROVED")
        self.assertTrue(first.report_hash.startswith("0x"))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.verification_status, "VERIFIER_APPROVED")
        self.assertFalse(self.assignment.verification_report_hash)

    @patch("workers.execution_verification.GitHubAppExecutionClient.for_job")
    def test_ci_pass_cannot_approve_without_verifier_agent(self, github_for_job):
        github_for_job.return_value.pull_request.return_value = PullRequestSnapshot(
            number=42,
            html_url="https://github.com/example/flask-repo/pull/42",
            state="open",
            merged=False,
            head_ref="veyra/job-44-logicbloom",
            head_sha="c" * 40,
            base_ref="main",
            changed_files=("app.py", "tests/test_app.py"),
        )
        github_for_job.return_value.check_runs.return_value = [
            {
                "name": "Veyra independent repository tests",
                "status": "completed",
                "conclusion": "success",
                "details_url": "https://github.com/example/flask-repo/actions/runs/1",
            }
        ]

        with self.assertRaises(ExecutionVerificationPending):
            _verification_report(self.assignment)

    @patch("workers.execution_verification.GitHubAppExecutionClient.for_job")
    def test_payment_approval_requires_ci_and_signed_verifier_approval(self, github_for_job):
        github_for_job.return_value.pull_request.return_value = PullRequestSnapshot(
            number=42,
            html_url="https://github.com/example/flask-repo/pull/42",
            state="open",
            merged=False,
            head_ref="veyra/job-44-logicbloom",
            head_sha="c" * 40,
            base_ref="main",
            changed_files=("app.py", "tests/test_app.py"),
        )
        github_for_job.return_value.check_runs.return_value = [
            {
                "name": "Veyra independent repository tests",
                "status": "completed",
                "conclusion": "success",
                "details_url": "https://github.com/example/flask-repo/actions/runs/1",
            }
        ]
        value = reserve_verifier_for_assignment(self.assignment)
        task = verification_task_for_connection(self.verifier_connection)
        value.refresh_from_db()
        submit_verifier_result(
            connection=self.verifier_connection,
            payload=self._signed_submission(value, task, self._approval_report()),
        )
        self.assignment.refresh_from_db()

        report, approved, reason = _verification_report(self.assignment)

        self.assertTrue(approved)
        self.assertEqual(reason, "")
        self.assertTrue(report["github_ci_passed"])
        self.assertEqual(report["verifier_agent"]["verdict"], "APPROVED")
        self.assertEqual(
            report["approval_rule"],
            "github_ci_passed AND independent_verifier_agent_approved",
        )
