from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _tool_works(
    server,
    workspace: Path,
    executable: str,
    *arguments: str,
) -> bool:
    resolved = shutil.which(executable)
    if not resolved:
        return False
    try:
        return server._run_process(
            [resolved, *arguments],
            cwd=workspace,
            timeout=15,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class MultiStackRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state_dir = tempfile.TemporaryDirectory()
        os.environ["VEYRA_RUNTIME_STATE_DIR"] = cls.state_dir.name
        os.environ["AI_HEALTHCHECK_MODE"] = "mock"
        source = Path(__file__).resolve().parent / "server.py"
        spec = importlib.util.spec_from_file_location("veyra_multistack_server", source)
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

    def tearDown(self):
        self.workspace_dir.cleanup()

    def _write(self, path: str, content: str = "") -> None:
        destination = self.workspace.joinpath(*path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def _reset_workspace(self) -> None:
        self.workspace_dir.cleanup()
        self.workspace_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.workspace_dir.name)

    def _run_detected_fixture(
        self,
        *,
        stack: str,
        files: dict[str, str],
        expected_command: str,
    ) -> str:
        self._reset_workspace()
        for path, content in files.items():
            self._write(path, content)
        plan = self.server._detect_validation_plan(self.workspace)
        self.assertEqual(plan["stack"], stack)
        self.assertEqual(plan["commands"], [expected_command])
        code, output, command = self.server._run_validation_commands(
            {"policy": {"maximum_execution_minutes": 5}},
            self.workspace,
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(command, expected_command)
        return output

    def test_qualification_target_is_one_explicit_controlled_path(self):
        task = {
            "qualification_target_path": "cmd/api/main.go",
            "allowed_submission_paths": ["cmd/api/main.go"],
            "starter_files": [
                {"path": "cmd/api/main.go", "content": "package main\n"},
                {"path": "go.mod", "content": "module example\n"},
            ],
        }
        self.assertEqual(
            self.server._qualification_target(task),
            "cmd/api/main.go",
        )
        task["allowed_submission_paths"] = ["app.py"]
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.server._qualification_target(task)

    def test_qualification_target_rejects_protected_and_ambiguous_paths(self):
        for target, allowed in (
            (".env", [".env"]),
            ("src/index.js", ["src/index.js", "tests/index.test.js"]),
        ):
            with self.subTest(target=target):
                task = {
                    "qualification_target_path": target,
                    "allowed_submission_paths": allowed,
                    "starter_files": [{"path": target, "content": ""}],
                }
                with self.assertRaises(RuntimeError):
                    self.server._qualification_target(task)

    def test_repository_detector_matrix(self):
        cases = (
            ("python", {"requirements.txt": "pytest\n", "tests/test_api.py": ""}, "python -m pytest -q"),
            ("node", {"package.json": json.dumps({"scripts": {"test": "node --test"}})}, "npm test"),
            ("hardhat", {"package.json": json.dumps({"devDependencies": {"hardhat": "3.0.0"}}), "hardhat.config.ts": ""}, "npx --no-install hardhat test"),
            ("rust", {"Cargo.toml": "[package]\nname='demo'\nversion='0.1.0'\n"}, "cargo test --quiet"),
            ("go", {"go.mod": "module example\n"}, "go test ./..."),
            ("maven", {"pom.xml": "<project />\n"}, "mvn test"),
            ("gradle", {"build.gradle.kts": "plugins {}\n"}, "gradle test"),
            ("php", {"composer.json": json.dumps({"scripts": {"test": "phpunit"}})}, "composer test"),
            ("ruby", {"Gemfile": "source 'https://rubygems.org'\n", "Rakefile": "task :test\n"}, "bundle exec rake test"),
            ("foundry", {"foundry.toml": "[profile.default]\n"}, "forge test -q"),
        )
        for expected_stack, files, expected_command in cases:
            with self.subTest(stack=expected_stack):
                self._reset_workspace()
                for path, content in files.items():
                    self._write(path, content)
                plan = self.server._detect_validation_plan(self.workspace)
                self.assertEqual(plan["stack"], expected_stack)
                self.assertEqual(plan["source"], "repository_detection")
                self.assertEqual(plan["commands"], [expected_command])
                self.server._command_args(expected_command)

    def test_installed_toolchains_execute_detected_smoke_repositories(self):
        cases = [
            (
                "python",
                True,
                {
                    "requirements.txt": "",
                    "test_smoke.py": (
                        "import unittest\n\n"
                        "class SmokeTests(unittest.TestCase):\n"
                        "    def test_smoke(self):\n"
                        "        self.assertEqual(2 + 2, 4)\n"
                    ),
                },
                "python -m unittest discover -v",
            ),
            (
                "node",
                _tool_works(self.server, self.workspace, "node", "--version")
                and _tool_works(self.server, self.workspace, "npm", "--version"),
                {
                    "package.json": json.dumps({"scripts": {"test": "node --test"}}),
                    "smoke.test.js": (
                        'const test = require("node:test");\n'
                        'const assert = require("node:assert/strict");\n'
                        'test("smoke", () => assert.equal(2 + 2, 4));\n'
                    ),
                },
                "npm test",
            ),
            (
                "rust",
                _tool_works(self.server, self.workspace, "cargo", "--version"),
                {
                    "Cargo.toml": (
                        "[package]\n"
                        'name = "veyra_smoke"\n'
                        'version = "0.1.0"\n'
                        'edition = "2021"\n'
                    ),
                    "src/lib.rs": (
                        "#[cfg(test)] mod tests { "
                        "#[test] fn smoke() { assert_eq!(2 + 2, 4); } }\n"
                    ),
                },
                "cargo test --quiet",
            ),
            (
                "go",
                _tool_works(self.server, self.workspace, "go", "version"),
                {
                    "go.mod": "module example.com/veyra-smoke\n\ngo 1.20\n",
                    "smoke_test.go": (
                        "package smoke\n\n"
                        'import "testing"\n\n'
                        "func TestSmoke(t *testing.T) {\n"
                        '    if 2+2 != 4 { t.Fatal("math") }\n'
                        "}\n"
                    ),
                },
                "go test ./...",
            ),
        ]
        executed: list[str] = []
        for stack, available, files, expected_command in cases:
            if not available:
                continue
            with self.subTest(stack=stack):
                output = self._run_detected_fixture(
                    stack=stack,
                    files=files,
                    expected_command=expected_command,
                )
                self.assertTrue(output.strip())
                executed.append(stack)
        self.assertIn("python", executed)

    def test_explicit_funded_commands_take_precedence_over_ambiguous_repo(self):
        self._write("Cargo.toml", "[package]\nname='demo'\nversion='0.1.0'\n")
        self._write("go.mod", "module example\n")
        task = {"policy": {"required_commands": ["go test ./internal/..."]}}
        self.assertEqual(
            self.server._validation_plan(task, self.workspace),
            {
                "stack": "go",
                "commands": ["go test ./internal/..."],
                "source": "funded_policy",
            },
        )

    def test_ambiguous_and_unsupported_repositories_fail_deterministically(self):
        with self.assertRaises(self.server.RuntimePreflightError) as unsupported:
            self.server._detect_validation_plan(self.workspace)
        self.assertEqual(unsupported.exception.code, "UNSUPPORTED_TOOLCHAIN")

        self._write("Cargo.toml", "[package]\nname='demo'\nversion='0.1.0'\n")
        self._write("go.mod", "module example\n")
        with self.assertRaises(self.server.RuntimePreflightError) as ambiguous:
            self.server._detect_validation_plan(self.workspace)
        self.assertEqual(ambiguous.exception.code, "AMBIGUOUS_TOOLCHAIN")

    def test_dependency_operations_are_not_valid_validation_commands(self):
        for command in (
            "npm install",
            "cargo fetch",
            "go mod download",
            "composer install",
            "bundle install",
        ):
            with self.subTest(command=command):
                with self.assertRaises(self.server.RuntimePreflightError) as raised:
                    self.server._command_args(command)
                self.assertEqual(raised.exception.code, "UNSAFE_VALIDATION_COMMAND")
                self.server._command_args(command, preparation=True)

    def test_missing_tool_has_stable_preflight_code(self):
        with patch.object(self.server.shutil, "which", return_value=None):
            with self.assertRaises(self.server.RuntimePreflightError) as raised:
                self.server._require_command_tool(["cargo", "test"], self.workspace)
        self.assertEqual(raised.exception.code, "TOOLCHAIN_UNAVAILABLE")

    def test_node_lockfile_selects_reproducible_dependency_preparation(self):
        self._write("package.json", json.dumps({"scripts": {"test": "node --test"}}))
        self._write("package-lock.json", "{}\n")
        completed = subprocess.CompletedProcess(
            args=["npm", "ci"],
            returncode=0,
            stdout="installed",
            stderr="",
        )
        with (
            patch.object(self.server, "_require_command_tool"),
            patch.object(self.server, "_run_process", return_value=completed) as run,
        ):
            _, output, command = self.server._prepare_validation_environment(
                {"policy": {}},
                self.workspace,
                self.workspace / ".python",
            )
        self.assertEqual(command, "npm ci")
        self.assertEqual(output, "installed")
        self.assertEqual(run.call_args.args[0], ["npm", "ci"])

    def test_evidence_records_plan_and_structured_failure_code(self):
        plan = {
            "stack": "rust",
            "source": "repository_detection",
            "commands": ["cargo test --quiet"],
        }
        self.assertEqual(
            self.server._validation_plan_evidence(plan),
            {
                "validation_toolchain": "rust",
                "validation_command_source": "repository_detection",
                "validation_commands": ["cargo test --quiet"],
            },
        )
        error = self.server.RuntimePreflightError(
            "cargo is missing",
            code="TOOLCHAIN_UNAVAILABLE",
        )
        self.assertEqual(
            self.server._runtime_failure_details(error),
            ("runtime_preflight", "TOOLCHAIN_UNAVAILABLE"),
        )


if __name__ == "__main__":
    unittest.main()