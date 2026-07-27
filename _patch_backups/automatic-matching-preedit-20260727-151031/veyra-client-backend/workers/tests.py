from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from workers.circle_wallet import (
    WorkerWalletProvisioningResult,
    provision_worker_wallet,
)
from workers.engine import connect_worker_engine
from workers.models import WorkerAgent


ENGINE_SETTINGS = {
    "WORKER_ENGINE_EXECUTABLE": "opencode",
    "WORKER_ENGINE_HEALTHCHECK_ARGS": ["--version"],
    "WORKER_ENGINE_TIMEOUT_SECONDS": 5,
    "WORKER_ENGINE_MODEL": "zai-org/glm-5.2",
}


class WorkerAgentModelTests(TestCase):
    def test_profile_normalises_duplicate_skills(self):
        worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python", " python ", "Pytest"],
        )
        self.assertEqual(worker.skills, ["Python", "Pytest"])

    def test_worker_cannot_be_active_before_onboarding_is_complete(self):
        worker = WorkerAgent(
            slug="not-ready",
            name="Not Ready",
            status=WorkerAgent.Status.ACTIVE,
            skills=["Python"],
        )
        with self.assertRaises(ValidationError):
            worker.save()

    def test_non_active_worker_cannot_enable_discovery(self):
        worker = WorkerAgent(
            slug="discover-too-soon",
            name="Discover Too Soon",
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            discovery_enabled=True,
        )
        with self.assertRaises(ValidationError):
            worker.save()

    def test_connected_engine_requires_health_check_metadata(self):
        worker = WorkerAgent(
            slug="invalid-engine",
            name="Invalid Engine",
            status=WorkerAgent.Status.ENGINE_CONNECTED,
            skills=["Python"],
            engine_connected=True,
        )
        with self.assertRaises(ValidationError):
            worker.save()


class BootstrapWorkerCommandTests(TestCase):
    def test_command_is_idempotent(self):
        stdout = StringIO()
        call_command("bootstrap_worker", stdout=stdout)
        call_command("bootstrap_worker", stdout=stdout)

        self.assertEqual(WorkerAgent.objects.count(), 1)
        worker = WorkerAgent.objects.get(slug="veyra-code-agent")
        self.assertEqual(worker.status, WorkerAgent.Status.PROFILE_READY)
        self.assertEqual(worker.repository_strategy, WorkerAgent.RepositoryStrategy.FORK_PR)
        self.assertIn("Python", worker.skills)


@override_settings(**ENGINE_SETTINGS)
class WorkerEngineConnectionTests(TestCase):
    def setUp(self):
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent",
            name="Veyra Code Agent",
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python", "Pytest"],
            engine_model="zai-org/glm-5.2",
        )

    @patch("workers.engine.subprocess.run")
    @patch("workers.engine._resolve_executable", return_value="/usr/local/bin/opencode")
    def test_successful_health_check_connects_engine(self, _resolve, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="OpenCode 1.0.0\n",
            stderr="",
        )

        result = connect_worker_engine(self.worker)
        self.worker.refresh_from_db()

        self.assertTrue(result.connected)
        self.assertTrue(self.worker.engine_connected)
        self.assertEqual(self.worker.status, WorkerAgent.Status.ENGINE_CONNECTED)
        self.assertEqual(self.worker.engine_version, "OpenCode 1.0.0")
        self.assertIsNotNone(self.worker.engine_last_checked_at)
        self.assertEqual(self.worker.engine_last_error, "")
        self.assertEqual(self.worker.engine_connection_metadata["model"], "zai-org/glm-5.2")

    @patch("workers.engine._resolve_executable", return_value=None)
    def test_missing_executable_keeps_worker_disconnected(self, _resolve):
        result = connect_worker_engine(self.worker)
        self.worker.refresh_from_db()

        self.assertFalse(result.connected)
        self.assertFalse(self.worker.engine_connected)
        self.assertEqual(self.worker.status, WorkerAgent.Status.PROFILE_READY)
        self.assertIn("not found", self.worker.engine_last_error.lower())

    @patch("workers.engine.subprocess.run")
    @patch("workers.engine._resolve_executable", return_value="/usr/local/bin/opencode")
    def test_health_check_redacts_secret_like_output(self, _resolve, run):
        run.return_value = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="api_key=do-not-store-this",
        )

        result = connect_worker_engine(self.worker)
        self.worker.refresh_from_db()

        self.assertFalse(result.connected)
        self.assertNotIn("do-not-store-this", self.worker.engine_last_error)
        self.assertIn("[REDACTED]", self.worker.engine_last_error)

    @patch("workers.engine.subprocess.run")
    @patch("workers.engine._resolve_executable", return_value="/usr/local/bin/opencode")
    def test_connect_command_updates_existing_worker(self, _resolve, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="OpenCode 1.0.0\n",
            stderr="",
        )
        stdout = StringIO()

        call_command("connect_worker_engine", stdout=stdout)
        self.worker.refresh_from_db()

        self.assertTrue(self.worker.engine_connected)
        self.assertIn("Connected coding engine", stdout.getvalue())
        self.assertIn("zai-org/glm-5.2", stdout.getvalue())


@override_settings(**ENGINE_SETTINGS)
class WorkerAgentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = User.objects.create_user(handle="worker-admin", is_staff=True)
        self.regular = User.objects.create_user(handle="ordinary-user")
        self.payload = {
            "slug": "veyra-code-agent",
            "name": "Veyra Code Agent",
            "description": "Autonomous coding worker",
            "owner_type": "VEYRA",
            "skills": ["Python", "Flask", "Pytest"],
            "minimum_budget_usdc": "1.000000",
            "maximum_active_jobs": 1,
            "repository_strategy": "FORK_PR",
            "engine_provider": "OPENCODE",
            "engine_model": "zai-org/glm-5.2",
        }

    def test_staff_can_create_worker_profile(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post("/api/v1/worker/onboarding/agents/", self.payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], WorkerAgent.Status.PROFILE_READY)
        self.assertFalse(response.data["onboarding"]["ready_for_activation"])
        self.assertEqual(WorkerAgent.objects.count(), 1)

    def test_regular_user_cannot_manage_worker_profiles(self):
        self.client.force_authenticate(self.regular)
        response = self.client.post("/api/v1/worker/onboarding/agents/", self.payload, format="json")
        self.assertEqual(response.status_code, 403)

    @patch("workers.engine.subprocess.run")
    @patch("workers.engine._resolve_executable", return_value="/usr/local/bin/opencode")
    def test_staff_can_connect_worker_engine(self, _resolve, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="OpenCode 1.0.0\n",
            stderr="",
        )
        worker = WorkerAgent.objects.create(
            slug="api-worker",
            name="API Worker",
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
        )
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            f"/api/v1/worker/onboarding/agents/{worker.id}/connect-engine/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["engine"]["connected"])
        self.assertEqual(response.data["worker"]["status"], WorkerAgent.Status.ENGINE_CONNECTED)

    @patch("workers.engine._resolve_executable", return_value=None)
    def test_engine_endpoint_reports_unavailable_runtime(self, _resolve):
        worker = WorkerAgent.objects.create(
            slug="offline-worker",
            name="Offline Worker",
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
        )
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            f"/api/v1/worker/onboarding/agents/{worker.id}/connect-engine/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.data["engine"]["connected"])
        self.assertIn("not found", response.data["engine"]["message"].lower())


class WorkerWalletProvisioningTests(TestCase):
    def setUp(self):
        self.worker = WorkerAgent.objects.create(
            slug="veyra-code-agent-wallet",
            name="Veyra Code Agent Wallet",
            status=WorkerAgent.Status.ENGINE_CONNECTED,
            skills=["Python"],
            engine_connected=True,
            engine_version="OpenCode 1.17.18",
            engine_last_checked_at=timezone.now(),
        )

    @patch("workers.circle_wallet._create_circle_resources")
    def test_wallet_creation_updates_worker(self, create_resources):
        create_resources.return_value = (
            "wallet-set-1",
            {
                "id": "wallet-1",
                "address": "0x1111111111111111111111111111111111111111",
                "blockchain": "ARC-TESTNET",
                "account_type": "SCA",
            },
        )

        result = provision_worker_wallet(self.worker)
        self.worker.refresh_from_db()

        self.assertTrue(result.created)
        self.assertEqual(self.worker.status, WorkerAgent.Status.WALLET_READY)
        self.assertEqual(self.worker.circle_wallet_id, "wallet-1")
        self.assertEqual(
            self.worker.worker_wallet_address,
            "0x1111111111111111111111111111111111111111",
        )

    @patch("workers.circle_wallet._create_circle_resources")
    def test_existing_wallet_is_idempotent(self, create_resources):
        self.worker.circle_wallet_set_id = "wallet-set-existing"
        self.worker.circle_wallet_id = "wallet-existing"
        self.worker.worker_wallet_address = (
            "0x2222222222222222222222222222222222222222"
        )
        self.worker.save()

        result = provision_worker_wallet(self.worker)

        self.assertFalse(result.created)
        create_resources.assert_not_called()

    @patch("workers.management.commands.create_worker_wallet.provision_worker_wallet")
    def test_create_wallet_command(self, provision):
        provision.return_value = WorkerWalletProvisioningResult(
            worker_id=str(self.worker.id),
            wallet_set_id="wallet-set-1",
            wallet_id="wallet-1",
            address="0x3333333333333333333333333333333333333333",
            blockchain="ARC-TESTNET",
            account_type="SCA",
            created=True,
        )
        stdout = StringIO()

        call_command(
            "create_worker_wallet",
            slug=self.worker.slug,
            stdout=stdout,
        )

        self.assertIn("Created Circle worker wallet", stdout.getvalue())
        self.assertIn("Secrets stored in database: none", stdout.getvalue())


class WorkerWalletApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = User.objects.create_user(handle="wallet-admin", is_staff=True)
        self.worker = WorkerAgent.objects.create(
            slug="api-wallet-worker",
            name="API Wallet Worker",
            status=WorkerAgent.Status.ENGINE_CONNECTED,
            skills=["Python"],
            engine_connected=True,
            engine_version="OpenCode 1.17.18",
            engine_last_checked_at=timezone.now(),
        )

    @patch("workers.views.provision_worker_wallet")
    def test_staff_can_create_worker_wallet(self, provision):
        provision.return_value = WorkerWalletProvisioningResult(
            worker_id=str(self.worker.id),
            wallet_set_id="wallet-set-1",
            wallet_id="wallet-1",
            address="0x4444444444444444444444444444444444444444",
            blockchain="ARC-TESTNET",
            account_type="SCA",
            created=True,
        )
        self.client.force_authenticate(self.staff)

        response = self.client.post(
            f"/api/v1/worker/onboarding/agents/{self.worker.id}/create-wallet/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["wallet"]["created"])
