"""Projects: every task works in its own git worktree of a project outside the BABD installation; BABD
commits the work on the task's branch and merges it per the project's policy.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, projects  # noqa: E402
from babd.config import ROOT, load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class TempProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for name, sub in (("PROJECTS_DIR", "projects"), ("WORKTREES_DIR", "worktrees")):
            p = mock.patch.object(projects, name, os.path.join(self.tmp, sub))
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)


class ProjectsTest(TempProjects):
    def test_defaults_and_validation(self):
        ps = projects.projects({"projects": [{"name": "Web Shop"}]})
        self.assertEqual([p["id"] for p in ps], ["default", "web-shop"])
        self.assertEqual(ps[1]["path"], os.path.join(projects.PROJECTS_DIR, "web-shop"))
        self.assertEqual(ps[1]["merge"], "on_approval")
        with self.assertRaisesRegex(projects.ProjectError, "merge must be"):
            projects.normalize({"id": "x", "merge": "always"})
        with self.assertRaisesRegex(projects.ProjectError, "no project"):
            projects.get({"projects": []}, "missing")
        self.assertTrue(projects.inside_babd(os.path.join(ROOT, "babd")))
        self.assertFalse(projects.inside_babd(os.path.join(ROOT, "workspace", "projects", "x")))
        with self.assertRaisesRegex(projects.ProjectError, "inside the BABD installation"):
            projects.ensure(projects.normalize({"id": "bad", "path": ROOT}))

    def test_worktree_per_task_then_merge(self):
        p = projects.normalize({"id": "app"})
        a, b = projects.start(p, "run-a"), projects.start(p, "run-b")
        self.assertNotEqual(a["dir"], b["dir"])
        self.assertEqual(git(a["dir"], "rev-parse", "--abbrev-ref", "HEAD"), "babd/run-a")
        with open(os.path.join(a["dir"], "app.py"), "w") as f:
            f.write("print('hi')\n")
        out = projects.finish(p, a, "babd: add app", merge=True)
        self.assertEqual((out["files"], out["merged"]), (1, True))
        self.assertTrue(os.path.exists(os.path.join(p["path"], "app.py")))  # in the project's main checkout
        self.assertFalse(os.path.exists(a["dir"]))  # worktree removed after the merge
        out = projects.finish(p, b, "babd: nothing", merge=True)
        self.assertEqual((out["commit"], out["note"]), (None, "the agents changed no files"))

    def test_never_merge_keeps_the_branch(self):
        p = projects.normalize({"id": "app", "merge": "never"})
        ws = projects.start(p, "r1")
        with open(os.path.join(ws["dir"], "x.txt"), "w") as f:
            f.write("x")
        out = projects.finish(p, ws, "babd: x", merge=False)
        self.assertFalse(out["merged"])
        self.assertIn("kept on branch babd/r1", out["note"])
        self.assertFalse(os.path.exists(os.path.join(p["path"], "x.txt")))
        self.assertEqual(git(p["path"], "show", "babd/r1:x.txt"), "x")

    def test_merge_conflict_is_reported_not_fatal(self):
        p = projects.normalize({"id": "app"})
        a, b = projects.start(p, "a"), projects.start(p, "b")
        for ws, text in ((a, "A"), (b, "B")):
            with open(os.path.join(ws["dir"], "same.txt"), "w") as f:
                f.write(text)
        self.assertTrue(projects.finish(p, a, "a", merge=True)["merged"])
        out = projects.finish(p, b, "b", merge=True)
        self.assertFalse(out["merged"])
        self.assertIn("conflict", out["note"])
        self.assertEqual(git(p["path"], "status", "--porcelain"), "")  # merge aborted cleanly

    def test_clone_a_repository(self):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        git(src, "init", "-q", "-b", "trunk")
        git(src, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "init")
        p = projects.normalize({"id": "cloned", "repo": src})
        ws = projects.start(p, "r1")
        self.assertEqual(ws["base"], "trunk")
        self.assertTrue(os.path.isdir(os.path.join(p["path"], ".git")))

    def test_file_blocks(self):
        root = os.path.join(self.tmp, "w")
        os.makedirs(root)
        text = ("Here:\n```python file=src/app.py\nprint(1)\n```\n```js file=../escape.js\nbad\n```\n"
                "```text file=.git/config\nbad\n```\n```python\nno file\n```\n")
        self.assertEqual(projects.write_file_blocks(text, root), [os.path.join("src", "app.py")])
        with open(os.path.join(root, "src", "app.py")) as f:
            self.assertEqual(f.read(), "print(1)\n")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "escape.js")))


class RunInProjectTest(TempProjects):
    def setUp(self):
        super().setUp()
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=False, use_projects=True, require_approval=[])
        self.cfg["projects"] = [{"id": "shop", "name": "Shop"}]
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def test_agents_without_tools_get_their_files_written_and_merged(self):
        prompts = []

        def ask(agent, prompt, **kw):
            prompts.append(prompt)
            if agent.id == "developer":
                return "Done.\n```python file=shop/cart.py\ndef total(items):\n    return sum(items)\n```\n"
            return td.scripted_ask(agent, prompt, **kw)

        with mock.patch.object(Agent, "ask", ask):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Add a cart", project_id="shop").execute()
        self.assertEqual(state["status"], "done", state["error"])
        ws = state["workspace"]
        self.assertEqual((ws["project"], ws["branch"]), ("shop", f"babd/{state['id']}"))
        self.assertTrue(all("## Workspace" in p and ws["dir"] in p for p in prompts))
        self.assertEqual(ws["files_written"], [{"agent": "developer", "kind": "code", "path": "shop/cart.py"}])
        self.assertTrue(ws["result"]["merged"], ws["result"])
        project_dir = os.path.join(projects.PROJECTS_DIR, "shop")
        with open(os.path.join(project_dir, "shop", "cart.py")) as f:
            self.assertIn("sum(items)", f.read())
        self.assertIn(f"(task {state['id']})", git(project_dir, "log", "-2", "--format=%s"))

    def test_failed_qa_keeps_the_work_on_its_branch(self):
        def ask(agent, prompt, **kw):
            if agent.id == "qa":
                return "broken\nVERDICT: FAIL"
            if agent.id == "developer":
                return "```text file=notes.txt\nwip\n```"
            return td.scripted_ask(agent, prompt, **kw)

        self.cfg["project"]["max_fix_rounds"] = 0
        with mock.patch.object(Agent, "ask", ask):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Try", project_id="shop").execute()
        res = state["workspace"]["result"]
        self.assertFalse(res["merged"])
        self.assertTrue(res["commit"])
        self.assertIn("kept on branch", res["note"])

    def test_harness_cwd_is_the_worktree(self):
        seen = []
        with mock.patch.object(Agent, "ask", lambda agent, prompt, **kw: (seen.append(agent.harness.cwd),
                                                                          td.scripted_ask(agent, prompt))[1]):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "x", project_id="shop").execute()
        self.assertEqual(set(seen), {state["workspace"]["dir"]})

    def test_unknown_project(self):
        with self.assertRaisesRegex(projects.ProjectError, "no project"):
            flow.Run(Team(self.cfg, log=lambda m: None), "x", project_id="nope")


class ProjectApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def test_manage_projects(self):
        status, out = self.call("PUT", "/api/projects", {"projects": [{"name": "Web Shop", "merge": "on_pass"}],
                                                         "default_project": "web-shop"})
        self.assertEqual(status, 200, out)
        self.assertEqual([p["id"] for p in out["projects"]], ["default", "web-shop"])
        self.assertEqual(json.loads(td.read(self.cfg_path))["project"]["default_project"], "web-shop")
        for body, err in [({"projects": [{"name": "x", "path": ROOT}]}, "inside the BABD installation"),
                          ({"projects": [{"id": "a"}, {"id": "a"}]}, "two projects"),
                          ({"projects": [{"id": "Bad Id"}]}, "use lowercase"),
                          ({"default_project": "nope"}, "no project")]:
            status, out = self.call("PUT", "/api/projects", body)
            self.assertEqual(status, 400, body)
            self.assertIn(err, out["error"])
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["default_project"], "web-shop")


if __name__ == "__main__":
    unittest.main()
