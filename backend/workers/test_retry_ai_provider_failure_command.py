from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from jobs.models import JobDraft, VeyraJob
from workers.models import WorkerAgent, WorkerJobAssignment, WorkerJobQueueItem


class RetryAiProviderFailureCommandTests(TestCase):
    def setUp(self):
        client = User.objects.create_user(handle="command-client")
        owner = User.objects.create_user(handle="command-owner")
        deadline = timezone.now() + timedelta(hours=2)
        draft = JobDraft.objects.create(
            client=client,
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
            client=client,
            draft=draft,
            onchain_job_id=5,
            status="CLAIMED",
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
        worker = WorkerAgent.objects.create(
            slug="command-worker",
            name="Command Worker",
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
            execution_attempt_count=3,
            execution_failure_stage="runtime_execution",
            execution_failure_message="The read operation timed out",
        )
        self.assignment = WorkerJobAssignment.objects.create(
            job=self.job,
            worker=worker,
            queue_item=self.item,
            status=WorkerJobAssignment.Status.FAILED,
            assignment_attempt=4,
            reserved_until=timezone.now() + timedelta(minutes=5),
            failure_stage="runtime_execution",
            failure_message="The read operation timed out",
        )

    def test_replay_preserves_current_attempt_and_claim_identity(self):
        assignment_id = self.assignment.id
        queue_item_id = self.item.id
        claim_hash = self.item.claim_arc_transaction_hash
        output = StringIO()

        call_command(
            "retry_ai_provider_failure",
            repository="owner/repo",
            issue=5,
            reuse_current_attempt=True,
            stdout=output,
        )
        call_command(
            "retry_ai_provider_failure",
            repository="owner/repo",
            issue=5,
            reuse_current_attempt=True,
            stdout=output,
        )

        self.assignment.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.assignment.id, assignment_id)
        self.assertEqual(self.item.id, queue_item_id)
        self.assertEqual(self.assignment.status, WorkerJobAssignment.Status.CLAIMED)
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.CLAIMED)
        self.assertEqual(self.assignment.assignment_attempt, 4)
        self.assertEqual(self.item.execution_attempt_count, 3)
        self.assertEqual(self.item.claim_arc_transaction_hash, claim_hash)
        self.assertIsNone(self.assignment.execution_lease_id)
        self.assertEqual(WorkerJobAssignment.objects.filter(job=self.job).count(), 1)
        self.assertEqual(WorkerJobQueueItem.objects.filter(job=self.job).count(), 1)
        self.assertIn("Platform attempt: 4 (replayed)", output.getvalue())
        self.assertIn("already recovered", output.getvalue())

    def test_replay_accepts_repaired_funded_path_id_failure(self):
        self.assignment.failure_message = (
            "The AI model returned an unknown funded path ID: app.py"
        )
        self.assignment.save(update_fields=["failure_message", "updated_at"])

        call_command(
            "retry_ai_provider_failure",
            repository="owner/repo",
            issue=5,
            reuse_current_attempt=True,
        )

        self.assignment.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.assignment.status, WorkerJobAssignment.Status.CLAIMED)
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.CLAIMED)
        self.assertEqual(self.assignment.assignment_attempt, 4)
        self.assertEqual(self.item.execution_attempt_count, 3)