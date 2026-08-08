from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserCapability
from jobs.models import JobDraft, VeyraJob
from workers.models import WorkerAgent, WorkerJobAssignment, WorkerJobQueueItem


@override_settings(VEYRA_JOB_MAX_RUNTIME_ATTEMPTS=3)
class RetryExecutionApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(handle="retry-client")
        UserCapability.objects.create(
            user=self.user,
            code=UserCapability.Code.CLIENT,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        deadline = timezone.now() + timedelta(hours=2)
        draft = JobDraft.objects.create(
            client=self.user,
            status=JobDraft.Status.FUNDED,
            github_issue_url="https://github.com/owner/repo/issues/5",
            repository_owner="owner",
            repository_name="repo",
            target_branch="main",
            issue_number=5,
            issue_title="Issue five",
            issue_body="Repair the requested behavior.",
            budget_usdc="3.000000",
            deadline=deadline,
            acceptance_criteria=["Tests pass"],
        )
        self.job = VeyraJob.objects.create(
            client=self.user,
            draft=draft,
            onchain_job_id=5,
            status="FUNDED",
            client_status="OPEN",
            client_address="0x" + "11" * 20,
            invited_provider_address="0x" + "00" * 20,
            provider_address="0x" + "22" * 20,
            verifier_address="0x" + "33" * 20,
            budget_atomic=3_000_000,
            expires_at=int(deadline.timestamp()),
            claim_deadline=int(deadline.timestamp()),
            repository_hash="0x" + "44" * 32,
            task_hash="0x" + "55" * 32,
            policy_hash="0x" + "66" * 32,
            creation_tx_hash="0x" + "77" * 32,
        )
        owner = User.objects.create_user(handle="retry-owner")
        worker = WorkerAgent.objects.create(
            slug="retry-worker",
            name="Retry Worker",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=owner,
            status=WorkerAgent.Status.PROFILE_READY,
            specialisation=WorkerAgent.Specialisation.PYTHON_BACKEND,
            skills=["python"],
            minimum_budget_usdc="1.000000",
            maximum_budget_usdc="5.000000",
            worker_wallet_address="0x" + "22" * 20,
            payout_wallet_address="0x" + "22" * 20,
        )
        self.item = WorkerJobQueueItem.objects.create(
            worker=worker,
            job=self.job,
            status=WorkerJobQueueItem.Status.FAILED,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            claim_arc_transaction_hash="0x" + "aa" * 32,
            claim_confirmed_at=timezone.now(),
            execution_failure_stage="runtime_execution",
            execution_failure_message="Expecting value: line 1 column 12 (char 11)",
        )
        self.assignment = WorkerJobAssignment.objects.create(
            job=self.job,
            worker=worker,
            queue_item=self.item,
            status=WorkerJobAssignment.Status.FAILED,
            assignment_attempt=1,
            reserved_until=timezone.now() + timedelta(minutes=5),
            failure_stage="runtime_execution",
            failure_message="Expecting value: line 1 column 12 (char 11)",
        )

    def test_retry_endpoint_reuses_existing_job_assignment_and_claim(self):
        assignment_id = self.assignment.id
        claim_hash = self.item.claim_arc_transaction_hash

        first = self.client.post("/api/v1/client/jobs/5/retry-execution/", {}, format="json")
        second = self.client.post("/api/v1/client/jobs/5/retry-execution/", {}, format="json")

        self.assignment.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["code"], "EXECUTION_RETRY_SCHEDULED")
        self.assertTrue(first.data["claim_preserved"])
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["code"], "EXECUTION_RETRY_ALREADY_SCHEDULED")
        self.assertEqual(self.assignment.id, assignment_id)
        self.assertEqual(self.assignment.assignment_attempt, 2)
        self.assertEqual(self.item.claim_arc_transaction_hash, claim_hash)
        self.assertEqual(VeyraJob.objects.filter(draft__issue_number=5).count(), 1)
        self.assertEqual(WorkerJobAssignment.objects.filter(job=self.job).count(), 1)
        self.assertFalse(self.item.submission_arc_transaction_hash)
        self.assertFalse(self.item.execution_commit_sha)