from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from eth_account import Account
from rest_framework.test import APIClient

from accounts.models import User, UserCapability
from workers.hosted_runtime import HOSTED_RUNTIME_MODE, ensure_hosted_runtime
from workers.models import RunnerAgentBinding, RunnerDevice, WorkerAgent
from workers.runtime_status import runtime_snapshot


class HostedRuntimeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(handle="hosted-runtime-owner")
        UserCapability.objects.create(
            user=self.owner,
            code=UserCapability.Code.AGENT_OWNER,
        )
        self.worker = WorkerAgent.objects.create(
            slug="hosted-agent",
            name="Hosted Agent",
            description="Builds and tests FastAPI endpoints.",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            specialisation=WorkerAgent.Specialisation.PYTHON_BACKEND,
            languages=["Python"],
            frameworks=["FastAPI"],
            testing_tools=["Pytest"],
            task_types=["API endpoint"],
            skills=["Python", "FastAPI", "Pytest", "API endpoint"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="external-runner",
        )

    def test_hosted_runtime_is_provisioned_without_pairing(self):
        result = ensure_hosted_runtime(self.worker)

        self.worker.refresh_from_db()
        snapshot = runtime_snapshot(self.worker)
        self.assertTrue(result.created)
        self.assertTrue(self.worker.engine_connected)
        self.assertEqual(self.worker.status, WorkerAgent.Status.ENGINE_CONNECTED)
        self.assertEqual(snapshot["runtime_mode"], HOSTED_RUNTIME_MODE)
        self.assertEqual(snapshot["managed_by"], "VEYRA")
        self.assertTrue(snapshot["auto_start"])
        self.assertTrue(snapshot["connected"])
        self.assertEqual(snapshot["status"], "ONLINE")
        self.assertEqual(snapshot["os_name"], "Veyra Cloud")

    def test_hosted_runtime_does_not_require_owner_heartbeat(self):
        result = ensure_hosted_runtime(self.worker)
        result.runner.last_seen_at = timezone.now() - timedelta(days=3)
        result.runner.save(update_fields=["last_seen_at", "updated_at"])

        self.worker.refresh_from_db()
        snapshot = runtime_snapshot(self.worker)
        self.assertEqual(snapshot["status"], "ONLINE")
        self.assertTrue(snapshot["connected"])

    def test_existing_owner_hosted_binding_is_replaced(self):
        local_account = Account.create()
        local_runner = RunnerDevice.objects.create(
            owner_user=self.owner,
            name="Old Laptop Runner",
            device_address=local_account.address,
            runner_version="0.1.0",
            os_name="Windows",
            architecture="AMD64",
            health=RunnerDevice.Health.HEALTHY,
            last_seen_at=timezone.now(),
        )
        binding = RunnerAgentBinding.objects.create(
            worker=self.worker,
            runner=local_runner,
        )

        result = ensure_hosted_runtime(self.worker)
        binding.refresh_from_db()

        self.assertNotEqual(binding.runner_id, local_runner.id)
        self.assertEqual(binding.runner_id, result.runner.id)
        self.assertEqual(result.runner.tools["runtime_mode"], HOSTED_RUNTIME_MODE)

    def test_owner_can_repair_hosted_runtime_through_api(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/agents/{self.worker.id}/runtime/hosted/provision/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["runtime"]["runtime_mode"], HOSTED_RUNTIME_MODE)
        self.assertTrue(response.data["runtime"]["connected"])
        self.assertEqual(response.data["agent"]["onboarding"]["current_step"], "github")
