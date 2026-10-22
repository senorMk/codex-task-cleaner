import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "plugins/task-cleaner/scripts/cleaner.py"
spec = importlib.util.spec_from_file_location("cleaner", SCRIPT)
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.store = cleaner.Store(self.base / "owned")
        self.data = self.store.start("session-a", "turn-1")
        self.task = self.data["task"]
        self.work = self.store.work(self.task, self.data)
        (self.work / "scratch.txt").write_text("scratch")

    def test_active_task_is_retained(self):
        with self.assertRaises(cleaner.Refused):
            self.store.clean(self.task, apply=True)
        self.assertTrue(self.work.exists())

    @patch.object(cleaner, "open_files")
    def test_preview_does_not_remove_files(self, check):
        self.store.status(self.task, "ready")
        result = self.store.clean(self.task)
        self.assertEqual(result["bytes"], 7)
        self.assertTrue((self.work / "scratch.txt").exists())

    @patch.object(cleaner, "open_files")
    def test_stop_removes_only_ready_tasks_in_current_session(self, check):
        other = self.store.start("session-b", "turn-1")
        pending = self.store.start("session-a", "turn-2")
        self.store.status(self.task, "ready")
        self.store.status(other["task"], "ready")
        cleaner.hook(self.store, {"hook_event_name": "Stop", "session_id": "session-a"})
        self.assertFalse(self.work.exists())
        self.assertTrue(self.store.work(other["task"], other).exists())
        self.assertTrue(self.store.work(pending["task"], pending).exists())
        self.assertEqual(self.store.clean(self.task, True)["status"], "already removed")

    def test_hold_cancels_readiness(self):
        self.store.status(self.task, "ready")
        self.store.status(self.task, "held")
        with self.assertRaises(cleaner.Refused):
            self.store.clean(self.task, True)

    @patch.object(cleaner, "open_files")
    def test_internal_symlink_does_not_remove_target(self, check):
        target = self.base / "deliverable.txt"
        target.write_text("keep")
        (self.work / "link").symlink_to(target)
        self.store.status(self.task, "ready")
        self.store.clean(self.task, True)
        self.assertEqual(target.read_text(), "keep")

    def test_replaced_work_directory_is_refused(self):
        moved = self.work.with_name("original")
        self.work.rename(moved)
        self.work.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(cleaner.Refused):
            self.store.status(self.task, "ready")
        self.assertTrue((moved / "scratch.txt").exists())

    def test_root_symlink_is_refused(self):
        link = self.base / "link"
        link.symlink_to(self.store.root, target_is_directory=True)
        with self.assertRaises(cleaner.Refused):
            cleaner.Store(link)

    def test_hard_link_is_retained(self):
        target = self.base / "deliverable.txt"
        target.write_text("keep")
        os.link(target, self.work / "linked.txt")
        self.store.status(self.task, "ready")
        with self.assertRaises(cleaner.Refused):
            self.store.clean(self.task, True)
        self.assertEqual(target.read_text(), "keep")

    def test_path_traversal_is_refused(self):
        with self.assertRaises(cleaner.Refused):
            self.store.clean("../../outside", True)

    def test_missing_hook_identity_is_refused(self):
        with self.assertRaises(cleaner.Refused):
            cleaner.hook(self.store, {"hook_event_name": "UserPromptSubmit"})

    def test_prompt_replay_preserves_files(self):
        result = cleaner.hook(self.store, {"hook_event_name": "UserPromptSubmit",
                                          "session_id": "session-a", "turn_id": "turn-1"})
        self.assertIn(str(self.work), result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual((self.work / "scratch.txt").read_text(), "scratch")

    @patch.object(cleaner.subprocess, "run")
    @patch.object(cleaner.shutil, "which", return_value="/usr/sbin/lsof")
    def test_failed_open_file_check_retains_files(self, which, run):
        self.store.status(self.task, "ready")
        for result in [subprocess.CompletedProcess([], 1, "", "permission denied"),
                       subprocess.CompletedProcess([], 0, "p123", "")]:
            run.return_value = result
            with self.assertRaises(cleaner.Refused):
                self.store.clean(self.task, True)
            self.assertTrue(self.work.exists())

    def test_live_open_file_is_detected(self):
        with (self.work / "scratch.txt").open():
            with self.assertRaises(cleaner.Refused):
                cleaner.open_files(self.work)

    def test_real_cleanup_after_file_is_closed(self):
        self.store.status(self.task, "ready")
        result = self.store.clean(self.task, True)
        self.assertEqual(result["status"], "removed")
        self.assertFalse(self.work.exists())

    def test_hook_files_and_script_agree(self):
        root = SCRIPT.parents[1]
        manifest = json.loads((root / ".codex-plugin/plugin.json").read_text())
        hooks = json.loads((root / manifest["hooks"]).read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "Stop"})
        for groups in hooks.values():
            command = groups[0]["hooks"][0]["command"]
            self.assertIn("${PLUGIN_ROOT}/scripts/cleaner.py", command)


if __name__ == "__main__":
    unittest.main()
