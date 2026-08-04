from unittest.mock import Mock

from django.test import TestCase, override_settings
from django.utils import timezone

from workers.engine import EngineHealthResult
from workers.github_bot import GitHubBotConnectionResult
from workers.models import WorkerAgent
from workers.readiness import (
    check_worker_readiness,
    sync_worker_contract_authorisation,
)


WORKER_ADDRESS = "0x7e1efab63cb37b0550c9cf23d81622b66a31ea33"
VERIFIER_ADDRESS = "0x1111111111111111111111111111111111111111"
CONTRACT_ADDRESS = "0xe422ba48559A4ef5B1fad8A5AAc4F646b252d9F5"


class FakeArcClient:
    def __init__(
        self,
        *,
        agent_authorised=True,
        verifier_authorised=True,
        paused=False,
        chain_id=5042002,
    ):
        self.agent_authorised = agent_authorised
        self.verifier_authorised = verifier_authorised
        self.paused = paused
        self.w3 = Mock()
        self.w3.eth.chain_id = chain_id
        self.contract = Mock()
        self.contract.address = CONTRACT_ADDRESS

    def assert_chain(self):
        if self.w3.eth.chain_id != 5042002:
            raise RuntimeError("chain mismatch")

    def is_paused(self):
        return self.paused

    def is_agent_authorised(self, address):
        return self.agent_authorised

    def is_verifier_authorised(self, address):
        return self.verifier_authorised


def successful_engine_check(worker):
    return EngineHealthResult(
        connected=True,
        provider=worker.engine_provider,
        model=worker.engine_model,
        version="1.17.18",
        executable="opencode.ps1",
        checked_at=timezone.now().isoformat(),
        message="OpenCode is ready.",
        return_code=0,
    )


def successful_github_check(*, expected_username=None):
    return GitHubBotConnectionResult(
        connected=True,
        login=expected_username or "logicbloomlab",
        github_user_id=227142916,
        account_type="User",
        api_url="https://api.github.com/users/logicbloomlab",
        checked_at=timezone.now().isoformat(),
    )


@override_settings(
    VEYRA_VERIFIER_ADDRESS=VERIFIER_ADDRESS,
    VEYRA_CONTRACT_ADDRESS=CONTRACT_ADDRESS,
    ARC_CHAIN_ID=5042002,
)
class WorkerReadinessTests(TestCase):
    def setUp(self):
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            description="Autonomous code worker",
            owner_type=WorkerAgent.OwnerType.VEYRA,
            status=WorkerAgent.Status.GITHUB_READY,
            skills=["Python", "Flask", "Pytest"],
            engine_provider=WorkerAgent.EngineProvider.OPENCODE,
            engine_model="zai-org/glm-5.2",
            engine_connected=True,
            engine_version="1.17.18",
            engine_last_checked_at=timezone.now(),
            circle_wallet_id="fecb6750-b81f-56f7-a229-091e876c4a36",
            circle_wallet_set_id="6839ea61-5756-507c-b751-b63d8a69c819",
            worker_wallet_address=WORKER_ADDRESS,
            wallet_blockchain="ARC-TESTNET",
            wallet_account_type="SCA",
            payout_wallet_address=WORKER_ADDRESS,
            github_username="logicbloomlab",
            github_connected=True,
        )

    def test_syncs_authorised_worker_without_activating_it(self):
        result = sync_worker_contract_authorisation(
            self.worker,
            arc_client=FakeArcClient(),
        )
        self.worker.refresh_from_db()

        self.assertTrue(result.authorised)
        self.assertTrue(self.worker.contract_authorised)
        self.assertEqual(self.worker.status, WorkerAgent.Status.GITHUB_READY)
        self.assertFalse(self.worker.discovery_enabled)

    def test_revoked_authorisation_moves_worker_to_pending(self):
        self.worker.contract_authorised = True
        self.worker.status = WorkerAgent.Status.TESTING
        self.worker.save()

        result = sync_worker_contract_authorisation(
            self.worker,
            arc_client=FakeArcClient(agent_authorised=False),
        )
        self.worker.refresh_from_db()

        self.assertFalse(result.authorised)
        self.assertFalse(self.worker.contract_authorised)
        self.assertEqual(
            self.worker.status,
            WorkerAgent.Status.AUTHORISATION_PENDING,
        )

    def test_readiness_passes_and_moves_worker_to_testing(self):
        result = check_worker_readiness(
            self.worker,
            arc_client=FakeArcClient(),
            engine_checker=successful_engine_check,
            github_checker=successful_github_check,
        )
        self.worker.refresh_from_db()

        self.assertTrue(result.ready)
        self.assertEqual(self.worker.status, WorkerAgent.Status.TESTING)
        self.assertTrue(self.worker.contract_authorised)
        self.assertFalse(self.worker.test_assignment_passed)
        self.assertFalse(self.worker.discovery_enabled)

    def test_readiness_fails_when_contract_is_paused(self):
        result = check_worker_readiness(
            self.worker,
            arc_client=FakeArcClient(paused=True),
            engine_checker=successful_engine_check,
            github_checker=successful_github_check,
        )
        self.worker.refresh_from_db()

        self.assertFalse(result.ready)
        self.assertEqual(self.worker.status, WorkerAgent.Status.GITHUB_READY)
        self.assertIn(
            "escrow_unpaused",
            [check.name for check in result.checks if not check.passed],
        )

    def test_readiness_fails_when_verifier_is_not_authorised(self):
        result = check_worker_readiness(
            self.worker,
            arc_client=FakeArcClient(verifier_authorised=False),
            engine_checker=successful_engine_check,
            github_checker=successful_github_check,
        )

        self.assertFalse(result.ready)
        self.assertIn(
            "verifier_authorised",
            [check.name for check in result.checks if not check.passed],
        )

    def test_readiness_fails_when_engine_is_unreachable(self):
        def failed_engine_check(worker):
            return EngineHealthResult(
                connected=False,
                provider=worker.engine_provider,
                model=worker.engine_model,
                version="",
                executable="opencode.ps1",
                checked_at=timezone.now().isoformat(),
                message="OpenCode did not respond.",
                return_code=1,
            )

        result = check_worker_readiness(
            self.worker,
            arc_client=FakeArcClient(),
            engine_checker=failed_engine_check,
            github_checker=successful_github_check,
        )

        self.assertFalse(result.ready)
        self.assertIn(
            "engine_live",
            [check.name for check in result.checks if not check.passed],
        )

    def test_readiness_fails_when_github_verification_fails(self):
        def failed_github_check(*, expected_username=None):
            raise RuntimeError("GitHub denied the token")

        result = check_worker_readiness(
            self.worker,
            arc_client=FakeArcClient(),
            engine_checker=successful_engine_check,
            github_checker=failed_github_check,
        )

        self.assertFalse(result.ready)
        self.assertIn(
            "github_platform",
            [check.name for check in result.checks if not check.passed],
        )
