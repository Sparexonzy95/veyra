from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _FakeThread:
    created = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False
        self.__class__.created.append(self)

    def start(self):
        self.started = True


class WorkspaceRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        os.environ["VEYRA_RUNTIME_STATE_DIR"] = cls.temp_dir.name
        os.environ["AI_HEALTHCHECK_MODE"] = "mock"
        source = Path(__file__).resolve().parent / "server.py"
        spec = importlib.util.spec_from_file_location("veyra_workspace_retry_server", source)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.server = module

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def setUp(self):
        self.server.JOB_RUNNING.clear()
        _FakeThread.created.clear()

    def test_fresh_lease_uses_distinct_workspace(self):
        first = self.server._job_workspace("assignment-1", "lease-1")
        second = self.server._job_workspace("assignment-1", "lease-2")
        self.assertNotEqual(first, second)
        self.assertIn("assignment-1--lease-1", first.name)
        self.assertIn("assignment-1--lease-2", second.name)

    def test_workspace_cleanup_retries_permission_error(self):
        workspace = Path(self.temp_dir.name) / "jobs" / "retry-test"
        workspace.mkdir(parents=True)
        (workspace / "locked.idx").write_text("test", encoding="utf-8")

        original_rmtree = self.server.shutil.rmtree
        calls = {"count": 0}

        def flaky_rmtree(path, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError(5, "Access is denied", str(path))
            return original_rmtree(path, *args, **kwargs)

        with patch.object(self.server.shutil, "rmtree", side_effect=flaky_rmtree):
            removed = self.server._remove_workspace(workspace, strict=True)

        self.assertTrue(removed)
        self.assertGreaterEqual(calls["count"], 2)
        self.assertFalse(workspace.exists())

    def test_new_lease_retries_same_assignment_after_failure(self):
        failed_state = self.server.default_state()
        failed_state.update(
            {
                "job_assignment_id": "assignment-1",
                "job_lease_id": "old-lease",
                "job_status": "failed",
            }
        )
        old_task = {"id": "assignment-1", "lease_id": "old-lease"}
        new_task = {"id": "assignment-1", "lease_id": "new-lease"}

        with (
            patch.object(self.server, "load_state", return_value=failed_state),
            patch.object(self.server.threading, "Thread", _FakeThread),
        ):
            self.server.ensure_job_thread(old_task)
            self.assertEqual(_FakeThread.created, [])

            self.server.ensure_job_thread(new_task)
            self.assertEqual(len(_FakeThread.created), 1)
            self.assertTrue(_FakeThread.created[0].started)
            self.assertIn("assignment-1:new-lease", self.server.JOB_RUNNING)


if __name__ == "__main__":
    unittest.main()
