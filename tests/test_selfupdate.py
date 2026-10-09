"""BABD updating itself: `babd/selfupdate.py` pulls upstream into an installation, tests it, and
keeps a rollback; the `babd-self` project lets the agents edit BABD's own code in an isolated
worktree that only reaches the installation through the CEO approval + merge gate.

Run: python -m unittest discover -s tests
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from babd import selfupdate as su  # noqa: E402


def sh(cwd, *args, check=True):
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError(f"{args} failed: {p.stderr or p.stdout}")
    return (p.stdout or "").strip()


def git(cwd, *args):
    return sh(cwd, "git", *args)


def make_upstream(path):
    """A tiny repo that already looks like a BABD install (has babd/)."""
    os.makedirs(os.path.join(path, "babd"), exist_ok=True)
    with open(os.path.join(path, "babd", "__init__.py"), "w") as f:
        f.write("")
    with open(os.path.join(path, "file.txt"), "w") as f:
        f.write("first\n")
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "first")
    return path


class InstallationMixin(unittest.TestCase):
    """`upstream` is what origin points at; `install` is the clone BABD runs from (origin -> upstream)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.upstream = make_upstream(os.path.join(self.tmp, "upstream"))
        self.install = os.path.join(self.tmp, "install")
        sh(self.tmp, "git", "clone", "-q", "--no-local", self.upstream, self.install)
        git(self.install, "config", "user.email", "t@t")
        git(self.install, "config", "user.name", "t")
        self._patches = []
        for name, value in (("ROOT", self.install),
                            ("MARKER_DIR", os.path.join(self.install, ".babd", "selfupdate")),
                            ("BACKUP_DIR", os.path.join(self.install, ".babd", "selfupdate", "backups"))):
            p = mock.patch.object(su, name, value)
            p.start()
            self._patches.append(p)
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def upstream_commit(self, message):
        with open(os.path.join(self.upstream, "file.txt"), "a") as f:
            f.write(message + "\n")
        git(self.upstream, "add", "-A")
        git(self.upstream, "commit", "-qm", message)
        return git(self.upstream, "rev-parse", "HEAD")


class DetectTest(InstallationMixin):
    def test_is_installation(self):
        self.assertTrue(su.is_installation(self.install))
        self.assertFalse(su.is_installation(self.tmp))

    def test_behind_after_upstream_commit(self):
        self.assertEqual(su.behind_ahead("origin"), (0, 0))
        self.upstream_commit("second")
        su.fetch("origin")
        behind, ahead = su.behind_ahead("origin")
        self.assertEqual(behind, 1)
        self.assertEqual(ahead, 0)

    def test_dirty_paths(self):
        with open(os.path.join(self.install, "file.txt"), "a") as f:
            f.write("edit\n")
        self.assertIn("file.txt", su.dirty_paths())


class UpdateTest(InstallationMixin):
    def test_up_to_date_is_a_noop(self):
        report = su.update(do_test=False)
        self.assertTrue(report["ok"])
        self.assertFalse(report["updated"])
        self.assertEqual(report["before"], report["after"])

    def test_update_pulls_new_commit(self):
        new = self.upstream_commit("second")
        report = su.update(do_test=False)
        self.assertTrue(report["ok"])
        self.assertTrue(report["updated"])
        self.assertEqual(su.current_commit(), new)

    def test_update_keeps_local_edits(self):
        # a local edit to a file upstream does not touch
        with open(os.path.join(self.install, "local-only.txt"), "w") as f:
            f.write("mine\n")
        new = self.upstream_commit("second")
        report = su.update(do_test=False)
        self.assertTrue(report["ok"])
        self.assertEqual(su.current_commit(), new)
        self.assertTrue(os.path.isfile(os.path.join(self.install, "local-only.txt")))

    def test_failing_tests_roll_back(self):
        before = su.current_commit()
        self.upstream_commit("second")
        with mock.patch.object(su, "test_command", lambda: "exit 1"):
            report = su.update(do_test=True)
        self.assertFalse(report["ok"])
        self.assertIn("rolled back", report.get("error", ""))
        self.assertEqual(su.current_commit(), before)

    def test_passing_tests_keep_the_update(self):
        new = self.upstream_commit("second")
        with mock.patch.object(su, "test_command", lambda: "true"):
            report = su.update(do_test=True)
        self.assertTrue(report["ok"])
        self.assertEqual(su.current_commit(), new)


class RollbackTest(InstallationMixin):
    def test_rollback_without_marker_errors(self):
        with self.assertRaises(su.SelfUpdateError):
            su.rollback()

    def test_rollback_restores_previous_commit(self):
        before = su.current_commit()
        self.upstream_commit("second")
        su.update(do_test=False)
        self.assertNotEqual(su.current_commit(), before)
        result = su.rollback()
        self.assertTrue(result["ok"])
        self.assertEqual(su.current_commit(), before)


class BackupTest(InstallationMixin):
    def test_backup_copies_code_and_prunes(self):
        dest = su._backup_installation(max_keep=1)
        self.assertTrue(os.path.isdir(dest))
        self.assertTrue(os.path.isdir(os.path.join(dest, "babd")))
        dest2 = su._backup_installation(max_keep=1)
        self.assertNotEqual(dest, dest2)
        self.assertFalse(os.path.isdir(dest))
        self.assertTrue(os.path.isdir(dest2))


if __name__ == "__main__":
    unittest.main()
