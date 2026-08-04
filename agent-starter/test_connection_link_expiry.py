from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from test_runtime_identity import _load_runtime


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _claim(runtime, port: int, token: str, suffix: str = "") -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(
        "POST",
        "/veyra/connect/claim",
        body=json.dumps(
            {
                "token": token,
                "agent_id": f"agent-expiry-test{suffix}",
                "agent_name": "Expiry test",
                "runtime_credential": "c" * 48,
                "heartbeat_url": "https://veyra.invalid/heartbeat",
                "configuration_url": "https://veyra.invalid/configuration",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


class ConnectionLinkExpiryTests(unittest.TestCase):
    def test_link_is_valid_for_exactly_24_hours(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            state = runtime.load_state()

            self.assertEqual(
                state["token_expires_at"] - state["token_issued_at"],
                24 * 60 * 60,
            )
            with patch.object(
                runtime.time,
                "time",
                return_value=state["token_expires_at"] - 1,
            ):
                self.assertEqual(
                    runtime.token_is_valid(state, state["one_time_token"]),
                    (True, ""),
                )

    def test_link_is_expired_at_24_hours(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            state = runtime.load_state()

            with patch.object(
                runtime.time,
                "time",
                return_value=state["token_expires_at"],
            ):
                valid, detail = runtime.token_is_valid(
                    state,
                    state["one_time_token"],
                )

            self.assertFalse(valid)
            self.assertIn("expired", detail.lower())

    def test_successful_claim_invalidates_link_immediately(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            runtime.ensure_heartbeat_thread = lambda: None
            runtime.Handler.log_message = lambda *args, **kwargs: None
            state = runtime.load_state()
            server = runtime.ThreadingHTTPServer(("127.0.0.1", 0), runtime.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, _ = _claim(
                    runtime,
                    server.server_address[1],
                    state["one_time_token"],
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(status, 201)
            valid, detail = runtime.token_is_valid(
                runtime.load_state(),
                state["one_time_token"],
            )
            self.assertFalse(valid)
            self.assertIn("already been used", detail)

    def test_restart_preserves_unused_link_and_expiry(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary) / ".veyra-runtime"
            first = _load_runtime(state_dir)
            before = first.load_state()
            restarted = _load_runtime(state_dir)
            after = restarted.load_state()

            self.assertEqual(before["one_time_token"], after["one_time_token"])
            self.assertEqual(before["token_issued_at"], after["token_issued_at"])
            self.assertEqual(before["token_expires_at"], after["token_expires_at"])
            self.assertFalse(after["token_consumed"])

    def test_regeneration_revokes_old_link_and_keeps_new_link_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            old_state = runtime.load_state()
            old_token = old_state["one_time_token"]

            new_state = runtime.rotate_connection_token()

            old_valid, old_detail = runtime.token_is_valid(new_state, old_token)
            self.assertFalse(old_valid)
            self.assertIn("revoked", old_detail.lower())
            self.assertEqual(
                runtime.token_is_valid(
                    new_state,
                    new_state["one_time_token"],
                ),
                (True, ""),
            )
            self.assertNotIn(old_token, new_state["revoked_token_hashes"])
            self.assertIn(
                runtime.token_digest(old_token),
                new_state["revoked_token_hashes"],
            )

    def test_rotation_preserves_runtime_and_signing_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            before = (
                runtime.load_state()["runtime_id"],
                runtime.PUBLIC_KEY_TEXT,
                _file_hash(runtime.PRIVATE_KEY_PATH),
            )

            runtime.rotate_connection_token()

            after = (
                runtime.load_state()["runtime_id"],
                runtime.PUBLIC_KEY_TEXT,
                _file_hash(runtime.PRIVATE_KEY_PATH),
            )
            self.assertEqual(before, after)

    def test_expired_revoked_used_and_invalid_messages_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            state = runtime.load_state()
            token = state["one_time_token"]
            with patch.object(
                runtime.time,
                "time",
                return_value=state["token_expires_at"],
            ):
                expired = runtime.token_is_valid(state, token)[1]

            rotated = runtime.rotate_connection_token()
            revoked = runtime.token_is_valid(rotated, token)[1]
            rotated["token_consumed"] = True
            used = runtime.token_is_valid(
                rotated,
                rotated["one_time_token"],
            )[1]
            invalid = runtime.token_is_valid(rotated, "not-a-real-token")[1]

            self.assertEqual(len({expired, revoked, used, invalid}), 4)
            self.assertIn("expired", expired.lower())
            self.assertIn("revoked", revoked.lower())
            self.assertIn("already been used", used.lower())
            self.assertIn("invalid", invalid.lower())

    def test_only_one_simultaneous_claim_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            runtime.ensure_heartbeat_thread = lambda: None
            runtime.Handler.log_message = lambda *args, **kwargs: None
            token = runtime.load_state()["one_time_token"]
            server = runtime.ThreadingHTTPServer(("127.0.0.1", 0), runtime.Handler)
            server_thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
            )
            server_thread.start()
            barrier = threading.Barrier(6)
            results: list[tuple[int, dict]] = []
            results_lock = threading.Lock()

            def attempt(index: int) -> None:
                barrier.wait(timeout=5)
                result = _claim(
                    runtime,
                    server.server_address[1],
                    token,
                    suffix=f"-{index}",
                )
                with results_lock:
                    results.append(result)

            workers = [
                threading.Thread(target=attempt, args=(index,))
                for index in range(6)
            ]
            try:
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=10)
            finally:
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=5)

            self.assertEqual(len(results), 6)
            self.assertEqual(
                sorted(status for status, _ in results),
                [201, 403, 403, 403, 403, 403],
            )
            for status, payload in results:
                if status == 403:
                    self.assertIn("already been used", payload["detail"])

    def test_dashboard_shows_exact_expiry_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            runtime.Handler.log_message = lambda *args, **kwargs: None
            state = runtime.load_state()
            expected_expiry = runtime.connection_link_expiry(state)
            server = runtime.ThreadingHTTPServer(("127.0.0.1", 0), runtime.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1",
                    server.server_address[1],
                    timeout=5,
                )
                connection.request("GET", "/")
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertEqual(response.status, 200)
            self.assertIn(
                f"<time id='link-expiry'>{expected_expiry}</time>",
                body,
            )

    def test_startup_log_does_not_print_full_connection_token(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = _load_runtime(Path(temporary) / ".veyra-runtime")
            token = runtime.load_state()["one_time_token"]
            output = StringIO()

            with (
                patch.object(runtime, "ensure_heartbeat_thread"),
                patch.object(runtime, "provider_health", return_value=(True, "Ready")),
                patch.object(
                    runtime,
                    "ThreadingHTTPServer",
                    side_effect=RuntimeError("stop after startup output"),
                ),
                redirect_stdout(output),
                self.assertRaisesRegex(RuntimeError, "stop after startup output"),
            ):
                runtime.main()

            self.assertNotIn(token, output.getvalue())
            self.assertNotIn("veyra-connect://", output.getvalue())


if __name__ == "__main__":
    unittest.main()
