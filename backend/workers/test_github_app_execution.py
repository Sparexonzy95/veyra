from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from accounts.models import User
from jobs.models import GitHubAppInstallation, GitHubRepositoryAccess, JobDraft, VeyraJob
from workers.execution import _github_for_item
from workers.models import WorkerAgent, WorkerJobQueueItem


class GitHubAppExecutionCredentialTests(TestCase):
    @patch("workers.execution.token_for_repository")
    def test_paid_job_uses_repository_scoped_installation_token(self, token_for_repository):
        user = User.objects.create_user(display_name="Client")
        installation = GitHubAppInstallation.objects.create(
            client=user,
            installation_id=6001,
            account_id=6002,
            account_login="client-org",
            status=GitHubAppInstallation.Status.CONNECTED,
        )
        repository = GitHubRepositoryAccess.objects.create(
            installation=installation,
            github_repository_id=6003,
            owner="client-org",
            name="api",
            full_name="client-org/api",
        )
        draft = JobDraft.objects.create(
            client=user,
            github_issue_url="https://github.com/client-org/api/issues/1",
            github_repository_access=repository,
            repository_owner="client-org",
            repository_name="api",
            issue_number=1,
            issue_title="Fix endpoint",
            budget_usdc="1.000000",
            deadline=timezone.now() + timedelta(days=1),
            acceptance_criteria=["Tests pass"],
        )
        job = VeyraJob.objects.create(
            client=user,
            draft=draft,
            onchain_job_id=1,
            status="CLAIMED",
            client_status="AGENT_WORKING",
            client_address="0x1111111111111111111111111111111111111111",
            invited_provider_address="0x0000000000000000000000000000000000000000",
            provider_address="0x2222222222222222222222222222222222222222",
            verifier_address="0x3333333333333333333333333333333333333333",
            budget_atomic=1000000,
            expires_at=2000000000,
            repository_hash="0x" + "11" * 32,
            task_hash="0x" + "22" * 32,
            policy_hash="0x" + "33" * 32,
        )
        worker = WorkerAgent.objects.create(
            slug="hosted-worker",
            name="Hosted worker",
            owner_type=WorkerAgent.OwnerType.VEYRA,
            skills=["Python"],
        )
        queue_item = WorkerJobQueueItem.objects.create(worker=worker, job=job)
        queue_item = WorkerJobQueueItem.objects.select_related(
            "job__draft__github_repository_access__installation"
        ).get(pk=queue_item.pk)
        token_for_repository.return_value = SimpleNamespace(token="short-lived-token")

        client, app_mode = _github_for_item(queue_item)

        self.assertTrue(app_mode)
        self.assertEqual(client.token, "short-lived-token")
        self.assertEqual(client.username, "client-org")
        token_for_repository.assert_called_once_with(repository)
