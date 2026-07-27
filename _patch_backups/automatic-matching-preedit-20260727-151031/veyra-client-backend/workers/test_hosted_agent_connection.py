import base64
import hashlib
import json
from unittest.mock import patch

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from workers.hosted_agent_connection import (
    HostedAgentConnectionError,
    _credential_hash,
    connect_hosted_agent,
    parse_connection_link,
)
from workers.models import HostedAgentConnection, WorkerAgent


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


@override_settings(
    DEBUG=True,
    VEYRA_ALLOW_LOCAL_AGENT_RUNTIME=True,
    VEYRA_PUBLIC_API_URL="http://127.0.0.1:8000",
    VEYRA_AGENT_CONNECTION_PROTOCOL_VERSION=1,
)
class HostedAgentConnectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(handle="runtime-owner")
        self.worker = WorkerAgent.objects.create(
            slug="owner-runtime-agent",
            name="Owner Runtime Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="pending-owner-runtime",
        )
        self.link = (
            "veyra-connect://localhost:9100/connect/"
            "abcdefghijklmnopqrstuvwxyz123456?protocol=1"
        )

    def test_parses_local_copy_link_in_debug(self):
        parsed = parse_connection_link(self.link)
        self.assertEqual(parsed.runtime_base_url, "http://localhost:9100")
        self.assertEqual(parsed.protocol_version, 1)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", parsed.runtime_base_url)

    @override_settings(DEBUG=False, VEYRA_ALLOW_LOCAL_AGENT_RUNTIME=False)
    def test_rejects_local_runtime_outside_debug(self):
        with self.assertRaises(HostedAgentConnectionError):
            parse_connection_link(self.link)

    def test_rejects_malformed_port(self):
        with self.assertRaises(HostedAgentConnectionError):
            parse_connection_link(
                "veyra-connect://localhost:not-a-port/connect/"
                "abcdefghijklmnopqrstuvwxyz123456?protocol=1"
            )

    def test_verifies_signature_and_claims_runtime_without_ai_key(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = b64url(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        seen_claim = {}

        def handler(request: httpx.Request):
            payload = json.loads(request.content.decode("utf-8"))
            if request.url.path == "/veyra/connect/challenge":
                challenge = payload["challenge"]
                runtime_id = "runtime-test-1"
                signature = private_key.sign(
                    f"veyra-connect-v1:{challenge}:{runtime_id}".encode("utf-8")
                )
                return httpx.Response(
                    200,
                    json={
                        "runtime_id": runtime_id,
                        "challenge": challenge,
                        "signature": b64url(signature),
                        "public_key": public_key,
                        "runtime_version": "test-runtime/1.0",
                        "protocol_version": 1,
                        "provider": "aiand",
                        "model": "zai-org/glm-5.2",
                        "provider_ready": True,
                        "provider_message": "Ready",
                        "capabilities": {"coding": True, "testing": True},
                    },
                )
            if request.url.path == "/veyra/connect/claim":
                seen_claim.update(payload)
                return httpx.Response(
                    201,
                    json={
                        "connected": True,
                        "runtime_id": "runtime-test-1",
                        "agent_id": payload["agent_id"],
                    },
                )
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = connect_hosted_agent(
            worker=self.worker,
            connection_link=self.link,
            client=client,
        )

        self.worker.refresh_from_db()
        connection = self.worker.hosted_connection
        self.assertEqual(result.runtime_id, "runtime-test-1")
        self.assertTrue(self.worker.engine_connected)
        self.assertEqual(self.worker.engine_model, "zai-org/glm-5.2")
        self.assertEqual(connection.provider, "aiand")
        self.assertEqual(connection.status, HostedAgentConnection.Status.CONNECTED)
        self.assertNotEqual(connection.credential_hash, seen_claim["runtime_credential"])
        self.assertNotIn("api_key", json.dumps(seen_claim).lower())
        self.assertNotIn("one_time_token", json.dumps(connection.metadata).lower())

    def test_rejects_runtime_owned_by_another_agent_before_claim(self):
        private_key = Ed25519PrivateKey.generate()
        public_key_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        public_key = b64url(public_key_raw)
        other = WorkerAgent.objects.create(
            slug="other-runtime-agent",
            name="Other Runtime Agent",
            owner_type=WorkerAgent.OwnerType.EXTERNAL,
            owner_user=self.owner,
            status=WorkerAgent.Status.PROFILE_READY,
            skills=["Python"],
            languages=["Python"],
            engine_provider=WorkerAgent.EngineProvider.CUSTOM,
            engine_model="pending-owner-runtime",
        )
        HostedAgentConnection.objects.create(
            worker=other,
            runtime_id="already-owned-runtime",
            runtime_url="http://localhost:9100",
            public_key=public_key,
            public_key_fingerprint=hashlib.sha256(public_key_raw).hexdigest(),
            protocol_version=1,
            runtime_version="test-runtime/1.0",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={"coding": True},
            credential_hash="b" * 64,
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        claim_calls = 0

        def handler(request: httpx.Request):
            nonlocal claim_calls
            payload = json.loads(request.content.decode("utf-8"))
            if request.url.path == "/veyra/connect/challenge":
                challenge = payload["challenge"]
                signature = private_key.sign(
                    f"veyra-connect-v1:{challenge}:already-owned-runtime".encode("utf-8")
                )
                return httpx.Response(
                    200,
                    json={
                        "runtime_id": "already-owned-runtime",
                        "challenge": challenge,
                        "signature": b64url(signature),
                        "public_key": public_key,
                        "runtime_version": "test-runtime/1.0",
                        "protocol_version": 1,
                        "provider": "aiand",
                        "model": "zai-org/glm-5.2",
                        "provider_ready": True,
                        "capabilities": {"coding": True},
                    },
                )
            if request.url.path == "/veyra/connect/claim":
                claim_calls += 1
                return httpx.Response(201, json={"connected": True})
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with self.assertRaises(HostedAgentConnectionError):
            connect_hosted_agent(
                worker=self.worker,
                connection_link=self.link,
                client=client,
            )
        self.assertEqual(claim_calls, 0)

    def test_heartbeat_requires_runtime_credential(self):
        raw_credential = "runtime-credential-" + "x" * 48
        connection = HostedAgentConnection.objects.create(
            worker=self.worker,
            runtime_id="runtime-heartbeat",
            runtime_url="http://localhost:9100",
            public_key="public-key",
            public_key_fingerprint="f" * 64,
            protocol_version=1,
            runtime_version="test-runtime/1.0",
            provider="aiand",
            model_name="zai-org/glm-5.2",
            provider_ready=True,
            capabilities={"coding": True},
            credential_hash=_credential_hash(raw_credential),
            status=HostedAgentConnection.Status.CONNECTED,
            connected_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        api = APIClient()

        rejected = api.post(
            "/api/v1/agent-runtime/heartbeat/",
            {"agent_id": str(self.worker.id), "health": "HEALTHY"},
            format="json",
            HTTP_AUTHORIZATION="Bearer wrong-token",
        )
        self.assertEqual(rejected.status_code, 401)

        accepted = api.post(
            "/api/v1/agent-runtime/heartbeat/",
            {
                "agent_id": str(self.worker.id),
                "health": "HEALTHY",
                "provider_ready": True,
                "runtime_version": "test-runtime/1.1",
                "model": "zai-org/glm-5.2",
            },
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw_credential}",
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)
        connection.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(connection.runtime_version, "test-runtime/1.1")
        self.assertTrue(self.worker.engine_connected)
        self.assertEqual(self.worker.engine_version, "test-runtime/1.1")
        self.assertEqual(self.worker.engine_model, "zai-org/glm-5.2")

        configuration = api.get(
            "/api/v1/agent-runtime/configuration/",
            HTTP_AUTHORIZATION=f"Bearer {raw_credential}",
            HTTP_X_VEYRA_AGENT_ID=str(self.worker.id),
        )
        self.assertEqual(configuration.status_code, 200, configuration.data)
        self.assertEqual(configuration.data["agent"]["id"], str(self.worker.id))
        self.assertEqual(configuration.data["runtime"]["provider"], "aiand")
        self.assertNotIn("api_key", json.dumps(configuration.data).lower())
