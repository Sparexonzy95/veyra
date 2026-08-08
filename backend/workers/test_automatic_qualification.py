import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from workers.automatic_qualification import (
    QUALIFICATION_SPECS,
    qualification_task_for_connection,
)
from workers.hosted_agent_connection import _credential_hash
from workers.models import HostedAgentConnection, WorkerAgent, WorkerQualificationRun


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@override_settings(
    VEYRA_PUBLIC_API_URL="http://127.0.0.1:8000",
    VEYRA_QUALIFICATION_MAX_ATTEMPTS=2,
    VEYRA_QUALIFICATION_LEASE_MINUTES=15,
)
class AutomaticQualificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(handle="auto-qualification-owner")
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.raw_credential = "runtime-credential-" + "x" * 48
        self.worker = WorkerAgent.objects.create(
            slug="automatic-qualification-agent",
            name="Automatic Qualification Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.READY_FOR_QUALIFICATION,
            provisioning_stage="READY_FOR_QUALIFICATION",
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="zai-org/glm-5.2",
            engine_version="runtime/1.0",
            engine_connected=True,
            engine_last_checked_at=timezone.now(),
            worker_wallet_address="0x76abc57539a8efde290d3236a0ab9f3955b3db9b",
            payout_wallet_address="0x76abc57539a8efde290d3236a0ab9f3955b3db9b",
            contract_authorised=True,
            skills=["Python", "Flask", "Pytest"],
            languages=["Python"],
            frameworks=["Flask"],
            testing_tools=["Pytest"],
            task_types=["API endpoint"],
        )
        self.connection = HostedAgentConnection.objects.create(
            worker=self.worker,
            runtime_id="runtime-auto-qualification",
            runtime_url="http://localhost:9100",
            public_key=b64url(public_key),
            public_key_fingerprint=hashlib.sha256(public_key).hexdigest(),
            protocol_version=1,
            runtime_version="runtime/1.0",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={"coding": True, "testing": True},
            credential_hash=_credential_hash(self.raw_credential),
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )

    def _signed_submission(self, task, source, return_code=0):
        files = [{"path": task["qualification_target_path"], "content": source}]
        canonical = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        files_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        message = (
            f"veyra-qualification-v1:{task['id']}:{files_hash}:{return_code}"
        ).encode("utf-8")
        return {
            "agent_id": str(self.worker.id),
            "qualification_id": task["id"],
            "lease_token": task["lease_token"],
            "files": files,
            "test_return_code": return_code,
            "test_output": "1 passed",
            "signature": b64url(self.private_key.sign(message)),
            "provider": "aiand",
            "model": "zai-org/glm-5.2",
            "runtime_version": "runtime/1.0",
        }

    def test_heartbeat_queues_and_leases_qualification_automatically(self):
        task = qualification_task_for_connection(self.connection)
        self.assertIsNotNone(task)
        self.assertEqual(task["type"], "automatic_qualification")
        self.assertEqual(task["qualification_target_path"], "src/service.py")
        self.assertEqual(task["allowed_submission_paths"], ["src/service.py"])
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.status, WorkerAgent.Status.TESTING)
        self.assertEqual(self.worker.provisioning_stage, "QUALIFICATION_RUNNING")

    def test_signed_passing_submission_activates_agent(self):
        task = qualification_task_for_connection(self.connection)
        source = '''def health_response():
    return {"status": "ok", "service": "veyra-qualification", "version": 1}
'''
        api = APIClient()
        response = api.post(
            "/api/v1/agent-runtime/qualification/submit/",
            data=self._signed_submission(task, source),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_credential}",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["passed"])
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.status, WorkerAgent.Status.ACTIVE)
        self.assertTrue(self.worker.test_assignment_passed)
        self.assertEqual(self.worker.provisioning_stage, "ACTIVE")

    def test_invalid_solution_fails_without_activating(self):
        task = qualification_task_for_connection(self.connection)
        source = '''def health_response():
    return {"status": "wrong"}
'''
        api = APIClient()
        response = api.post(
            "/api/v1/agent-runtime/qualification/submit/",
            data=self._signed_submission(task, source),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_credential}",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["passed"])
        self.worker.refresh_from_db()
        self.assertFalse(self.worker.test_assignment_passed)
        self.assertEqual(self.worker.provisioning_stage, "QUALIFICATION_FAILED")
        run = WorkerQualificationRun.objects.get(id=task["id"])
        self.assertEqual(run.status, WorkerQualificationRun.Status.FAILED)

    def test_declared_language_selects_versioned_controlled_target(self):
        cases = {
            "Python": "python",
            "TypeScript": "javascript",
            "Rust": "rust",
            "Go": "go",
            "Solidity": "solidity",
        }
        for language, spec_name in cases.items():
            with self.subTest(language=language):
                WorkerQualificationRun.objects.filter(worker=self.worker).delete()
                self.worker.languages = [language]
                self.worker.skills = [language]
                self.worker.status = WorkerAgent.Status.READY_FOR_QUALIFICATION
                self.worker.provisioning_stage = "READY_FOR_QUALIFICATION"
                self.worker.save(
                    update_fields=[
                        "languages",
                        "skills",
                        "status",
                        "provisioning_stage",
                        "updated_at",
                    ]
                )
                task = qualification_task_for_connection(self.connection)
                spec = QUALIFICATION_SPECS[spec_name]
                self.assertEqual(task["task_version"], spec["version"])
                self.assertEqual(task["qualification_target_path"], spec["target_path"])
                self.assertEqual(task["allowed_submission_paths"], [spec["target_path"]])
                self.assertEqual(task["test_command"], spec["test_command"])

    def test_submission_for_old_app_py_target_is_rejected(self):
        task = qualification_task_for_connection(self.connection)
        source = QUALIFICATION_SPECS["python"]["expected"]
        payload = self._signed_submission(task, source)
        payload["files"][0]["path"] = "app.py"
        api = APIClient()
        response = api.post(
            "/api/v1/agent-runtime/qualification/submit/",
            data=payload,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {self.raw_credential}",
        )
        self.assertEqual(response.status_code, 409, response.data)
        self.assertIn("src/service.py", str(response.data))
