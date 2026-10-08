"""Agent isolation with bubblewrap: the agent's program can write its task's folder and its own
home, but not the system or BABD; BABD's secrets, data and other agents' homes are hidden.

Run: python -m unittest discover -s tests   (the sandbox tests need bubblewrap)
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

import test_dashboard as td  # noqa: E402
from babd import config, permissions  # noqa: E402
from babd.harness import create_harness  # noqa: E402


def bwrap_works():
    if not shutil.which("bwrap"):
        return False
    return subprocess.run(["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid", "true"],
                          capture_output=True).returncode == 0


class SettingsTest(unittest.TestCase):
    def test_project_isolation_applies_unless_the_agent_sets_its_own(self):
        a = {"id": "dev", "llm": {"model": "m"}, "harness": {"type": "process", "command": "sh"}}
        self.assertEqual(create_harness(a, {"isolation": "bwrap"}).sandbox, "bwrap")
        self.assertEqual(create_harness({**a, "sandbox": "none"}, {"isolation": "bwrap"}).sandbox, "none")
        self.assertEqual(create_harness(a, {}).sandbox, "none")
        with self.assertRaises(permissions.PermissionsError):
            permissions.sandbox_of(a, {"isolation": "chroot"})

    def test_missing_bwrap_is_explained(self):
        permissions._bwrap_ok.clear()
        self.addCleanup(permissions._bwrap_ok.clear)
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(permissions.PermissionsError, "apt install bubblewrap"):
                permissions.bwrap_check()


@unittest.skipUnless(bwrap_works(), "needs bubblewrap with user namespaces")
class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "babd")
        for d in ("babd", "runs", "logs", ".babd/hermes/devops", ".babd/hermes/qa", "workspace/worktrees/p/t1"):
            os.makedirs(os.path.join(self.root, d))
        with open(os.path.join(self.root, ".env"), "w") as f:
            f.write("KEY1=sk-secret\n")
        with open(os.path.join(self.root, "runs", "task.txt"), "w") as f:
            f.write("task output")
        with open(os.path.join(self.root, ".babd/hermes/qa", "notes"), "w") as f:
            f.write("qa private")
        backup = os.path.join(self.tmp, "home-config", "babd", "secrets.env")
        os.makedirs(os.path.dirname(backup))
        with open(backup, "w") as f:
            f.write("KEY1=sk-secret\n")
        for p in (mock.patch.object(config, "ENV_PATH", os.path.join(self.root, ".env")),
                  mock.patch.object(config, "SECRETS_BACKUP", backup),
                  mock.patch.object(permissions, "ROOT", self.root)):
            p.start()
            self.addCleanup(p.stop)
        permissions._bwrap_ok.clear()

    def run_in_sandbox(self, script):
        wt = os.path.join(self.root, "workspace/worktrees/p/t1")
        argv = permissions.bwrap_argv(["sh", "-c", script], wt, [os.path.join(self.root, ".babd/hermes/devops")],
                                      root=self.root, hide_dirs=[os.path.join(self.root, ".babd/hermes/qa")])
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout

    def test_what_the_agent_can_and_cannot_touch(self):
        r = self.root
        out = self.run_in_sandbox(f"""
            touch code.py && echo worktree=rw
            touch {r}/.babd/hermes/devops/state && echo ownhome=rw
            touch {r}/babd/x 2>/dev/null && echo babd=RW || echo babd=ro
            touch /etc/babd-x 2>/dev/null && echo etc=RW || echo etc=ro
            echo env=[$(cat {r}/.env 2>/dev/null)]
            echo backup=[$(cat {os.path.dirname(config.SECRETS_BACKUP)}/secrets.env 2>/dev/null)]
            echo runs=[$(ls {r}/runs 2>/dev/null)]
            echo otheragent=[$(ls {r}/.babd/hermes/qa 2>/dev/null)]
            echo pids=$(ls /proc | grep -c '^[0-9]')
        """)
        for want in ("worktree=rw", "ownhome=rw", "babd=ro", "etc=ro", "env=[]", "backup=[]", "runs=[]", "otheragent=[]"):
            self.assertIn(want, out)
        self.assertLess(int(out.split("pids=")[1].split()[0]), 10)  # BABD's processes are not visible
        self.assertTrue(os.path.exists(os.path.join(r, "workspace/worktrees/p/t1/code.py")))

    def test_harness_runs_inside(self):
        wt = os.path.join(self.root, "workspace/worktrees/p/t1")
        h = create_harness({"id": "devops", "llm": {"model": "m"}, "sandbox": "bwrap",
                            "harness": {"type": "process", "command": "sh", "cwd": wt}})
        out = h.run_process(["sh", "-c", f"echo [$(cat {self.root}/.env 2>/dev/null)]; touch {self.root}/babd/y 2>/dev/null || echo ro"], {})
        self.assertEqual(out.split(), ["[]", "ro"])


class IsolationApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def test_project_setting(self):
        self.assertEqual(self.call("PUT", "/api/project", {"isolation": "chroot"})[0], 400)
        self.assertEqual(self.call("PUT", "/api/project", {"isolation": "none"})[0], 200)
        if bwrap_works():
            permissions._bwrap_ok.clear()
            self.assertEqual(self.call("PUT", "/api/project", {"isolation": "bwrap"})[0], 200)
            _, state = self.call("GET", "/api/state")
            self.assertEqual(state["project"]["isolation"], "bwrap")
            self.assertEqual(state["agents"][0]["sandbox"], "")  # the agents follow the project


if __name__ == "__main__":
    unittest.main()
