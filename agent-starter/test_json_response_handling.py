from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class _Response:
    def __init__(self, *, status_code=200, text="", content_type="application/json"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type} if content_type else {}


class _HeadersLike:
    """Minimal mapping-like stand-in for httpx.Headers (not a plain dict)."""

    def __init__(self, content_type: str):
        self.content_type = content_type

    def get(self, name: str, default=""):
        return self.content_type if name.casefold() == "content-type" else default


class JsonResponseHandlingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["VEYRA_RUNTIME_STATE_DIR"] = cls.temp_dir.name
        os.environ["AI_HEALTHCHECK_MODE"] = "mock"
        source = Path(__file__).resolve().parent / "server.py"
        spec = importlib.util.spec_from_file_location("veyra_json_runtime_server", source)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.server = module

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_truncated_model_json_becomes_actionable_runtime_error(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r"malformed or incomplete JSON.*Parser reported: Expecting value.*Response began: \{\"summary\":",
        ):
            self.server._extract_json_object('{"summary":')

    def test_literal_control_characters_inside_model_strings_are_repaired(self):
        payload = self.server._extract_json_object(
            '{"summary":"ok","files":[{"path_id":"app.py",'
            '"content":"first line\n\tsecond line\r\n"}]}'
        )

        self.assertEqual(
            payload,
            {
                "summary": "ok",
                "files": [
                    {
                        "path_id": "app.py",
                        "content": "first line\n\tsecond line\r\n",
                    }
                ],
            },
        )

    def test_non_string_control_character_is_not_repaired(self):
        with self.assertRaisesRegex(RuntimeError, r"malformed JSON"):
            self.server._extract_json_object('{"summary":"ok",\u0001"files":[]}')

    def test_empty_provider_body_is_rejected_before_json_parser(self):
        with self.assertRaisesRegex(RuntimeError, r"empty response with status 200"):
            self.server._response_json(_Response(text=""), "The owner AI provider")

    def test_html_provider_body_reports_content_type_and_excerpt(self):
        with self.assertRaisesRegex(
            RuntimeError,
            r"text/html instead of JSON.*upstream unavailable",
        ):
            self.server._response_json(
                _Response(text="<html>upstream unavailable</html>", content_type="text/html"),
                "The owner AI provider",
            )

    def test_mapping_like_headers_are_checked_for_content_type(self):
        response = _Response(text="gateway error", content_type="")
        response.headers = _HeadersLike("text/plain; charset=utf-8")

        with self.assertRaisesRegex(RuntimeError, r"text/plain instead of JSON.*gateway error"):
            self.server._response_json(response, "The owner AI provider")

    def test_valid_provider_json_is_returned(self):
        payload = self.server._response_json(
            _Response(text='{"choices": []}'),
            "The owner AI provider",
        )
        self.assertEqual(payload, {"choices": []})

    def test_json_only_test_double_remains_supported(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"choices": []}

        payload = self.server._response_json(response, "The owner AI provider")

        self.assertEqual(payload, {"choices": []})

    def test_ai_transport_timeout_is_retried_once_inside_same_step(self):
        response = _Response(text='{"choices": []}')
        with patch.dict(
            os.environ,
            {
                "VEYRA_MODEL_TRANSPORT_ATTEMPTS": "2",
                "VEYRA_MODEL_TRANSPORT_RETRY_DELAY_SECONDS": "0",
            },
        ), patch.object(
            self.server.httpx,
            "post",
            side_effect=[self.server.httpx.ReadTimeout("slow provider"), response],
        ) as post:
            payload = self.server._post_ai_json(
                {"model": "test"},
                source="The owner AI provider",
                timeout=120,
            )

        self.assertEqual(payload, {"choices": []})
        self.assertEqual(post.call_count, 2)

    def test_ai_transport_retry_stops_at_configured_bound(self):
        with patch.dict(
            os.environ,
            {
                "VEYRA_MODEL_TRANSPORT_ATTEMPTS": "2",
                "VEYRA_MODEL_TRANSPORT_RETRY_DELAY_SECONDS": "0",
            },
        ), patch.object(
            self.server.httpx,
            "post",
            side_effect=self.server.httpx.ReadTimeout("slow provider"),
        ) as post:
            with self.assertRaisesRegex(
                RuntimeError,
                r"failed after 2 transport attempt\(s\): slow provider",
            ):
                self.server._post_ai_json(
                    {"model": "test"},
                    source="The owner AI provider",
                    timeout=120,
                )

        self.assertEqual(post.call_count, 2)

    def test_empty_model_files_are_a_bounded_repair_error(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputRepairError,
            r"returned no changed files.*at least one complete file",
        ):
            self.server._extract_model_files('{"summary":"No work","files":[]}')

    def test_malformed_model_files_are_a_bounded_repair_error(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputRepairError,
            r"malformed or incomplete JSON",
        ):
            self.server._extract_model_files('{"summary":')

    def test_empty_model_files_consume_one_bounded_repair_attempt(self):
        repaired_files = [{"path": "app.py", "content": "print('fixed')\n"}]
        model = Mock(
            side_effect=[
                self.server.ModelOutputRepairError(
                    "The AI model returned no changed files."
                ),
                (repaired_files, "Fixed the implementation."),
            ]
        )
        with tempfile.TemporaryDirectory() as workspace, patch.object(
            self.server, "_run_job_model", model
        ), patch.object(self.server, "_apply_model_files") as apply_files:
            files, summary, repairs = self.server._generate_and_apply_model_files(
                {"policy": {"maximum_repair_attempts": 1, "allowed_paths": ["app.py"]}},
                Path(workspace),
            )

        self.assertEqual(files, repaired_files)
        self.assertEqual(summary, "Fixed the implementation.")
        self.assertEqual(repairs, 1)
        self.assertIn(
            "MODEL OUTPUT REPAIR ERROR: The AI model returned no changed files.",
            model.call_args_list[1].kwargs["previous_test_output"],
        )
        apply_files.assert_called_once()


if __name__ == "__main__":
    unittest.main()