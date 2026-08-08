from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


class FundedPathResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state_dir = tempfile.TemporaryDirectory()
        os.environ["VEYRA_RUNTIME_STATE_DIR"] = cls.state_dir.name
        os.environ["AI_HEALTHCHECK_MODE"] = "mock"
        source = Path(__file__).resolve().parent / "server.py"
        spec = importlib.util.spec_from_file_location("veyra_funded_path_server", source)
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
        for relative in (
            "app.py",
            "index.js",
            "server.js",
            "package.json",
            "src/index.js",
            "routes/tasks.js",
            "tests/test_tasks.py",
            "tests/tasks.test.js",
            "src/features/tasks/handler.ts",
            ".github/workflows/ci.yml",
            ".env",
        ):
            destination = self.workspace.joinpath(*relative.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(f"original {relative}\n", encoding="utf-8")
        self.repository_paths = self.server._repository_paths(self.workspace)

    def tearDown(self):
        self.workspace_dir.cleanup()

    def _task(self, allowed_paths: list[str], **overrides):
        policy = {
            "allowed_paths": allowed_paths,
            "forbidden_paths": [".github/**"],
            "allow_new_dependencies": False,
            "allow_database_migrations": False,
        }
        policy.update(overrides)
        return {"policy": policy}

    def _resolve(self, value: str) -> str:
        return self.server._resolve_funded_repository_path(
            value,
            self.repository_paths,
        )

    def test_root_files_resolve_without_language_or_framework_special_cases(self):
        for path in ("app.py", "index.js", "server.js", "package.json"):
            with self.subTest(path=path):
                self.assertEqual(self._resolve(path), path)

    def test_nested_javascript_files_resolve(self):
        for path in ("src/index.js", "routes/tasks.js"):
            with self.subTest(path=path):
                self.assertEqual(self._resolve(path), path)

    def test_windows_separator_is_normalized(self):
        self.assertEqual(self._resolve(r"src\index.js"), "src/index.js")

    def test_dot_slash_prefix_is_normalized(self):
        self.assertEqual(self._resolve("./src/index.js"), "src/index.js")

    def test_nested_test_files_resolve(self):
        for path in ("tests/test_tasks.py", "tests/tasks.test.js"):
            with self.subTest(path=path):
                self.assertEqual(self._resolve(path), path)

    def test_deeply_nested_file_resolves(self):
        self.assertEqual(
            self._resolve("src/features/tasks/handler.ts"),
            "src/features/tasks/handler.ts",
        )

    def test_traversal_and_absolute_paths_are_rejected(self):
        for path in ("../index.js", "src/../../index.js", "/index.js", r"C:\index.js"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    self.server.ModelOutputPolicyError,
                    "unsafe repository path",
                ):
                    self._resolve(path)

    def test_protected_file_is_rejected(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputPolicyError,
            "protected path",
        ):
            self.server._apply_model_files(
                self._task([]),
                self.workspace,
                [{"path": ".github/workflows/ci.yml", "content": "changed\n"}],
            )

    def test_existing_file_outside_funded_policy_is_rejected(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputPolicyError,
            "outside the funded policy",
        ):
            self.server._apply_model_files(
                self._task(["src/**"]),
                self.workspace,
                [{"path": "routes/tasks.js", "content": "changed\n"}],
            )

    def test_genuinely_unknown_path_is_rejected(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputPolicyError,
            "unknown funded repository path",
        ):
            self._resolve("src/missing.js")

    def test_ambiguous_case_insensitive_path_is_rejected(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputPolicyError,
            "unknown funded repository path",
        ):
            self.server._resolve_funded_repository_path(
                "src/index.js",
                ["src/Index.js", "src/INDEX.js"],
            )

    def test_protected_environment_file_is_not_added_to_model_context(self):
        context_paths = {
            item["path"] for item in self.server._repository_context(self.workspace)
        }
        self.assertNotIn(".env", context_paths)

    def test_missing_exact_allowlist_entry_does_not_become_trusted(self):
        self.assertEqual(
            self.server._trusted_model_paths(
                ["src/missing.js"],
                self.repository_paths,
            ),
            [],
        )

    def test_normalized_path_is_compared_against_normalized_policy(self):
        files = [{"path": r".\src\index.js", "content": "changed\n"}]
        self.server._apply_model_files(
            self._task(["./src/**"]),
            self.workspace,
            files,
        )
        self.assertEqual(files[0]["path"], "src/index.js")
        self.assertEqual(
            (self.workspace / "src" / "index.js").read_text(encoding="utf-8"),
            "changed\n",
        )

    def test_package_manifest_still_obeys_dependency_policy(self):
        with self.assertRaisesRegex(
            self.server.ModelOutputPolicyError,
            "Dependency changes are disabled",
        ):
            self.server._apply_model_files(
                self._task(["package.json"]),
                self.workspace,
                [{"path": "package.json", "content": "{}\n"}],
            )

        self.server._apply_model_files(
            self._task(["package.json"], allow_new_dependencies=True),
            self.workspace,
            [{"path": "package.json", "content": "{}\n"}],
        )
        self.assertEqual(
            (self.workspace / "package.json").read_text(encoding="utf-8"),
            "{}\n",
        )


if __name__ == "__main__":
    unittest.main()