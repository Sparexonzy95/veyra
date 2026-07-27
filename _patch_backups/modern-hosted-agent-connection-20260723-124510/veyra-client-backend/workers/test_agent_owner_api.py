from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User, UserCapability
from workers.circle_wallet import WorkerWalletProvisioningResult
from workers.models import RunnerAgentBinding, RunnerDevice, WorkerAgent


class AgentOwnerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(handle="agent-owner")
        UserCapability.objects.create(
            user=self.owner,
            code=UserCapability.Code.AGENT_OWNER,
        )
        self.other_owner = User.objects.create_user(handle="other-owner")
        UserCapability.objects.create(
            user=self.other_owner,
            code=UserCapability.Code.AGENT_OWNER,
        )
        self.payload = {
            "name": "LogicBloom Flask Agent",
            "description": "Builds and tests Flask API endpoints.",
            "specialisation": "PYTHON_BACKEND",
            "languages": ["Python"],
            "frameworks": ["Flask"],
            "testing_tools": ["Pytest"],
            "task_types": ["API endpoint", "Bug fix"],
            "minimum_budget_usdc": "1.000000",
            "maximum_budget_usdc": "5.000000",
            "public_repositories_only": True,
            "allowed_organizations": [],
            "maximum_active_jobs": 1,
            "maximum_execution_minutes": 45,
            "allow_fork_creation": True,
            "allow_new_dependencies": False,
            "allow_database_migrations": False,
            "protected_paths": [".github/workflows", ".env"],
        }

    def test_agent_owner_can_create_focused_veyra_hosted_agent(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post("/api/v1/agents/", self.payload, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        agent = WorkerAgent.objects.get()
        self.assertEqual(agent.owner_user, self.owner)
        self.assertEqual(agent.owner_type, WorkerAgent.OwnerType.EXTERNAL)
        self.assertEqual(agent.engine_provider, WorkerAgent.EngineProvider.OPENCODE)
        self.assertTrue(agent.engine_connected)
        self.assertEqual(agent.status, WorkerAgent.Status.ENGINE_CONNECTED)
        self.assertEqual(agent.skills, [
            "Python",
            "Flask",
            "Pytest",
            "API endpoint",
            "Bug fix",
        ])
        self.assertFalse(agent.auto_claim_enabled)
        self.assertEqual(RunnerDevice.objects.count(), 1)
        self.assertEqual(RunnerAgentBinding.objects.count(), 1)
        self.assertEqual(response.data["runtime"]["runtime_mode"], "VEYRA_HOSTED")
        self.assertTrue(response.data["runtime"]["connected"])
        self.assertEqual(response.data["onboarding"]["current_step"], "wallet")
        self.assertNotIn("circle_wallet_id", response.data)
        self.assertNotIn("circle_wallet_set_id", response.data)

    @patch("workers.owner_views.provision_worker_wallet")
    def test_owner_can_create_a_dedicated_agent_wallet(self, provision_wallet):
        self.client.force_authenticate(self.owner)
        created = self.client.post("/api/v1/agents/", self.payload, format="json")
        agent = WorkerAgent.objects.get(pk=created.data["id"])
        provision_wallet.return_value = WorkerWalletProvisioningResult(
            worker_id=str(agent.id),
            wallet_set_id="agent-wallet-set",
            wallet_id="agent-wallet-id",
            address="0x2222222222222222222222222222222222222222",
            blockchain="ARC-TESTNET",
            account_type="SCA",
            created=True,
        )

        response = self.client.post(
            f"/api/v1/agents/{agent.id}/create-wallet/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["wallet"]["address"],
            "0x2222222222222222222222222222222222222222",
        )
        self.assertNotIn("wallet_id", response.data["wallet"])
        self.assertNotIn("wallet_set_id", response.data["wallet"])

    def test_owner_list_is_isolated(self):
        first = WorkerAgent.objects.create(
            slug="first-agent",
            name="First Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="external-runner",
        )
        WorkerAgent.objects.create(
            slug="second-agent",
            name="Second Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.other_owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["TypeScript"],
            languages=["TypeScript"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="external-runner",
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get("/api/v1/agents/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(first.id))

    def test_owner_cannot_read_another_owners_agent(self):
        agent = WorkerAgent.objects.create(
            slug="private-agent",
            name="Private Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.other_owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="external-runner",
        )
        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/api/v1/agents/{agent.id}/")
        self.assertEqual(response.status_code, 404)

    def test_capability_limits_are_enforced(self):
        self.client.force_authenticate(self.owner)
        payload = {**self.payload, "languages": ["Python", "SQL", "Go"]}
        response = self.client.post("/api/v1/agents/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("languages", response.data["error"]["message"])

    def test_budget_range_is_enforced(self):
        self.client.force_authenticate(self.owner)
        payload = {
            **self.payload,
            "minimum_budget_usdc": "5.000000",
            "maximum_budget_usdc": "1.000000",
        }
        response = self.client.post("/api/v1/agents/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("maximum_budget_usdc", response.data["error"]["message"])

    def test_regular_client_without_agent_owner_capability_is_forbidden(self):
        regular = User.objects.create_user(handle="regular-client")
        UserCapability.objects.create(user=regular, code=UserCapability.Code.CLIENT)
        self.client.force_authenticate(regular)
        response = self.client.get("/api/v1/agents/")
        self.assertEqual(response.status_code, 403)
