from __future__ import annotations

import io
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from jobs.models import JobDraft, JobFundingSnapshot, VeyraJob
from workers.claiming import (
    CircleClaimTransaction,
    WorkerClaimError,
    WorkerClaimPendingError,
    execute_worker_job_claim,
    preflight_worker_job_claim,
    reconcile_worker_job_claim,
)
from workers.github_freshness import GitHubFreshnessResult
from workers.models import WorkerAgent, WorkerJobQueueItem

CLIENT = "0x1111111111111111111111111111111111111111"
WORKER = "0x2222222222222222222222222222222222222222"
OTHER = "0x3333333333333333333333333333333333333333"
VERIFIER = "0x0edbc6f8506e72478ce78a4ae934c7b21cb7050a"
ZERO = "0x0000000000000000000000000000000000000000"
TX_HASH = "0x" + "ab" * 32
REPOSITORY_HASH = "0x" + "11" * 32
TASK_HASH = "0x" + "22" * 32
POLICY_HASH = "0x" + "33" * 32


class FakeGitHubGuard:
    def check(self, worker, job):
        return GitHubFreshnessResult(
            passed=True,
            code="GITHUB_FRESH",
            detail="The GitHub issue is fresh.",
            issue_state="OPEN",
            issue_url=job.draft.github_issue_url,
            checked_at=timezone.now().isoformat(),
        )


DEFAULT_RECEIPT = object()


class FakeArcClient:
    def __init__(self, states, *, receipt=DEFAULT_RECEIPT, event_provider=WORKER):
        self.states = [dict(item) for item in states]
        self.last_state = dict(self.states[-1])
        self.receipt = (
            {"status": 1, "blockNumber": 777}
            if receipt is DEFAULT_RECEIPT
            else receipt
        )
        self.event_provider = event_provider

    def assert_chain(self):
        return None

    def is_paused(self):
        return False

    def is_agent_authorised(self, address):
        return address.lower() == WORKER

    def is_verifier_authorised(self, address):
        return address.lower() == VERIFIER

    def get_job(self, job_id):
        if self.states:
            self.last_state = self.states.pop(0)
        return dict(self.last_state)

    def transaction_receipt_or_none(self, tx_hash):
        return self.receipt

    def decode_receipt_event(self, event_name, receipt):
        if event_name != "JobClaimed":
            return []
        return [
            {
                "args": {
                    "jobId": 5,
                    "provider": self.event_provider,
                    "claimDeadline": int(timezone.now().timestamp()) + 3600,
                }
            }
        ]


class FakeCircleClient:
    def __init__(self, created=None, polled=None):
        self.created = created or CircleClaimTransaction("circle-1", "INITIATED")
        self.polled = list(polled or [CircleClaimTransaction("circle-1", "COMPLETE", TX_HASH)])
        self.create_calls = []
        self.get_calls = []

    def create_claim(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.created

    def get_transaction(self, transaction_id):
        self.get_calls.append(transaction_id)
        if self.polled:
            return self.polled.pop(0)
        return self.created


@override_settings(
    VEYRA_VERIFIER_ADDRESS=VERIFIER,
    ARC_USDC_DECIMALS=6,
    WORKER_DISCOVERY_MIN_REMAINING_SECONDS=900,
    WORKER_DISCOVERY_REQUIRE_SKILL_MATCH=True,
    WORKER_CLAIM_TIMEOUT_SECONDS=2,
    WORKER_CLAIM_POLL_INTERVAL_SECONDS=0,
    WORKER_ARC_RECEIPT_TIMEOUT_SECONDS=2,
    VEYRA_CONTRACT_ADDRESS="0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5",
)
class WorkerClaimingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(handle="claim-client")
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            description="Autonomous coding worker",
            status=WorkerAgent.Status.ACTIVE,
            skills=["Python", "Flask", "Pytest"],
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
            discovery_enabled=False,
        )
        deadline = timezone.now() + timedelta(hours=3)
        self.draft = JobDraft.objects.create(
            client=self.user,
            status=JobDraft.Status.FUNDED,
            github_issue_url="https://github.com/example/repo/issues/3",
            repository_owner="example",
            repository_name="repo",
            target_branch="main",
            issue_number=3,
            issue_title="Add task statistics endpoint",
            issue_body="Build the endpoint.",
            budget_usdc="1.000000",
            deadline=deadline,
            acceptance_criteria=["Tests pass"],
            advanced_options={},
        )
        JobFundingSnapshot.objects.create(
            draft=self.draft,
            repository_commitment={
                "version": 2,
                "host": "github.com",
                "owner": "example",
                "repository": "repo",
                "targetBranch": "main",
                "issueNumber": 3,
                "repositoryStack": [
                    {"name": "Python", "category": "language"},
                    {"name": "Flask", "category": "framework"},
                    {"name": "Pytest", "category": "testing"},
                ],
            },
            task_commitment={"version": 2, "title": self.draft.issue_title},
            policy_commitment={
                "version": 2,
                "requiredCommands": ["pytest -q"],
                "deliveryType": "PULL_REQUEST",
                "agentAccess": "OPEN",
            },
            repository_hash=REPOSITORY_HASH,
            task_hash=TASK_HASH,
            policy_hash=POLICY_HASH,
            budget_atomic=1_000_000,
            expires_at=int(deadline.timestamp()),
            verifier_address=VERIFIER,
            invited_provider_address=ZERO,
        )
        self.job = VeyraJob.objects.create(
            client=self.user,
            draft=self.draft,
            onchain_job_id=5,
            status="FUNDED",
            client_status="OPEN",
            client_address=CLIENT,
            invited_provider_address=ZERO,
            provider_address="",
            verifier_address=VERIFIER,
            budget_atomic=1_000_000,
            expires_at=int(deadline.timestamp()),
            repository_hash=REPOSITORY_HASH,
            task_hash=TASK_HASH,
            policy_hash=POLICY_HASH,
            creation_tx_hash="0x" + "55" * 32,
        )
        self.item = WorkerJobQueueItem.objects.create(
            worker=self.worker,
            job=self.job,
            status=WorkerJobQueueItem.Status.QUEUED,
            source=WorkerJobQueueItem.Source.MANUAL,
            eligibility_passed=True,
            eligibility_code="ELIGIBLE",
            eligibility_detail="Eligible",
            priority_score=501,
            required_skills=["Python", "Flask", "Pytest"],
            matched_skills=["Python", "Flask", "Pytest"],
            onchain_status="FUNDED",
            github_freshness_code="GITHUB_FRESH",
            github_snapshot={"issue_state": "OPEN"},
            queued_at=timezone.now(),
        )

    def funded(self):
        return {
            "job_id": 5,
            "client": CLIENT,
            "invited_provider": ZERO,
            "provider": ZERO,
            "verifier": VERIFIER,
            "budget": 1_000_000,
            "expires_at": int(self.job.expires_at),
            "claim_deadline": 0,
            "repository_hash": REPOSITORY_HASH,
            "task_hash": TASK_HASH,
            "policy_hash": POLICY_HASH,
            "status": "FUNDED",
            "status_code": 1,
            "client_status": "OPEN",
            "created_at": int(timezone.now().timestamp()) - 60,
            "claimed_at": 0,
            "submitted_at": 0,
            "resolved_at": 0,
        }

    def claimed(self, provider=WORKER):
        value = self.funded()
        value.update(
            provider=provider.lower(),
            status="CLAIMED",
            status_code=2,
            client_status="AGENT_WORKING",
            claim_deadline=int(timezone.now().timestamp()) + 3600,
            claimed_at=int(timezone.now().timestamp()),
        )
        return value

    def test_preflight_is_read_only_and_allows_discovery_disabled(self):
        result = preflight_worker_job_claim(
            str(self.item.id),
            arc_client=FakeArcClient([self.funded()]),
            github_guard=FakeGitHubGuard(),
        )
        self.assertEqual(result.job_id, 5)
        self.assertEqual(result.github_freshness_code, "GITHUB_FRESH")
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.QUEUED)
        self.assertIsNone(self.item.claim_idempotency_key)

    def test_preflight_rejects_nonqueued_item(self):
        self.item.status = WorkerJobQueueItem.Status.DEFERRED
        self.item.save()
        with self.assertRaisesMessage(WorkerClaimError, "must be QUEUED"):
            preflight_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.funded()]),
                github_guard=FakeGitHubGuard(),
            )

    def test_successful_claim_saves_circle_and_arc_metadata(self):
        circle = FakeCircleClient()
        result = execute_worker_job_claim(
            str(self.item.id),
            arc_client=FakeArcClient([self.funded(), self.claimed()]),
            github_guard=FakeGitHubGuard(),
            circle_client=circle,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(result.status, WorkerJobQueueItem.Status.CLAIMED)
        self.assertEqual(result.arc_transaction_hash, TX_HASH)
        self.item.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.CLAIMED)
        self.assertEqual(self.item.claim_circle_transaction_id, "circle-1")
        self.assertEqual(self.item.claim_arc_transaction_hash, TX_HASH)
        self.assertEqual(self.item.claim_receipt_block_number, 777)
        self.assertEqual(self.job.status, "CLAIMED")
        self.assertEqual(self.job.provider_address, WORKER)

    def test_claim_uses_exact_typed_payload_and_stable_idempotency_key(self):
        circle = FakeCircleClient()
        execute_worker_job_claim(
            str(self.item.id),
            arc_client=FakeArcClient([self.funded(), self.claimed()]),
            github_guard=FakeGitHubGuard(),
            circle_client=circle,
            sleep_fn=lambda _: None,
        )
        self.assertEqual(len(circle.create_calls), 1)
        call = circle.create_calls[0]
        self.assertEqual(call["worker_wallet_address"], WORKER)
        self.assertEqual(call["job_id"], 5)
        self.item.refresh_from_db()
        self.assertEqual(call["idempotency_key"], self.item.claim_idempotency_key)

    def test_circle_terminal_failure_marks_queue_failed(self):
        circle = FakeCircleClient(
            created=CircleClaimTransaction("circle-1", "FAILED", failure_message="reverted"),
            polled=[],
        )
        with self.assertRaises(WorkerClaimError):
            execute_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.funded()]),
                github_guard=FakeGitHubGuard(),
                circle_client=circle,
                sleep_fn=lambda _: None,
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.FAILED)
        self.assertEqual(self.item.claim_failure_stage, "circle_transaction")

    @override_settings(WORKER_CLAIM_TIMEOUT_SECONDS=0)
    def test_circle_timeout_stays_pending_and_never_resubmits(self):
        circle = FakeCircleClient(
            created=CircleClaimTransaction("circle-1", "PENDING"),
            polled=[],
        )
        with self.assertRaises(WorkerClaimPendingError):
            execute_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.funded()]),
                github_guard=FakeGitHubGuard(),
                circle_client=circle,
                sleep_fn=lambda _: None,
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.CLAIM_PENDING)
        self.assertEqual(len(circle.create_calls), 1)
        with self.assertRaises(WorkerClaimError):
            execute_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.funded()]),
                github_guard=FakeGitHubGuard(),
                circle_client=circle,
                sleep_fn=lambda _: None,
            )
        self.assertEqual(len(circle.create_calls), 1)

    @override_settings(WORKER_ARC_RECEIPT_TIMEOUT_SECONDS=0)
    def test_missing_arc_receipt_stays_pending(self):
        circle = FakeCircleClient(
            created=CircleClaimTransaction("circle-1", "COMPLETE", TX_HASH),
            polled=[],
        )
        with self.assertRaises(WorkerClaimPendingError):
            execute_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.funded()], receipt=None),
                github_guard=FakeGitHubGuard(),
                circle_client=circle,
                sleep_fn=lambda _: None,
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.CLAIM_PENDING)
        self.assertEqual(self.item.claim_failure_stage, "arc_receipt_pending")

    def test_wrong_receipt_provider_never_marks_claimed(self):
        circle = FakeCircleClient(
            created=CircleClaimTransaction("circle-1", "COMPLETE", TX_HASH),
            polled=[],
        )
        with self.assertRaises(WorkerClaimPendingError):
            execute_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient(
                    [self.funded(), self.claimed()], event_provider=OTHER
                ),
                github_guard=FakeGitHubGuard(),
                circle_client=circle,
                sleep_fn=lambda _: None,
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.CLAIM_PENDING)
        self.assertEqual(self.item.claim_failure_stage, "arc_claim_verification")

    def test_reconcile_pending_circle_transaction_does_not_create(self):
        self.item.status = WorkerJobQueueItem.Status.CLAIM_PENDING
        self.item.claim_idempotency_key = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.item.claim_started_at = timezone.now()
        self.item.claim_circle_transaction_id = "circle-1"
        self.item.claim_circle_state = "PENDING"
        self.item.save()
        circle = FakeCircleClient(polled=[CircleClaimTransaction("circle-1", "PENDING")])
        with self.assertRaises(WorkerClaimPendingError):
            reconcile_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.funded()]),
                circle_client=circle,
            )
        self.assertEqual(circle.create_calls, [])
        self.assertEqual(circle.get_calls, ["circle-1"])

    def test_reconcile_complete_transaction_finalizes(self):
        self.item.status = WorkerJobQueueItem.Status.CLAIM_PENDING
        self.item.claim_idempotency_key = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.item.claim_started_at = timezone.now()
        self.item.claim_circle_transaction_id = "circle-1"
        self.item.claim_circle_state = "PENDING"
        self.item.save()
        circle = FakeCircleClient(polled=[CircleClaimTransaction("circle-1", "COMPLETE", TX_HASH)])
        result = reconcile_worker_job_claim(
            str(self.item.id),
            arc_client=FakeArcClient([self.funded(), self.claimed()]),
            circle_client=circle,
        )
        self.assertEqual(result.status, WorkerJobQueueItem.Status.CLAIMED)
        self.assertEqual(circle.create_calls, [])

    def test_reconcile_detects_different_provider(self):
        self.item.status = WorkerJobQueueItem.Status.CLAIM_PENDING
        self.item.claim_idempotency_key = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.item.claim_started_at = timezone.now()
        self.item.save()
        with self.assertRaisesMessage(WorkerClaimError, "different provider"):
            reconcile_worker_job_claim(
                str(self.item.id),
                arc_client=FakeArcClient([self.claimed(OTHER)]),
                circle_client=FakeCircleClient(),
            )
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, WorkerJobQueueItem.Status.FAILED)

    def test_claimed_model_state_requires_hash_and_confirmation(self):
        self.item.status = WorkerJobQueueItem.Status.CLAIMED
        self.item.onchain_status = "CLAIMED"
        with self.assertRaises(ValidationError):
            self.item.full_clean()

    def test_live_command_requires_explicit_confirmation(self):
        with self.assertRaisesMessage(CommandError, "--confirm-live-claim"):
            call_command("claim_worker_job", job_id=5)

    def test_show_queue_displays_no_secret_values(self):
        output = io.StringIO()
        call_command("show_worker_job_queue", stdout=output)
        text = output.getvalue()
        self.assertIn("Secrets displayed: none", text)
        self.assertNotIn("CIRCLE_ENTITY_SECRET", text)
        self.assertNotIn("GITHUB_TOKEN", text)
