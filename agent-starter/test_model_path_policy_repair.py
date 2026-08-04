from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch


class ModelPathPolicyRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state_dir = tempfile.TemporaryDirectory()
        os.environ["VEYRA_RUNTIME_STATE_DIR"] = cls.state_dir.name
        os.environ["AI_HEALTHCHECK_MODE"] = "mock"
        source = Path(__file__).resolve().parent / "server.py"
        spec = importlib.util.spec_from_file_location("veyra_model_path_repair_server", source)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.server = module

    @classmethod
    def tearDownClass(cls):
        cls.state_dir.cleanup()

    def setUp(self):
        self.workspace_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.workspace_dir.name)
        (self.workspace / "app.py").write_text("OLD\n", encoding="utf-8")
        (self.workspace / "tests").mkdir()
        (self.workspace / "tests" / "test_app.py").write_text("OLD TEST\n", encoding="utf-8")

    def tearDown(self):
        self.workspace_dir.cleanup()

    def _task(self, maximum_repairs: int = 2):
        return {
            "policy": {
                "allowed_paths": ["app.py", "tests/**"],
                "forbidden_paths": [".github/**"],
                "allow_new_dependencies": False,
                "allow_database_migrations": False,
                "maximum_repair_attempts": maximum_repairs,
            },
            "work": {"title": "Add health endpoint"},
        }

    def test_near_miss_path_is_reprompted_not_silently_remapped(self):
        responses = [
            ([{"path": "pp.py", "content": "WRONG\n"}], "bad path"),
            ([{"path": "app.py", "content": "FIXED\n"}], "corrected path"),
        ]
        with patch.object(self.server, "_run_job_model", side_effect=responses) as model:
            files, summary, repairs = self.server._generate_and_apply_model_files(
                self._task(), self.workspace
            )

        self.assertEqual(repairs, 1)
        self.assertEqual(files[0]["path"], "app.py")
        self.assertEqual(summary, "corrected path")
        self.assertEqual((self.workspace / "app.py").read_text(encoding="utf-8"), "FIXED\n")
        self.assertFalse((self.workspace / "pp.py").exists())
        feedback = model.call_args_list[1].kwargs["previous_test_output"]
        self.assertIn("pp.py", feedback)
        self.assertIn("app.py", feedback)

    def test_policy_stays_strict_when_no_repair_is_available(self):
        with patch.object(
            self.server,
            "_run_job_model",
            return_value=([{"path": "pp.py", "content": "WRONG\n"}], "bad path"),
        ):
            with self.assertRaises(self.server.ModelOutputPolicyError):
                self.server._generate_and_apply_model_files(
                    self._task(maximum_repairs=0), self.workspace
                )

    def test_pytest_command_uses_the_runtime_python_environment(self):
        self.assertEqual(
            self.server._command_args("pytest -q tests/test_app.py"),
            [sys.executable, "-m", "pytest", "-q", "tests/test_app.py"],
        )
        self.assertFalse((self.workspace / "pp.py").exists())
        self.assertEqual((self.workspace / "app.py").read_text(encoding="utf-8"), "OLD\n")

    def test_changed_files_preserves_first_character_of_modified_path(self):
        self.server._run_process(
            ["git", "init", "-q"],
            cwd=self.workspace,
            timeout=30,
        ).check_returncode()
        self.server._run_process(
            ["git", "config", "user.name", "Veyra Test"],
            cwd=self.workspace,
            timeout=30,
        ).check_returncode()
        self.server._run_process(
            ["git", "config", "user.email", "test@veyra.local"],
            cwd=self.workspace,
            timeout=30,
        ).check_returncode()
        self.server._run_process(
            ["git", "add", "."],
            cwd=self.workspace,
            timeout=30,
        ).check_returncode()
        self.server._run_process(
            ["git", "commit", "-q", "-m", "baseline"],
            cwd=self.workspace,
            timeout=30,
        ).check_returncode()
        (self.workspace / "app.py").write_text("FIXED\n", encoding="utf-8")

        self.assertEqual(self.server._changed_files(self.workspace), ["app.py"])

    def test_recursive_allowed_path_rule_matches_nested_tests(self):
        self.assertTrue(
            self.server._path_matches_policy_rule("tests/test_app.py", "tests/**")
        )
        self.assertTrue(
            self.server._path_matches_policy_rule("tests/unit/test_health.py", "tests/**")
        )
        self.assertFalse(
            self.server._path_matches_policy_rule("docs/test_health.py", "tests/**")
        )

    def test_recursive_forbidden_rule_blocks_workflow(self):
        task = self._task()
        with self.assertRaises(self.server.ModelOutputPolicyError):
            self.server._enforce_job_path_policy(
                task, [".github/workflows/ci.yml"]
            )

    def test_model_prompt_repeats_exact_allowed_paths_in_system_contract(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "fixed",
                                "files": [{"path_id": "FILE_1", "content": "FIXED\n"}],
                            }
                        )
                    }
                }
            ]
        }
        with patch.object(self.server.httpx, "post", return_value=response) as post:
            self.server.AI_API_KEY = "test-key"
            self.server._run_job_model(self._task(), self.workspace)

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["temperature"], 0)
        system_prompt = payload["messages"][0]["content"]
        user_prompt = payload["messages"][1]["content"]
        for expected in ('["app.py", "tests/**"]', "character for character"):
            self.assertIn(expected, system_prompt + user_prompt)
        self.assertIn('"FILE_1": "app.py"', system_prompt + user_prompt)

    def test_trusted_path_id_is_bound_to_exact_funded_path(self):
        content = json.dumps(
            {
                "summary": "fixed",
                "files": [{"path_id": "FILE_1", "content": "FIXED\n"}],
            }
        )
        files, summary = self.server._extract_model_files(
            content,
            path_ids={"FILE_1": "app.py"},
        )
        self.assertEqual(files, [{"path": "app.py", "content": "FIXED\n"}])
        self.assertEqual(summary, "fixed")

    def test_trusted_path_id_rejects_conflicting_model_path(self):
        content = json.dumps(
            {
                "summary": "bad",
                "files": [
                    {"path_id": "FILE_1", "path": "pp.py", "content": "WRONG\n"}
                ],
            }
        )
        with self.assertRaises(self.server.ModelOutputPolicyError):
            self.server._extract_model_files(
                content,
                path_ids={"FILE_1": "app.py"},
            )


if __name__ == "__main__":
    unittest.main()
