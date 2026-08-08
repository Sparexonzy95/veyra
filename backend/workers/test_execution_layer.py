from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

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
from workers.execution_matching import reserve_best_agent_for_job
from workers.execution_control import claim_controller, release_controller
from workers.execution_recovery import (
    recover_retryable_runtime_failures,
    retry_existing_runtime_assignment,
)
from workers.execution_status import assignment_public_snapshot, job_execution_snapshot
from workers.capacity import active_assignment_count
from workers.claiming import _validate_queue_for_preflight
from workers.execution_transport import execution_task_for_connection, submit_execution_result
from workers.execution_verification import (
    ExecutionVerificationPending,
    _clear_recovered_failures,
    _verification_report,
)
from workers.github_app_execution import PullRequestSnapshot
from workers.models import (
    ExecutionLayerState,
    HostedAgentConnection,
    WorkerAgent,
    WorkerJobAssignment,
    WorkerJobQueueItem,
)


CLIENT = "0x1111111111111111111111111111111111111111"
VERIFIER = "0x0EdBC6F8506e72478CE78a4AE934C7b21cb7050A"
ZERO = "0x0000000000000000000000000000000000000000"
REPOSITORY_HASH = "0x" + "11" * 32
TASK_HASH = "0x" + "22" * 32
POLICY_HASH = "0x" + "33" * 32


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@override_settings(
    VEYRA_AGENT_RUNTIME_ONLINE_WINDOW_SECONDS=60,
    VEYRA_MATCHING_FAIRNESS_BAND=200,
    VEYRA_JOB_RESERVATION_SECONDS=90,
    VEYRA_REQUIRE_GITHUB_CHECKS=True,
    VEYRA_PUBLIC_API_URL="http://127.0.0.1:8000",
)
class ExecutionLayerTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(handle="execution-client")
        self.installation = GitHubAppInstallation.objects.create(
            client=self.client_user,
            installation_id=987654,
            account_id=123,
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
        self.repository_access = GitHubRepositoryAccess.objects.create(
            installation=self.installation,
            github_repository_id=445566,
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
        self.job = self._create_job(100)
        self.agent_one, self.connection_one, self.key_one = self._create_agent(
            "logic-one", "0x" + "21" * 20, 1
        )
        self.agent_two, self.connection_two, self.key_two = self._create_agent(
            "logic-two", "0x" + "22" * 20, 2
        )

    def _create_job(self, job_id: int) -> VeyraJob:
        deadline = timezone.now() + timedelta(hours=3)
        draft = JobDraft.objects.create(
            client=self.client_user,
            status=JobDraft.Status.FUNDED,
            github_issue_url=f"https://github.com/example/flask-repo/issues/{job_id}",
            github_repository_access=self.repository_access,
            repository_owner="example",
            repository_name="flask-repo",
            target_branch="main",
            issue_number=job_id,
            issue_title=f"Implement issue {job_id}",
            issue_body="Add the requested Flask endpoint.",
            budget_usdc="3.000000",
            deadline=deadline,
            acceptance_criteria=["Pytest passes"],
            advanced_options={},
        )
        JobFundingSnapshot.objects.create(
            draft=draft,
            repository_commitment={
                "version": 2,
                "host": "github.com",
                "owner": "example",
                "repository": "flask-repo",
                "targetBranch": "main",
                "issueNumber": job_id,
                "repositoryStack": [
                    {"name": "Python", "category": "language"},
                    {"name": "Flask", "category": "framework"},
                    {"name": "Pytest", "category": "testing"},
                ],
            },
            task_commitment={
                "version": 2,
                "title": draft.issue_title,
                "description": draft.issue_body,
                "technicalRequirements": [],
                "acceptanceCriteria": [
                    {"statement": "Pytest passes", "verificationMethod": "AUTOMATED_TEST"}
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
            repository_hash=REPOSITORY_HASH,
            task_hash=TASK_HASH,
            policy_hash=POLICY_HASH,
            budget_atomic=3_000_000,
            expires_at=int(deadline.timestamp()),
            verifier_address=VERIFIER,
            invited_provider_address=ZERO,
        )
        return VeyraJob.objects.create(
            client=self.client_user,
            draft=draft,
            onchain_job_id=job_id,
            status="FUNDED",
            client_status="OPEN",
            client_address=CLIENT,
            invited_provider_address=ZERO,
            provider_address="",
            verifier_address=VERIFIER,
            budget_atomic=3_000_000,
            expires_at=int(deadline.timestamp()),
            repository_hash=REPOSITORY_HASH,
            task_hash=TASK_HASH,
            policy_hash=POLICY_HASH,
            creation_tx_hash="0x" + f"{job_id:064x}",
        )

    def _create_agent(self, slug: str, wallet: str, sequence: int):
        owner = User.objects.create_user(handle=f"owner-{slug}")
        worker = WorkerAgent.objects.create(
            slug=slug,
            name=slug.replace("-", " ").title(),
            description="Flask execution agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=owner,
            status=WorkerAgent.Status.ACTIVE,
            specialisation=WorkerAgent.Specialisation.PYTHON_BACKEND,
            languages=["Python"],
            frameworks=["Flask"],
            testing_tools=["Pytest"],
            task_types=["API endpoint"],
            skills=["Python", "Flask", "Pytest", "API endpoint"],
            minimum_budget_usdc="1.000000",
            maximum_budget_usdc="5.000000",
            auto_claim_enabled=True,
            discovery_enabled=True,
            maximum_active_jobs=1,
            maximum_execution_minutes=45,
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="zai-org/glm-5.2",
            engine_connected=True,
            engine_version="test-runtime/1.0",
            engine_last_checked_at=timezone.now(),
            circle_wallet_id=f"circle-wallet-{sequence}",
            circle_wallet_set_id="worker-wallet-set",
            worker_wallet_address=wallet,
            payout_wallet_address=wallet,
            contract_authorised=True,
            test_assignment_passed=True,
            activated_at=timezone.now(),
        )
        private_key = Ed25519PrivateKey.generate()
        public_key = _b64url(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        connection = HostedAgentConnection.objects.create(
            worker=worker,
            runtime_id=f"runtime-{sequence}",
            runtime_url="http://localhost:9100",
            public_key=public_key,
            public_key_fingerprint=f"{sequence:064x}",
            protocol_version=1,
            runtime_version="test-runtime/1.0",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={"coding": True, "testing": True},
            credential_hash=f"{sequence + 10:064x}",
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        return worker, connection, private_key

    def _discover_side_effect(self, worker, job, **kwargs):
        item, _ = WorkerJobQueueItem.objects.update_or_create(
            worker=worker,
            job=job,
            defaults={
                "status": WorkerJobQueueItem.Status.QUEUED,
                "source": WorkerJobQueueItem.Source.FAST_PATH,
                "eligibility_passed": True,
                "eligibility_code": "ELIGIBLE",
                "eligibility_detail": "Policy and skills match.",
                "priority_score": 1000,
                "required_skills": ["Python", "Flask", "Pytest"],
                "matched_skills": ["Python", "Flask", "Pytest"],
                "onchain_status": "FUNDED",
                "queued_at": timezone.now(),
                "last_checked_at": timezone.now(),
            },
        )
        return SimpleNamespace(
            status=WorkerJobQueueItem.Status.QUEUED,
            queue_item_id=str(item.id),
        )

    def _claimed_assignment(self, worker: WorkerAgent) -> WorkerJobAssignment:
        item = WorkerJobQueueItem.objects.create(
            worker=worker,
            job=self.job,
            status=WorkerJobQueueItem.Status.CLAIMED,
            source=WorkerJobQueueItem.Source.FAST_PATH,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            priority_score=1000,
            required_skills=["Python", "Flask", "Pytest"],
            matched_skills=["Python", "Flask", "Pytest"],
            onchain_status="CLAIMED",
            claim_arc_transaction_hash="0x" + "aa" * 32,
            claim_confirmed_at=timezone.now(),
        )
        return WorkerJobAssignment.objects.create(
            job=self.job,
            worker=worker,
            queue_item=item,
            status=WorkerJobAssignment.Status.CLAIMED,
            reserved_until=timezone.now() + timedelta(seconds=90),
            matching_score=2500,
            candidate_count=2,
        )

    @patch("workers.execution_matching.discover_job")
    def test_two_qualified_agents_create_only_one_authoritative_assignment(self, discover):
        discover.side_effect = self._discover_side_effect

        first = reserve_best_agent_for_job(self.job)
        second = reserve_best_agent_for_job(self.job)

        self.assertIsNotNone(first)
        self.assertEqual(first.id, second.id)
        self.assertEqual(WorkerJobAssignment.objects.filter(job=self.job).count(), 1)
        self.assertEqual(first.candidate_count, 2)

    @patch("workers.execution_matching.discover_job")
    def test_fairness_band_prefers_agent_with_less_recent_work(self, discover):
        discover.side_effect = self._discover_side_effect
        old_job = self._create_job(101)
        old_item = WorkerJobQueueItem.objects.create(
            worker=self.agent_one,
            job=old_job,
            status=WorkerJobQueueItem.Status.QUEUED,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            priority_score=1000,
            required_skills=["Python"],
            matched_skills=["Python"],
        )
        WorkerJobAssignment.objects.create(
            job=old_job,
            worker=self.agent_one,
            queue_item=old_item,
            status=WorkerJobAssignment.Status.COMPLETED,
            reserved_until=timezone.now(),
            completed_at=timezone.now(),
        )

        assignment = reserve_best_agent_for_job(self.job)

        self.assertEqual(assignment.worker_id, self.agent_two.id)
        self.assertEqual(assignment.fairness_rank, 1)

    @patch("workers.execution_matching.discover_job")
    def test_failed_old_assignment_does_not_consume_capacity(self, discover):
        discover.side_effect = self._discover_side_effect
        old_job = self._create_job(102)
        old_item = WorkerJobQueueItem.objects.create(
            worker=self.agent_one,
            job=old_job,
            status=WorkerJobQueueItem.Status.DEFERRED,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            priority_score=1000,
        )
        WorkerJobQueueItem.objects.filter(pk=old_item.pk).update(
            status=WorkerJobQueueItem.Status.SUBMISSION_PENDING
        )
        WorkerJobAssignment.objects.create(
            job=old_job,
            worker=self.agent_one,
            queue_item=old_item,
            status=WorkerJobAssignment.Status.FAILED,
            reserved_until=timezone.now(),
            failure_stage="submission_failed",
        )
        self.connection_two.provider_ready = False
        self.connection_two.save(update_fields=["provider_ready", "updated_at"])

        assignment = reserve_best_agent_for_job(self.job)

        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.worker_id, self.agent_one.id)
        _validate_queue_for_preflight(assignment.queue_item)

    @patch("workers.execution_matching.discover_job")
    def test_submitted_assignment_releases_coding_capacity_for_next_job(self, discover):
        discover.side_effect = self._discover_side_effect
        old_job = self._create_job(103)
        old_item = WorkerJobQueueItem.objects.create(
            worker=self.agent_one,
            job=old_job,
            status=WorkerJobQueueItem.Status.SUBMITTED,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            priority_score=1000,
            onchain_status="SUBMITTED",
            claim_arc_transaction_hash="0x" + "ab" * 32,
            claim_confirmed_at=timezone.now(),
            execution_post_test_passed=True,
            execution_commit_sha="c" * 40,
            execution_pull_request_number=43,
            execution_pull_request_url="https://github.com/example/flask-repo/pull/43",
            submission_commit_hash="0x" + "cc" * 32,
            submission_deliverable_hash="0x" + "dd" * 32,
            submission_arc_transaction_hash="0x" + "ee" * 32,
            submission_confirmed_at=timezone.now(),
        )
        WorkerJobAssignment.objects.create(
            job=old_job,
            worker=self.agent_one,
            queue_item=old_item,
            status=WorkerJobAssignment.Status.VERIFYING,
            reserved_until=timezone.now(),
        )
        self.connection_two.provider_ready = False
        self.connection_two.save(update_fields=["provider_ready", "updated_at"])

        assignment = reserve_best_agent_for_job(self.job)

        self.assertEqual(active_assignment_count(self.agent_one), 1)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.worker_id, self.agent_one.id)

    def test_result_received_still_consumes_coding_capacity(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.status = WorkerJobAssignment.Status.RESULT_RECEIVED
        assignment.save(update_fields=["status", "updated_at"])

        self.assertEqual(active_assignment_count(self.agent_one), 1)

    def test_submitting_still_consumes_coding_capacity(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.status = WorkerJobAssignment.Status.SUBMITTING
        assignment.save(update_fields=["status", "updated_at"])

        self.assertEqual(active_assignment_count(self.agent_one), 1)

    def test_submitted_releases_coding_capacity(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.status = WorkerJobAssignment.Status.SUBMITTED
        assignment.save(update_fields=["status", "updated_at"])

        self.assertEqual(active_assignment_count(self.agent_one), 0)

    def _online_execution_layer(self):
        now = timezone.now()
        return ExecutionLayerState.objects.create(
            key="default",
            running=True,
            cycle_number=1,
            last_cycle_started_at=now,
            last_cycle_finished_at=now,
            next_cycle_at=now + timedelta(seconds=5),
            lease_expires_at=now + timedelta(seconds=120),
        )

    def test_job_status_reports_execution_layer_offline(self):
        snapshot = job_execution_snapshot(self.job)
        self.assertEqual(snapshot["matching_status"], "PAUSED")
        self.assertEqual(
            snapshot["matching_reason_code"],
            "EXECUTION_LAYER_OFFLINE",
        )

    def test_job_status_reports_active_matching(self):
        self._online_execution_layer()
        snapshot = job_execution_snapshot(self.job)
        self.assertEqual(snapshot["matching_status"], "MATCHING")

    def test_job_status_reports_retryable_matching_error(self):
        self._online_execution_layer()
        WorkerJobQueueItem.objects.create(
            worker=self.agent_one,
            job=self.job,
            status=WorkerJobQueueItem.Status.DEFERRED,
            eligibility_code="GITHUB_READ_FAILED",
            eligibility_detail="GitHub is temporarily unavailable. Veyra will retry.",
            matching_retry_count=1,
            matching_next_retry_at=timezone.now() + timedelta(seconds=30),
        )
        snapshot = job_execution_snapshot(self.job)
        self.assertEqual(snapshot["matching_status"], "RETRYING")
        self.assertEqual(snapshot["matching_reason_code"], "GITHUB_READ_FAILED")
        self.assertIsNotNone(snapshot["matching_next_retry_at"])

    def test_job_status_reports_no_eligible_agent_reason(self):
        self._online_execution_layer()
        WorkerJobQueueItem.objects.create(
            worker=self.agent_one,
            job=self.job,
            status=WorkerJobQueueItem.Status.INELIGIBLE,
            eligibility_code="SKILLS_MISMATCH",
            eligibility_detail="The worker does not match all required skills.",
        )
        snapshot = job_execution_snapshot(self.job)
        self.assertEqual(snapshot["matching_status"], "NO_ELIGIBLE_AGENT")
        self.assertEqual(snapshot["matching_reason_code"], "SKILLS_MISMATCH")

    def test_only_claimed_agent_receives_one_signed_runtime_lease(self):
        assignment = self._claimed_assignment(self.agent_one)

        task = execution_task_for_connection(self.connection_one)
        other_task = execution_task_for_connection(self.connection_two)

        assignment.refresh_from_db()
        assignment.queue_item.refresh_from_db()
        self.assertIsNotNone(task)
        self.assertIsNone(other_task)
        self.assertEqual(str(task["id"]), str(assignment.id))
        self.assertEqual(assignment.status, WorkerJobAssignment.Status.LEASED)
        self.assertEqual(assignment.queue_item.status, WorkerJobQueueItem.Status.LEASED)
        self.assertTrue(task["lease_token"])
        self.assertNotIn("token", task["repository"])

    def test_expired_claim_is_failed_before_runtime_lease(self):
        assignment = self._claimed_assignment(self.agent_one)
        self.job.claim_deadline = int(
            (timezone.now() - timedelta(seconds=1)).timestamp()
        )
        self.job.save(update_fields=["claim_deadline", "updated_at"])

        task = execution_task_for_connection(self.connection_one)

        assignment.refresh_from_db()
        assignment.queue_item.refresh_from_db()
        self.assertIsNone(task)
        self.assertEqual(assignment.status, WorkerJobAssignment.Status.FAILED)
        self.assertEqual(assignment.failure_stage, "claim_deadline_expired")
        self.assertEqual(
            assignment.queue_item.status,
            WorkerJobQueueItem.Status.FAILED,
        )
        self.assertEqual(
            assignment.queue_item.execution_failure_stage,
            "claim_deadline_expired",
        )

    def test_retryable_runtime_failure_is_requeued_without_duplicate_claim(self):
        assignment = self._claimed_assignment(self.agent_one)
        original_claim_hash = assignment.queue_item.claim_arc_transaction_hash
        assignment.status = WorkerJobAssignment.Status.FAILED
        assignment.assignment_attempt = 2
        assignment.failure_stage = "runtime_execution"
        assignment.failure_message = (
            "[WinError 2] The system cannot find the file specified"
        )
        assignment.save(
            update_fields=[
                "status",
                "assignment_attempt",
                "failure_stage",
                "failure_message",
                "updated_at",
            ]
        )
        WorkerJobQueueItem.objects.filter(pk=assignment.queue_item_id).update(
            status=WorkerJobQueueItem.Status.FAILED,
            execution_failure_stage="runtime_execution",
            execution_failure_message=assignment.failure_message,
        )

        recovered = recover_retryable_runtime_failures(cycle_number=7)

        assignment.refresh_from_db()
        assignment.queue_item.refresh_from_db()
        self.assertEqual(recovered, 1)
        self.assertEqual(assignment.status, WorkerJobAssignment.Status.CLAIMED)
        self.assertEqual(assignment.assignment_attempt, 3)
        self.assertEqual(
            assignment.queue_item.status,
            WorkerJobQueueItem.Status.CLAIMED,
        )
        self.assertEqual(
            assignment.queue_item.claim_arc_transaction_hash,
            original_claim_hash,
        )
        self.assertEqual(assignment.failure_stage, "")
        self.assertEqual(active_assignment_count(self.agent_one), 1)

        self.assertEqual(recover_retryable_runtime_failures(cycle_number=8), 0)

    def test_legacy_json_decode_failure_is_retryable_and_publicly_normalised(self):
        assignment = self._claimed_assignment(self.agent_one)
        original_claim_hash = assignment.queue_item.claim_arc_transaction_hash
        assignment.status = WorkerJobAssignment.Status.FAILED
        assignment.failure_stage = "runtime_execution"
        assignment.failure_message = "Expecting value: line 1 column 12 (char 11)"
        assignment.save(
            update_fields=["status", "failure_stage", "failure_message", "updated_at"]
        )
        item = assignment.queue_item
        item.status = WorkerJobQueueItem.Status.FAILED
        item.execution_failure_stage = assignment.failure_stage
        item.execution_failure_message = assignment.failure_message
        item.save(
            update_fields=[
                "status",
                "execution_failure_stage",
                "execution_failure_message",
                "updated_at",
            ]
        )

        snapshot = assignment_public_snapshot(assignment)
        self.assertEqual(snapshot["failure_stage"], "AI_RESPONSE_INVALID")
        self.assertNotIn("Expecting value", snapshot["failure_message"])

        self.assertEqual(recover_retryable_runtime_failures(cycle_number=10), 1)
        assignment.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(assignment.status, WorkerJobAssignment.Status.CLAIMED)
        self.assertEqual(item.claim_arc_transaction_hash, original_claim_hash)
        self.assertFalse(item.execution_commit_sha)
        self.assertIsNone(item.execution_pull_request_number)
        self.assertFalse(item.submission_arc_transaction_hash)

    def test_explicit_runtime_retry_is_idempotent_and_preserves_claim_identity(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.status = WorkerJobAssignment.Status.FAILED
        assignment.assignment_attempt = 1
        assignment.failure_stage = "runtime_execution"
        assignment.failure_message = "Expecting value: line 1 column 12 (char 11)"
        assignment.save(
            update_fields=[
                "status", "assignment_attempt", "failure_stage",
                "failure_message", "updated_at",
            ]
        )
        item = assignment.queue_item
        item.status = WorkerJobQueueItem.Status.FAILED
        item.execution_failure_stage = assignment.failure_stage
        item.execution_failure_message = assignment.failure_message
        item.save(
            update_fields=[
                "status", "execution_failure_stage",
                "execution_failure_message", "updated_at",
            ]
        )
        original_assignment_id = assignment.id
        original_queue_id = item.id
        original_claim_hash = item.claim_arc_transaction_hash

        retried, changed = retry_existing_runtime_assignment(assignment)
        repeated, repeated_changed = retry_existing_runtime_assignment(retried)

        item.refresh_from_db()
        self.assertTrue(changed)
        self.assertFalse(repeated_changed)
        self.assertEqual(retried.id, original_assignment_id)
        self.assertEqual(repeated.id, original_assignment_id)
        self.assertEqual(item.id, original_queue_id)
        self.assertEqual(item.claim_arc_transaction_hash, original_claim_hash)
        self.assertEqual(repeated.assignment_attempt, 2)
        self.assertEqual(active_assignment_count(self.agent_one), 1)
        self.assertEqual(WorkerJobAssignment.objects.filter(job=self.job).count(), 1)
        self.assertEqual(WorkerJobQueueItem.objects.filter(job=self.job).count(), 1)
        self.assertFalse(item.submission_arc_transaction_hash)
        self.assertFalse(item.execution_commit_sha)

    def test_execution_controller_database_lease_blocks_duplicate_and_recovers_after_release(self):
        first = claim_controller()

        with self.assertRaisesRegex(RuntimeError, "active database lease"):
            claim_controller()

        release_controller(first)
        second = claim_controller()
        self.assertNotEqual(first, second)
        release_controller(second)

    @override_settings(VEYRA_JOB_MAX_RUNTIME_ATTEMPTS=2)
    def test_retryable_runtime_failure_stops_at_attempt_limit(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.status = WorkerJobAssignment.Status.FAILED
        assignment.assignment_attempt = 2
        assignment.failure_stage = "runtime_execution"
        assignment.failure_message = "[WinError 2] missing executable"
        assignment.save(
            update_fields=[
                "status",
                "assignment_attempt",
                "failure_stage",
                "failure_message",
                "updated_at",
            ]
        )

        self.assertEqual(recover_retryable_runtime_failures(cycle_number=9), 0)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, WorkerJobAssignment.Status.FAILED)

    def test_completed_assignment_hides_recovered_rpc_error_from_active_error(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.status = WorkerJobAssignment.Status.COMPLETED
        assignment.failure_stage = "verification_infrastructure"
        assignment.failure_message = "429 Too Many Requests"
        assignment.completed_at = timezone.now()
        assignment.save(
            update_fields=[
                "status",
                "failure_stage",
                "failure_message",
                "completed_at",
                "updated_at",
            ]
        )

        snapshot = assignment_public_snapshot(assignment)

        self.assertEqual(snapshot["failure_stage"], "")
        self.assertEqual(snapshot["failure_message"], "")
        self.assertEqual(
            snapshot["failure_history"][-1]["stage"],
            "verification_infrastructure",
        )

    def test_successful_settlement_clears_active_errors_into_history(self):
        assignment = self._claimed_assignment(self.agent_one)
        assignment.failure_stage = "verification_pending"
        assignment.failure_message = "Arc RPC providers are temporarily unavailable."
        assignment.queue_item.submission_failure_stage = "arc_receipt_pending"
        assignment.queue_item.submission_failure_message = "429 Too Many Requests"

        _clear_recovered_failures(assignment, assignment.queue_item)

        self.assertEqual(assignment.failure_stage, "")
        self.assertEqual(assignment.failure_message, "")
        self.assertEqual(assignment.queue_item.submission_failure_stage, "")
        self.assertEqual(len(assignment.failure_history), 2)
        self.assertEqual(
            {entry["source"] for entry in assignment.failure_history},
            {"assignment", "submission"},
        )

    def _signed_payload(self, assignment, task, private_key, *, outcome="SUCCEEDED"):
        if outcome == "FAILED":
            evidence = {
                "outcome": "FAILED",
                "assignment_id": str(assignment.id),
                "lease_id": str(assignment.execution_lease_id),
                "job_id": int(self.job.onchain_job_id),
                "failure_stage": "runtime_execution",
                "failure_message": "The controlled model run failed safely.",
                "summary": "No work was submitted.",
            }
        else:
            evidence = {
                "outcome": "SUCCEEDED",
                "assignment_id": str(assignment.id),
                "lease_id": str(assignment.execution_lease_id),
                "job_id": int(self.job.onchain_job_id),
                "branch": assignment.queue_item.execution_branch_name,
                "base_branch": "main",
                "base_commit_sha": "b" * 40,
                "commit_sha": "c" * 40,
                "pull_request_number": 42,
                "pull_request_url": "https://github.com/example/flask-repo/pull/42",
                "changed_files": ["app.py", "tests/test_app.py"],
                "baseline_test_command": "python -m pytest -q",
                "baseline_test_return_code": 0,
                "baseline_test_output": "2 passed",
                "test_command": "python -m pytest -q",
                "test_return_code": 0,
                "test_output": "3 passed",
                "repair_attempts": 0,
                "provider": "aiand",
                "model": "zai-org/glm-5.2",
                "runtime_version": "test-runtime/1.0",
                "summary": "Added the endpoint and tests.",
            }
        evidence_hash = "0x" + hashlib.sha256(
            canonical_json(evidence).encode("utf-8")
        ).hexdigest()
        message = (
            f"veyra-job-result-v1:{assignment.id}:{assignment.execution_lease_id}:{evidence_hash}"
        ).encode("utf-8")
        signature = _b64url(private_key.sign(message))
        return {
            "assignment_id": str(assignment.id),
            "lease_token": task["lease_token"],
            "evidence": evidence,
            "evidence_hash": evidence_hash,
            "signature": signature,
        }

    @patch("workers.execution_transport.GitHubAppExecutionClient.for_job")
    def test_signed_exact_pull_request_result_is_accepted_once(self, github_for_job):
        assignment = self._claimed_assignment(self.agent_one)
        task = execution_task_for_connection(self.connection_one)
        assignment.refresh_from_db()
        assignment.queue_item.refresh_from_db()
        github_for_job.return_value.pull_request.return_value = PullRequestSnapshot(
            number=42,
            html_url="https://github.com/example/flask-repo/pull/42",
            state="open",
            merged=False,
            head_ref=assignment.queue_item.execution_branch_name,
            head_sha="c" * 40,
            base_ref="main",
            changed_files=("app.py", "tests/test_app.py"),
        )
        payload = self._signed_payload(assignment, task, self.key_one)

        first = submit_execution_result(connection=self.connection_one, payload=payload)
        second = submit_execution_result(connection=self.connection_one, payload=payload)

        first.refresh_from_db()
        first.queue_item.refresh_from_db()
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, WorkerJobAssignment.Status.RESULT_RECEIVED)
        self.assertEqual(first.queue_item.status, WorkerJobQueueItem.Status.SUBMISSION_PENDING)
        self.assertTrue(first.queue_item.execution_post_test_passed)
        self.assertEqual(first.queue_item.execution_commit_sha, "c" * 40)

    def test_signed_runtime_failure_never_enters_payment_pipeline(self):
        assignment = self._claimed_assignment(self.agent_one)
        task = execution_task_for_connection(self.connection_one)
        assignment.refresh_from_db()
        payload = self._signed_payload(
            assignment, task, self.key_one, outcome="FAILED"
        )

        result = submit_execution_result(connection=self.connection_one, payload=payload)

        result.refresh_from_db()
        result.queue_item.refresh_from_db()
        self.assertEqual(result.status, WorkerJobAssignment.Status.FAILED)
        self.assertEqual(result.queue_item.status, WorkerJobQueueItem.Status.FAILED)
        self.assertFalse(result.queue_item.execution_post_test_passed)
        self.assertFalse(result.settlement_transaction_hash)

    @patch("workers.execution_verification.GitHubAppExecutionClient.for_job")
    def test_independent_github_check_is_required_before_settlement(self, github_for_job):
        snapshot = self.job.draft.funding_snapshot
        snapshot.policy_commitment = {
            **snapshot.policy_commitment,
            "requireGithubChecks": True,
        }
        snapshot.save(update_fields=["policy_commitment"])
        assignment = self._claimed_assignment(self.agent_one)
        task = execution_task_for_connection(self.connection_one)
        assignment.refresh_from_db()
        assignment.queue_item.refresh_from_db()
        github_for_job.return_value.pull_request.return_value = PullRequestSnapshot(
            number=42,
            html_url="https://github.com/example/flask-repo/pull/42",
            state="open",
            merged=False,
            head_ref=assignment.queue_item.execution_branch_name,
            head_sha="c" * 40,
            base_ref="main",
            changed_files=("app.py", "tests/test_app.py"),
        )
        payload = self._signed_payload(assignment, task, self.key_one)
        submit_execution_result(connection=self.connection_one, payload=payload)
        assignment.refresh_from_db()
        assignment.queue_item.status = WorkerJobQueueItem.Status.SUBMITTED
        assignment.queue_item.onchain_status = "SUBMITTED"
        assignment.queue_item.submission_commit_hash = "0x" + "cc" * 32
        assignment.queue_item.submission_deliverable_hash = "0x" + "dd" * 32
        assignment.queue_item.submission_arc_transaction_hash = "0x" + "ee" * 32
        assignment.queue_item.submission_confirmed_at = timezone.now()
        assignment.queue_item.save()
        assignment.status = WorkerJobAssignment.Status.SUBMITTED
        assignment.save(update_fields=["status", "updated_at"])
        github_for_job.return_value.check_runs.return_value = []

        with self.assertRaises(ExecutionVerificationPending):
            _verification_report(assignment)
