from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from jobs.models import JobDraft, JobFundingSnapshot, VeyraJob
from workers.discovery import (
    disable_worker_discovery,
    discover_job,
    enable_worker_discovery,
    enqueue_job_created_fast_path,
    reconcile_worker_jobs,
)
from workers.github_freshness import GitHubFreshnessError, GitHubFreshnessResult
from workers.models import WorkerAgent, WorkerJobQueueItem


CLIENT = "0x1111111111111111111111111111111111111111"
WORKER = "0x2222222222222222222222222222222222222222"
OTHER = "0x3333333333333333333333333333333333333333"
VERIFIER = "0x0edbc6f8506e72478ce78a4ae934c7b21cb7050a"
ZERO = "0x0000000000000000000000000000000000000000"
REPOSITORY_HASH = "0x" + "11" * 32
TASK_HASH = "0x" + "22" * 32
POLICY_HASH = "0x" + "33" * 32


class FakeArcClient:
    def __init__(self, jobs=None, *, paused=False, agent_authorised=True, verifier_authorised=True):
        self.jobs = jobs or {}
        self.paused = paused
        self.agent_authorised = agent_authorised
        self.verifier_authorised = verifier_authorised

    def assert_chain(self):
        return None

    def is_paused(self):
        return self.paused

    def is_agent_authorised(self, address):
        return self.agent_authorised and address.lower() == WORKER

    def is_verifier_authorised(self, address):
        return self.verifier_authorised and address.lower() == VERIFIER

    def get_job(self, job_id):
        return dict(self.jobs[job_id])


class FakeGitHubGuard:
    def __init__(self, result=None, error=None):
        self.result = result or GitHubFreshnessResult(
            passed=True,
            code="GITHUB_FRESH",
            detail="The GitHub issue is fresh.",
            issue_state="OPEN",
            issue_url="https://github.com/example/repo/issues/1",
            checked_at=timezone.now().isoformat(),
        )
        self.error = error

    def check(self, worker, job):
        if self.error:
            raise self.error
        return self.result


@override_settings(
    VEYRA_VERIFIER_ADDRESS=VERIFIER,
    ARC_USDC_DECIMALS=6,
    WORKER_DISCOVERY_MIN_REMAINING_SECONDS=900,
    WORKER_DISCOVERY_REQUIRE_SKILL_MATCH=True,
)
class WorkerDiscoveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(handle="discovery-client")
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            description="Autonomous coding worker",
            status=WorkerAgent.Status.ACTIVE,
            skills=["Python", "Flask", "Django", "Pytest", "TypeScript", "Next.js"],
            minimum_budget_usdc="1.000000",
            maximum_active_jobs=1,
            engine_provider=WorkerAgent.EngineProvider.OPENCODE,
            engine_model="aiand/zai-org/glm-5.2",
            engine_connected=True,
            engine_version="1.17.18",
            engine_last_checked_at=timezone.now(),
            circle_wallet_id="wallet-id",
            circle_wallet_set_id="wallet-set-id",
            worker_wallet_address=WORKER,
            wallet_blockchain="ARC-TESTNET",
            wallet_account_type="SCA",
            payout_wallet_address=WORKER,
            github_username="logicbloomlab",
            github_connected=True,
            contract_authorised=True,
            test_assignment_passed=True,
        )
        self.job = self._create_job(3)
        self.onchain = {3: self._onchain_job(self.job)}
        self.arc = FakeArcClient(self.onchain)
        self.github = FakeGitHubGuard()

    def _create_job(self, job_id, *, stack=None, invited=ZERO, budget_atomic=1_000_000):
        deadline = timezone.now() + timedelta(hours=3)
        draft = JobDraft.objects.create(
            client=self.user,
            status=JobDraft.Status.FUNDED,
            github_issue_url=f"https://github.com/example/repo/issues/{job_id}",
            repository_owner="example",
            repository_name="repo",
            target_branch="main",
            issue_number=job_id,
            issue_title=f"Implement issue {job_id}",
            issue_body="Build the requested endpoint.",
            budget_usdc=f"{budget_atomic / 1_000_000:.6f}",
            deadline=deadline,
            acceptance_criteria=["Tests pass"],
            advanced_options={},
        )
        JobFundingSnapshot.objects.create(
            draft=draft,
            repository_commitment={
                "version": 2,
                "host": "github.com",
                "owner": "example",
                "repository": "repo",
                "targetBranch": "main",
                "issueNumber": job_id,
                "repositoryStack": stack
                if stack is not None
                else [
                    {"name": "Python", "category": "language"},
                    {"name": "Flask", "category": "framework"},
                    {"name": "Pytest", "category": "testing"},
                ],
            },
            task_commitment={
                "version": 2,
                "title": draft.issue_title,
                "workType": "FEATURE",
                "description": draft.issue_body,
                "technicalRequirements": [],
                "acceptanceCriteria": [
                    {"statement": "Tests pass", "verificationMethod": "AUTOMATED_TEST"}
                ],
            },
            policy_commitment={
                "version": 2,
                "requiredCommands": ["pytest -q"],
                "allowedPaths": [],
                "forbiddenPaths": [],
                "deliveryType": "PULL_REQUEST",
                "agentAccess": "OPEN" if invited == ZERO else "INVITED",
            },
            repository_hash=REPOSITORY_HASH,
            task_hash=TASK_HASH,
            policy_hash=POLICY_HASH,
            budget_atomic=budget_atomic,
            expires_at=int(deadline.timestamp()),
            verifier_address=VERIFIER,
            invited_provider_address=invited,
        )
        return VeyraJob.objects.create(
            client=self.user,
            draft=draft,
            onchain_job_id=job_id,
            status="FUNDED",
            client_status="OPEN",
            client_address=CLIENT,
            invited_provider_address=invited,
            provider_address="",
            verifier_address=VERIFIER,
            budget_atomic=budget_atomic,
            expires_at=int(deadline.timestamp()),
            repository_hash=REPOSITORY_HASH,
            task_hash=TASK_HASH,
            policy_hash=POLICY_HASH,
            creation_tx_hash="0x" + f"{job_id:064x}",
        )

    def _onchain_job(self, job, *, status="FUNDED", provider=ZERO, invited=None):
        return {
            "job_id": job.onchain_job_id,
            "client": CLIENT,
            "invited_provider": invited if invited is not None else job.invited_provider_address,
            "provider": provider,
            "verifier": VERIFIER,
            "budget": int(job.budget_atomic),
            "expires_at": int(job.expires_at),
            "claim_deadline": 0,
            "repository_hash": job.repository_hash,
            "task_hash": job.task_hash,
            "policy_hash": job.policy_hash,
            "status": status,
            "status_code": 1 if status == "FUNDED" else 2,
            "client_status": "OPEN" if status == "FUNDED" else "AGENT_WORKING",
            "created_at": int(timezone.now().timestamp()) - 60,
            "claimed_at": 0,
            "submitted_at": 0,
            "resolved_at": 0,
        }

    def test_enable_and_disable_discovery_are_explicit(self):
        self.assertFalse(self.worker.discovery_enabled)
        enabled = enable_worker_discovery(self.worker, arc_client=self.arc)
        self.assertTrue(enabled.discovery_enabled)
        disabled = disable_worker_discovery(enabled)
        self.assertFalse(disabled.discovery_enabled)

    def test_matching_open_job_is_queued(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        result = discover_job(self.worker, self.job, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(result.status, WorkerJobQueueItem.Status.QUEUED)
        self.assertEqual(result.eligibility_code, "ELIGIBLE")
        self.assertEqual(set(result.matched_skills), {"Python", "Flask", "Pytest"})
        item = WorkerJobQueueItem.objects.get(worker=self.worker, job=self.job)
        self.assertTrue(item.eligibility_passed)
        self.assertIsNotNone(item.queued_at)
        self.assertNotIn("token", item.onchain_snapshot)
        self.assertNotIn("secret", item.onchain_snapshot)

    def test_discovery_is_idempotent(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        discover_job(self.worker, self.job, arc_client=self.arc, github_guard=self.github)
        discover_job(self.worker, self.job, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(
            WorkerJobQueueItem.objects.filter(worker=self.worker, job=self.job).count(),
            1,
        )

    def test_skill_mismatch_is_ineligible(self):
        mismatch = self._create_job(
            4,
            stack=[
                {"name": "Rust", "category": "language"},
                {"name": "Cargo", "category": "package_manager"},
            ],
        )
        self.onchain[4] = self._onchain_job(mismatch)
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        result = discover_job(self.worker, mismatch, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(result.status, WorkerJobQueueItem.Status.INELIGIBLE)
        self.assertEqual(result.eligibility_code, "SKILL_MISMATCH")

    def test_job_invited_to_another_agent_is_ineligible(self):
        invited_job = self._create_job(5, invited=OTHER)
        self.onchain[5] = self._onchain_job(invited_job, invited=OTHER)
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        result = discover_job(self.worker, invited_job, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(result.status, WorkerJobQueueItem.Status.INELIGIBLE)
        self.assertEqual(result.eligibility_code, "INVITED_TO_ANOTHER_AGENT")

    def test_capacity_defers_second_eligible_job(self):
        second = self._create_job(6)
        self.onchain[6] = self._onchain_job(second)
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        first_result = discover_job(self.worker, self.job, arc_client=self.arc, github_guard=self.github)
        second_result = discover_job(self.worker, second, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(first_result.status, WorkerJobQueueItem.Status.QUEUED)
        self.assertEqual(second_result.status, WorkerJobQueueItem.Status.DEFERRED)
        self.assertEqual(second_result.eligibility_code, "ELIGIBLE")
        self.assertIn("capacity is full", second_result.eligibility_detail)

    def test_claimed_onchain_job_is_stale(self):
        self.onchain[3] = self._onchain_job(
            self.job,
            status="CLAIMED",
            provider=WORKER,
        )
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        result = discover_job(self.worker, self.job, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(result.status, WorkerJobQueueItem.Status.STALE)
        self.assertEqual(result.eligibility_code, "ONCHAIN_JOB_NOT_OPEN")

    def test_reconciliation_scans_open_jobs_without_claiming(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        result = reconcile_worker_jobs(self.worker, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.queued, 1)
        self.assertEqual(result.deferred, 0)
        self.assertEqual(WorkerJobQueueItem.objects.count(), 1)

    def test_job_created_fast_path_uses_enabled_worker(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        from unittest.mock import patch

        with patch("workers.discovery.ArcClient", return_value=self.arc), patch(
            "workers.discovery.GitHubFreshnessGuard", return_value=self.github
        ):
            results = enqueue_job_created_fast_path(self.job.onchain_job_id)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, WorkerJobQueueItem.Status.QUEUED)

    def test_budget_below_worker_minimum_is_ineligible(self):
        self.worker.minimum_budget_usdc = "2.000000"
        self.worker.discovery_enabled = True
        self.worker.save(
            update_fields=["minimum_budget_usdc", "discovery_enabled", "updated_at"]
        )

        result = discover_job(self.worker, self.job, arc_client=self.arc, github_guard=self.github)

        self.assertEqual(result.status, WorkerJobQueueItem.Status.INELIGIBLE)
        self.assertEqual(result.eligibility_code, "BUDGET_BELOW_MINIMUM")


class WorkerDiscoveryFreshnessTests(WorkerDiscoveryTests):
    def test_existing_worker_pull_request_is_blocked(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])
        guard = FakeGitHubGuard(
            GitHubFreshnessResult(
                passed=False,
                code="GITHUB_WORKER_PR_OPEN",
                detail="The worker already has an open pull request for this issue.",
                issue_state="OPEN",
                issue_url="https://github.com/example/repo/issues/3",
                existing_pull_request_url="https://github.com/example/repo/pull/2",
                existing_pull_request_state="OPEN",
                checked_at=timezone.now().isoformat(),
            )
        )

        result = discover_job(
            self.worker, self.job, arc_client=self.arc, github_guard=guard
        )

        self.assertEqual(result.status, WorkerJobQueueItem.Status.BLOCKED)
        self.assertEqual(result.eligibility_code, "GITHUB_WORKER_PR_OPEN")
        item = WorkerJobQueueItem.objects.get(worker=self.worker, job=self.job)
        self.assertEqual(
            item.github_snapshot["existing_pull_request_url"],
            "https://github.com/example/repo/pull/2",
        )

    def test_duplicate_repository_issue_is_marked_duplicate(self):
        duplicate = self._create_job(4)
        duplicate.draft.issue_number = self.job.draft.issue_number
        duplicate.draft.github_issue_url = self.job.draft.github_issue_url
        duplicate.draft.save(update_fields=["issue_number", "github_issue_url", "updated_at"])
        self.onchain[4] = self._onchain_job(duplicate)
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])

        result = discover_job(
            self.worker, duplicate, arc_client=self.arc, github_guard=self.github
        )

        self.assertEqual(result.status, WorkerJobQueueItem.Status.DUPLICATE)
        self.assertEqual(result.eligibility_code, "DUPLICATE_REPOSITORY_ISSUE")
        self.assertIn("Arc job #3", result.eligibility_detail)

    def test_closed_issue_is_stale(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])
        guard = FakeGitHubGuard(
            GitHubFreshnessResult(
                passed=False,
                code="GITHUB_ISSUE_CLOSED",
                detail="GitHub reports the issue state as CLOSED.",
                issue_state="CLOSED",
                issue_url="https://github.com/example/repo/issues/3",
                checked_at=timezone.now().isoformat(),
            )
        )

        result = discover_job(
            self.worker, self.job, arc_client=self.arc, github_guard=guard
        )

        self.assertEqual(result.status, WorkerJobQueueItem.Status.STALE)
        self.assertEqual(result.eligibility_code, "GITHUB_ISSUE_CLOSED")

    def test_github_read_failure_is_deferred(self):
        self.worker.discovery_enabled = True
        self.worker.save(update_fields=["discovery_enabled", "updated_at"])
        guard = FakeGitHubGuard(error=GitHubFreshnessError("temporary outage"))

        result = discover_job(
            self.worker, self.job, arc_client=self.arc, github_guard=guard
        )

        self.assertEqual(result.status, WorkerJobQueueItem.Status.DEFERRED)
        self.assertEqual(result.eligibility_code, "GITHUB_READ_FAILED")
