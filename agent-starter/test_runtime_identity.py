from __future__ import annotations

import hashlib
import http.client
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parent / "server.py"


def _load_runtime(state_dir: Path):
    module_name = f"veyra_identity_test_{uuid.uuid4().hex}"
    environment = {
        "VEYRA_RUNTIME_STATE_DIR": str(state_dir),
        "VEYRA_RUNTIME_ENV_FILE": str(state_dir.parent / "missing-test.env"),
        "VEYRA_RUNTIME_WORKSPACE_ROOT": str(state_dir.parent / "workspaces"),
        "AI_API_KEY": "PASTE_OWNER_PAID_KEY_HERE",
        "AI_HEALTHCHECK_MODE": "mock",
        "RUNTIME_BIND_HOST": "127.0.0.1",
        "RUNTIME_PORT": "0",
        "RUNTIME_PUBLIC_HOST": "localhost",
        "RUNTIME_PUBLIC_PORT": "9300",
    }
    with patch.dict(os.environ, environment):
        spec = importlib.util.spec_from_file_location(module_name, SOURCE)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RuntimeIdentityTests(unittest.TestCase):
    def test_fresh_starter_initializes_with_bom_free_private_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / ".veyra-runtime"
            runtime = _load_runtime(state_dir)

            self.assertTrue(runtime.STATE_PATH.is_file())
            self.assertTrue(runtime.PRIVATE_KEY_PATH.is_file())
            self.assertFalse(runtime.STATE_PATH.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(runtime.load_state()["runtime_id"], runtime.INITIAL_STATE["runtime_id"])
            self.assertEqual(
                runtime.load_state()["signing_public_key"],
                runtime.PUBLIC_KEY_TEXT,
            )

    def test_two_fresh_copies_have_distinct_runtime_and_signing_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _load_runtime(root / "starter-one" / ".veyra-runtime")
            second = _load_runtime(root / "starter-two" / ".veyra-runtime")

            self.assertNotEqual(
                first.load_state()["runtime_id"],
                second.load_state()["runtime_id"],
            )
            self.assertNotEqual(first.PUBLIC_KEY_TEXT, second.PUBLIC_KEY_TEXT)
            self.assertNotEqual(
                first.PRIVATE_KEY_PATH.read_bytes(),
                second.PRIVATE_KEY_PATH.read_bytes(),
            )

    def test_restart_preserves_runtime_and_signing_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / ".veyra-runtime"
            first = _load_runtime(state_dir)
            before = (
                first.load_state()["runtime_id"],
                first.PUBLIC_KEY_TEXT,
                _sha256(first.PRIVATE_KEY_PATH),
            )

            restarted = _load_runtime(state_dir)
            after = (
                restarted.load_state()["runtime_id"],
                restarted.PUBLIC_KEY_TEXT,
                _sha256(restarted.PRIVATE_KEY_PATH),
            )

            self.assertEqual(before, after)

    def test_corrupt_state_is_rejected_without_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / ".veyra-runtime"
            runtime = _load_runtime(state_dir)
            key_hash = _sha256(runtime.PRIVATE_KEY_PATH)
            corrupt_bytes = b'{"runtime_id":'
            runtime.STATE_PATH.write_bytes(corrupt_bytes)

            with self.assertRaisesRegex(RuntimeError, "preserved and was not replaced"):
                _load_runtime(state_dir)

            self.assertEqual(runtime.STATE_PATH.read_bytes(), corrupt_bytes)
            self.assertEqual(_sha256(runtime.PRIVATE_KEY_PATH), key_hash)

    def test_original_logicbloom_identity_is_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = _load_runtime(root / "LogicBloom" / ".veyra-runtime")
            original_state_hash = _sha256(original.STATE_PATH)
            original_key_hash = _sha256(original.PRIVATE_KEY_PATH)

            fresh = _load_runtime(root / "FreshStarter" / ".veyra-runtime")

            self.assertNotEqual(
                original.load_state()["runtime_id"],
                fresh.load_state()["runtime_id"],
            )
            self.assertEqual(_sha256(original.STATE_PATH), original_state_hash)
            self.assertEqual(_sha256(original.PRIVATE_KEY_PATH), original_key_hash)

    def test_connection_url_onboarding_creates_no_pairing_code_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / ".veyra-runtime"
            runtime = _load_runtime(state_dir)
            state = runtime.load_state()
            token = state["one_time_token"]
            runtime.ensure_heartbeat_thread = lambda: None
            runtime.Handler.log_message = lambda *args, **kwargs: None
            http_server = runtime.ThreadingHTTPServer(
                ("127.0.0.1", 0),
                runtime.Handler,
            )
            thread = threading.Thread(target=http_server.serve_forever, daemon=True)
            thread.start()

            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    http_server.server_address[1],
                    timeout=5,
                )
                connection.request(
                    "POST",
                    "/veyra/connect/challenge",
                    body=json.dumps(
                        {
                            "token": token,
                            "challenge": "challenge-" + ("x" * 32),
                        }
                    ),
                    headers={"Content-Type": "application/json"},
                )
                challenge_response = connection.getresponse()
                challenge_payload = json.loads(challenge_response.read())
                self.assertEqual(challenge_response.status, 200)
                self.assertEqual(
                    challenge_payload["runtime_id"],
                    state["runtime_id"],
                )
                self.assertEqual(
                    challenge_payload["public_key"],
                    runtime.PUBLIC_KEY_TEXT,
                )

                connection.request(
                    "POST",
                    "/veyra/connect/claim",
                    body=json.dumps(
                        {
                            "token": token,
                            "agent_id": "agent-fresh-starter",
                            "agent_name": "Fresh starter",
                            "runtime_credential": "c" * 48,
                            "heartbeat_url": "https://veyra.invalid/heartbeat",
                            "configuration_url": "https://veyra.invalid/configuration",
                        }
                    ),
                    headers={"Content-Type": "application/json"},
                )
                claim_response = connection.getresponse()
                claim_response.read()
                self.assertEqual(claim_response.status, 201)
                connection.close()
            finally:
                http_server.shutdown()
                http_server.server_close()
                thread.join(timeout=5)

            connected_state = runtime.load_state()
            self.assertTrue(connected_state["token_consumed"])
            self.assertEqual(connected_state["agent_id"], "agent-fresh-starter")
            self.assertFalse(
                any("pair" in key.lower() for key in connected_state),
            )
            self.assertFalse(
                any("pair" in path.name.lower() for path in state_dir.rglob("*")),
            )


if __name__ == "__main__":
    unittest.main()
