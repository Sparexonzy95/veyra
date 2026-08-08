import base64
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User, UserCapability
from workers.automatic_qualification import qualification_task_for_connection
from workers.circle_wallet import WorkerWalletProvisioningResult
from workers.hosted_agent_connection import _credential_hash
from workers.models import (
    HostedAgentConnection,
    RunnerPairingCode,
    WorkerAgent,
)


@override_settings(
    DEBUG=True,
    VEYRA_ALLOW_LOCAL_AGENT_RUNTIME=True,
    VEYRA_PUBLIC_API_URL="http://127.0.0.1:8000",
    VEYRA_AGENT_CONNECTION_PROTOCOL_VERSION=1,
)
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
        self.runtime_private_key = Ed25519PrivateKey.generate()
        self.runtime_public_key = self.runtime_private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.runtime_credential = "runtime-credential-" + "x" * 48
        self.payload = {
            "connection_link": (
                "veyra-connect://localhost:9100/connect/"
                "abcdefghijklmnopqrstuvwxyz123456?protocol=1"
            ),
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

    def _successful_provision(self, worker, *, connection_link=None):
        HostedAgentConnection.objects.create(
            worker=worker,
            runtime_id=f"runtime-{worker.id}",
            runtime_url="http://localhost:9100",
            public_key=base64.urlsafe_b64encode(self.runtime_public_key).decode("ascii").rstrip("="),
            public_key_fingerprint=hashlib.sha256(self.runtime_public_key).hexdigest(),
            protocol_version=1,
            runtime_version="test-runtime/1.0",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={"coding": True, "testing": True},
            credential_hash=_credential_hash(self.runtime_credential),
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        worker.engine_provider = WorkerAgent.EngineProvider.CUSTOM
        worker.engine_model = "zai-org/glm-5.2"
        worker.engine_connected = True
        worker.engine_version = "test-runtime/1.0"
        worker.engine_last_checked_at = timezone.now()
        worker.circle_wallet_set_id = f"wallet-set-{worker.id}"
        worker.circle_wallet_id = f"wallet-{worker.id}"
        worker.worker_wallet_address = "0x2222222222222222222222222222222222222222"
        worker.payout_wallet_address = worker.worker_wallet_address
        worker.contract_authorised = True
        worker.provisioning_stage = "READY_FOR_QUALIFICATION"
        worker.provisioning_error = ""
        worker.status = WorkerAgent.Status.READY_FOR_QUALIFICATION
        worker.save()
        return SimpleNamespace(
            stage=worker.provisioning_stage,
            status=worker.status,
            runtime_connected=True,
            wallet_ready=True,
            contract_authorised=True,
        )

    @patch("workers.serializers.provision_agent")
    def test_agent_owner_can_create_connected_owner_hosted_agent(self, provision_agent):
        provision_agent.side_effect = self._successful_provision
        self.client.force_authenticate(self.owner)
        response = self.client.post("/api/v1/agents/", self.payload, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        agent = WorkerAgent.objects.get()
        self.assertEqual(agent.owner_user, self.owner)
        self.assertEqual(agent.owner_type, WorkerAgent.OwnerType.EXTERNAL)
        self.assertEqual(agent.engine_provider, WorkerAgent.EngineProvider.CUSTOM)
        self.assertTrue(agent.engine_connected)
        self.assertEqual(agent.status, WorkerAgent.Status.READY_FOR_QUALIFICATION)
        self.assertEqual(
            agent.skills,
            ["Python", "Flask", "Pytest", "API endpoint", "Bug fix"],
        )
        self.assertFalse(agent.auto_claim_enabled)
        self.assertEqual(HostedAgentConnection.objects.count(), 1)
        self.assertEqual(response.data["runtime"]["runtime_mode"], "OWNER_HOSTED")
        self.assertTrue(response.data["runtime"]["connected"])
        self.assertEqual(response.data["runtime"]["provider"], "aiand")
        self.assertEqual(response.data["onboarding"]["current_step"], "qualification")
        self.assertEqual(
            response.data["worker_wallet_address"],
            "0x2222222222222222222222222222222222222222",
        )
        self.assertTrue(response.data["contract_authorised"])
        self.assertNotIn("circle_wallet_id", response.data)
        self.assertNotIn("circle_wallet_set_id", response.data)
        self.assertNotIn("connection_link", response.data)

    @patch("workers.serializers.provision_agent")
    def test_agent_starter_url_connects_qualifies_and_activates_without_pairing_code(
        self,
        provision_agent,
    ):
        provision_agent.side_effect = self._successful_provision
        self.client.force_authenticate(self.owner)

        created = self.client.post("/api/v1/agents/", self.payload, format="json")

        self.assertEqual(created.status_code, 201, created.data)
        provision_agent.assert_called_once()
        self.assertEqual(
            provision_agent.call_args.kwargs["connection_link"],
            self.payload["connection_link"],
        )
        agent = WorkerAgent.objects.get(pk=created.data["id"])
        connection = agent.hosted_connection
        self.assertTrue(created.data["runtime"]["connected"])
        self.assertEqual(RunnerPairingCode.objects.count(), 0)

        task = qualification_task_for_connection(connection)
        files = [
            {
                "path": task["qualification_target_path"],
                "content": (
                    'def health_response():\n'
                    '    return {"status": "ok", "service": "veyra-qualification", "version": 1}\n'
                ),
            }
        ]
        canonical = json.dumps(
            files,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        files_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        message = (
            f"veyra-qualification-v1:{task['id']}:{files_hash}:0"
        ).encode("utf-8")
        signature = base64.urlsafe_b64encode(
            self.runtime_private_key.sign(message)
        ).decode("ascii").rstrip("=")

        qualified = self.client.post(
            "/api/v1/agent-runtime/qualification/submit/",
            {
                "agent_id": str(agent.id),
                "qualification_id": task["id"],
                "lease_token": task["lease_token"],
                "files": files,
                "test_return_code": 0,
                "test_output": "1 passed",
                "signature": signature,
                "provider": "aiand",
                "model": "zai-org/glm-5.2",
                "runtime_version": "test-runtime/1.0",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.runtime_credential}",
        )

        self.assertEqual(qualified.status_code, 200, qualified.data)
        self.assertTrue(qualified.data["passed"])
        agent.refresh_from_db()
        self.assertEqual(agent.status, WorkerAgent.Status.ACTIVE)
        self.assertTrue(agent.test_assignment_passed)
        self.assertEqual(RunnerPairingCode.objects.count(), 0)

    def test_legacy_pairing_routes_are_not_public(self):
        self.client.force_authenticate(self.owner)
        pairing = self.client.post(
            f"/api/v1/agents/{self.worker_id_for_route_test()}/runtime/pairing-code/",
            {},
            format="json",
        )
        runner = self.client.post("/api/v1/runner/pair/", {}, format="json")
        self.assertEqual(pairing.status_code, 404)
        self.assertEqual(runner.status_code, 404)

    @patch("workers.serializers.provision_agent")
    def test_owner_can_disconnect_agent_with_public_agent_wording(self, provision_agent):
        provision_agent.side_effect = self._successful_provision
        self.client.force_authenticate(self.owner)
        created = self.client.post("/api/v1/agents/", self.payload, format="json")
        agent = WorkerAgent.objects.get(pk=created.data["id"])

        response = self.client.post(
            f"/api/v1/agents/{agent.id}/runtime/disconnect/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        agent.refresh_from_db()
        agent.hosted_connection.refresh_from_db()
        self.assertFalse(agent.engine_connected)
        self.assertEqual(
            agent.hosted_connection.status,
            HostedAgentConnection.Status.REVOKED,
        )
        self.assertEqual(agent.status, WorkerAgent.Status.CONNECTION_FAILED)

    def worker_id_for_route_test(self):
        return WorkerAgent.objects.create(
            slug="legacy-route-test",
            name="Legacy Route Test",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="pending-owner-runtime",
        ).id

    @patch("workers.owner_views.provision_worker_wallet")
    @patch("workers.serializers.provision_agent")
    def test_recovery_wallet_endpoint_does_not_expose_circle_ids(
        self,
        provision_agent,
        provision_wallet,
    ):
        provision_agent.side_effect = self._successful_provision
        self.client.force_authenticate(self.owner)
        created = self.client.post("/api/v1/agents/", self.payload, format="json")
        agent = WorkerAgent.objects.get(pk=created.data["id"])
        provision_wallet.return_value = WorkerWalletProvisioningResult(
            worker_id=str(agent.id),
            wallet_set_id="agent-wallet-set",
            wallet_id="agent-wallet-id",
            address=agent.worker_wallet_address,
            blockchain="ARC-TESTNET",
            account_type="SCA",
            created=False,
        )

        response = self.client.post(
            f"/api/v1/agents/{agent.id}/create-wallet/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["wallet"]["address"], agent.worker_wallet_address)
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

    def test_connection_link_is_required(self):
        self.client.force_authenticate(self.owner)
        payload = {**self.payload, "connection_link": ""}
        response = self.client.post("/api/v1/agents/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("connection_link", response.data["error"]["message"])

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
