import json
import secrets
import time
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from eth_account import Account
from eth_account.messages import encode_defunct
from rest_framework.test import APIClient

from accounts.models import User, UserCapability
from workers.models import (
    RunnerAgentBinding,
    RunnerDevice,
    RunnerPairingCode,
    WorkerAgent,
)
from workers.runner_auth import canonical_pairing_message, canonical_runner_message


@override_settings(
    VEYRA_RUNNER_PAIRING_TTL_SECONDS=600,
    VEYRA_RUNNER_ONLINE_WINDOW_SECONDS=35,
    VEYRA_RUNNER_SIGNATURE_MAX_SKEW_SECONDS=300,
)
class RuntimePairingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = User.objects.create_user(handle="runtime-owner")
        UserCapability.objects.create(
            user=self.owner,
            code=UserCapability.Code.AGENT_OWNER,
        )
        self.worker = self.create_worker("logic-bloom-agent", "Logic Bloom Agent")
        self.device_account = Account.create()

    def create_worker(self, slug, name):
        return WorkerAgent.objects.create(
            slug=slug,
            name=name,
            description="Builds and tests FastAPI endpoints.",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            specialisation=WorkerAgent.Specialisation.PYTHON_BACKEND,
            languages=["Python", "SQL"],
            frameworks=["Django", "Flask", "FastAPI"],
            testing_tools=["Pytest"],
            task_types=["API endpoint", "Bug fix", "Automated tests"],
            skills=[
                "Python",
                "SQL",
                "Django",
                "Flask",
                "FastAPI",
                "Pytest",
                "API endpoint",
                "Bug fix",
                "Automated tests",
            ],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="external-runner",
        )

    def create_code(self, worker=None):
        worker = worker or self.worker
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/agents/{worker.id}/runtime/pairing-code/",
            {},
            format="json",
        )
        self.client.force_authenticate(None)
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["pairing_code"]

    def pair(self, code, worker=None):
        runner_name = "Maryam Development Runner"
        proof = canonical_pairing_message(
            code=code,
            device_address=self.device_account.address,
            runner_name=runner_name,
        )
        device_signature = Account.sign_message(
            encode_defunct(text=proof),
            self.device_account.key,
        ).signature.hex()
        response = self.client.post(
            "/api/v1/runner/pair/",
            {
                "code": code,
                "device_address": self.device_account.address,
                "device_signature": device_signature,
                "runner_name": runner_name,
                "runner_version": "0.1.0",
                "environment": {
                    "os_name": "Windows",
                    "os_version": "11",
                    "architecture": "AMD64",
                    "python_version": "3.12.4",
                    "tools": {
                        "git": "2.50.0",
                        "python": "3.12.4",
                        "node": "22.17.0",
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def signed_heartbeat(self, runner_id, payload, *, nonce=None, timestamp=None):
        path = "/api/v1/runner/heartbeat/"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        nonce = nonce or secrets.token_hex(16)
        timestamp = timestamp or str(int(time.time()))
        canonical = canonical_runner_message(
            method="POST",
            path=path,
            timestamp=timestamp,
            nonce=nonce,
            body=body,
        )
        signature = Account.sign_message(
            encode_defunct(text=canonical),
            self.device_account.key,
        ).signature.hex()
        response = self.client.generic(
            "POST",
            path,
            data=body,
            content_type="application/json",
            HTTP_X_VEYRA_RUNNER_ID=str(runner_id),
            HTTP_X_VEYRA_TIMESTAMP=timestamp,
            HTTP_X_VEYRA_NONCE=nonce,
            HTTP_X_VEYRA_SIGNATURE=signature,
        )
        return response

    def test_owner_generates_one_time_code_without_plaintext_storage(self):
        code = self.create_code()
        self.assertRegex(code, r"^VYR-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        record = RunnerPairingCode.objects.get()
        self.assertNotEqual(record.code_hash, code)
        self.assertNotIn(code, record.code_hash)
        self.assertTrue(record.is_available)

    def test_pair_then_signed_heartbeat_moves_onboarding_to_three_of_seven(self):
        code = self.create_code()
        pair_response = self.pair(code)
        runner_id = pair_response.data["runner_id"]

        self.worker.refresh_from_db()
        self.assertFalse(self.worker.engine_connected)
        self.assertEqual(RunnerDevice.objects.count(), 1)
        self.assertEqual(RunnerAgentBinding.objects.count(), 1)
        self.assertIsNotNone(RunnerPairingCode.objects.get().consumed_at)

        heartbeat = self.signed_heartbeat(
            runner_id,
            {
                "runner_version": "0.1.0",
                "health": "HEALTHY",
                "health_message": "",
                "agent_ids": [str(self.worker.id)],
                "environment": {
                    "os_name": "Windows",
                    "os_version": "11",
                    "architecture": "AMD64",
                    "python_version": "3.12.4",
                    "tools": {"git": "2.50.0", "python": "3.12.4"},
                },
            },
        )
        self.assertEqual(heartbeat.status_code, 200, heartbeat.data)

        self.client.force_authenticate(self.owner)
        detail = self.client.get(f"/api/v1/agents/{self.worker.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["runtime"]["status"], "ONLINE")
        self.assertTrue(detail.data["runtime"]["connected"])
        self.assertTrue(detail.data["onboarding"]["checks"]["runtime"])
        completed = sum(detail.data["onboarding"]["checks"].values())
        self.assertEqual(completed, 3)
        self.assertEqual(detail.data["onboarding"]["current_step"], "wallet")
        self.assertNotIn("device_address", detail.data["runtime"])

    def test_signature_nonce_cannot_be_replayed(self):
        code = self.create_code()
        runner_id = self.pair(code).data["runner_id"]
        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time()))
        payload = {
            "runner_version": "0.1.0",
            "health": "HEALTHY",
            "agent_ids": [str(self.worker.id)],
        }
        first = self.signed_heartbeat(runner_id, payload, nonce=nonce, timestamp=timestamp)
        second = self.signed_heartbeat(runner_id, payload, nonce=nonce, timestamp=timestamp)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 403)

    def test_one_runner_can_host_multiple_agents(self):
        first_code = self.create_code(self.worker)
        first_pair = self.pair(first_code)
        second_worker = self.create_worker("second-agent", "Second Agent")
        second_code = self.create_code(second_worker)
        second_pair = self.pair(second_code)

        self.assertEqual(first_pair.data["runner_id"], second_pair.data["runner_id"])
        self.assertEqual(RunnerDevice.objects.count(), 1)
        self.assertEqual(RunnerAgentBinding.objects.filter(status="ACTIVE").count(), 2)

    def test_owner_can_revoke_only_the_agent_binding(self):
        code = self.create_code()
        runner_id = self.pair(code).data["runner_id"]
        heartbeat = self.signed_heartbeat(
            runner_id,
            {
                "runner_version": "0.1.0",
                "health": "HEALTHY",
                "agent_ids": [str(self.worker.id)],
            },
        )
        self.assertEqual(heartbeat.status_code, 200)

        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/agents/{self.worker.id}/runtime/revoke/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["runtime"]["status"], "REVOKED")
        self.assertFalse(response.data["agent"]["onboarding"]["checks"]["runtime"])
        self.assertEqual(RunnerDevice.objects.get().status, RunnerDevice.Status.ACTIVE)

    def test_stale_heartbeat_is_reported_offline(self):
        code = self.create_code()
        runner_id = self.pair(code).data["runner_id"]
        response = self.signed_heartbeat(
            runner_id,
            {
                "runner_version": "0.1.0",
                "health": "HEALTHY",
                "agent_ids": [str(self.worker.id)],
            },
        )
        self.assertEqual(response.status_code, 200)
        RunnerDevice.objects.update(last_seen_at=timezone.now() - timedelta(minutes=2))

        self.client.force_authenticate(self.owner)
        detail = self.client.get(f"/api/v1/agents/{self.worker.id}/")
        self.assertEqual(detail.data["runtime"]["status"], "OFFLINE")
        self.assertFalse(detail.data["onboarding"]["checks"]["runtime"])

    def test_pairing_code_cannot_be_reused(self):
        code = self.create_code()
        self.pair(code)
        runner_name = "Same Runner"
        proof = canonical_pairing_message(
            code=code,
            device_address=self.device_account.address,
            runner_name=runner_name,
        )
        signature = Account.sign_message(
            encode_defunct(text=proof),
            self.device_account.key,
        ).signature.hex()
        second = self.client.post(
            "/api/v1/runner/pair/",
            {
                "code": code,
                "device_address": self.device_account.address,
                "device_signature": signature,
                "runner_name": runner_name,
            },
            format="json",
        )
        self.assertEqual(second.status_code, 400)
