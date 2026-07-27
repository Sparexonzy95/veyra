from __future__ import annotations

import json
from datetime import timedelta

import httpx
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from jobs.models import JobDraft, VeyraJob
from workers.github_freshness import GitHubFreshnessGuard
from workers.models import WorkerAgent


WORKER = "0x2222222222222222222222222222222222222222"


@override_settings(GITHUB_API_URL="https://api.github.test")
class GitHubFreshnessGuardTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(handle="github-freshness-client")
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            description="Autonomous coding worker",
            status=WorkerAgent.Status.ACTIVE,
            skills=["Python"],
            engine_provider=WorkerAgent.EngineProvider.OPENCODE,
            engine_model="aiand/zai-org/glm-5.2",
            engine_connected=True,
            engine_version="1.17.18",
            engine_last_checked_at=timezone.now(),
            circle_wallet_id="wallet-id-freshness",
            circle_wallet_set_id="wallet-set-id",
            worker_wallet_address=WORKER,
            payout_wallet_address=WORKER,
            github_username="logicbloomlab",
            github_connected=True,
            contract_authorised=True,
            test_assignment_passed=True,
        )
        draft = JobDraft.objects.create(
            client=user,
            status=JobDraft.Status.FUNDED,
            github_issue_url="https://github.com/example/repo/issues/1",
            repository_owner="example",
            repository_name="repo",
            target_branch="main",
            issue_number=1,
            issue_title="Implement endpoint",
            issue_body="Build it.",
            budget_usdc="1.000000",
            deadline=timezone.now() + timedelta(hours=3),
            acceptance_criteria=["Tests pass"],
            advanced_options={},
        )
        self.job = VeyraJob.objects.create(
            client=user,
            draft=draft,
            onchain_job_id=3,
            status="FUNDED",
            client_status="OPEN",
            client_address="0x1111111111111111111111111111111111111111",
            invited_provider_address="0x0000000000000000000000000000000000000000",
            verifier_address="0x3333333333333333333333333333333333333333",
            budget_atomic=1_000_000,
            expires_at=int((timezone.now() + timedelta(hours=3)).timestamp()),
            repository_hash="0x" + "11" * 32,
            task_hash="0x" + "22" * 32,
            policy_hash="0x" + "33" * 32,
        )

    @staticmethod
    def _json(payload, status=200):
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
        )

    def _guard(self, handler):
        return GitHubFreshnessGuard(
            token="test-token",
            api_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        )

    def test_open_issue_without_worker_pr_or_fork_is_fresh(self):
        def handler(request):
            if request.url.path.endswith("/issues/1"):
                return self._json(
                    {
                        "number": 1,
                        "state": "open",
                        "html_url": "https://github.com/example/repo/issues/1",
                    }
                )
            if request.url.path.endswith("/pulls"):
                return self._json([])
            if request.url.path.endswith("/repos/logicbloomlab/repo"):
                return self._json({"message": "Not Found"}, status=404)
            raise AssertionError(request.url)

        result = self._guard(handler).check(self.worker, self.job)

        self.assertTrue(result.passed)
        self.assertEqual(result.code, "GITHUB_FRESH")
        self.assertEqual(result.issue_state, "OPEN")

    def test_open_worker_pull_request_blocks_issue(self):
        def handler(request):
            if request.url.path.endswith("/issues/1"):
                return self._json(
                    {
                        "number": 1,
                        "state": "open",
                        "html_url": "https://github.com/example/repo/issues/1",
                    }
                )
            if request.url.path.endswith("/pulls"):
                return self._json(
                    [
                        {
                            "state": "open",
                            "merged_at": None,
                            "html_url": "https://github.com/example/repo/pull/2",
                            "body": "Closes #1",
                            "head": {
                                "ref": "veyra/test-issue-1-1234",
                                "user": {"login": "logicbloomlab"},
                                "repo": {
                                    "owner": {"login": "logicbloomlab"}
                                },
                            },
                        }
                    ]
                )
            raise AssertionError(request.url)

        result = self._guard(handler).check(self.worker, self.job)

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "GITHUB_WORKER_PR_OPEN")
        self.assertEqual(
            result.existing_pull_request_url,
            "https://github.com/example/repo/pull/2",
        )

    def test_existing_worker_branch_blocks_issue(self):
        def handler(request):
            if request.url.path.endswith("/issues/1"):
                return self._json(
                    {
                        "number": 1,
                        "state": "open",
                        "html_url": "https://github.com/example/repo/issues/1",
                    }
                )
            if request.url.path.endswith("/pulls"):
                return self._json([])
            if request.url.path.endswith("/repos/logicbloomlab/repo"):
                return self._json(
                    {
                        "fork": True,
                        "full_name": "logicbloomlab/repo",
                        "parent": {"full_name": "example/repo"},
                    }
                )
            if request.url.path.endswith("/branches"):
                return self._json(
                    [
                        {"name": "main"},
                        {"name": "veyra/job-issue-1-abc"},
                    ]
                )
            raise AssertionError(request.url)

        result = self._guard(handler).check(self.worker, self.job)

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "GITHUB_WORKER_BRANCH_EXISTS")
        self.assertEqual(result.existing_branch, "veyra/job-issue-1-abc")

    def test_closed_issue_is_stale(self):
        def handler(request):
            if request.url.path.endswith("/issues/1"):
                return self._json(
                    {
                        "number": 1,
                        "state": "closed",
                        "html_url": "https://github.com/example/repo/issues/1",
                    }
                )
            raise AssertionError(request.url)

        result = self._guard(handler).check(self.worker, self.job)

        self.assertFalse(result.passed)
        self.assertEqual(result.code, "GITHUB_ISSUE_CLOSED")
        self.assertEqual(result.issue_state, "CLOSED")
