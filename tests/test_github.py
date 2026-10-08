"""Pull requests: a project with "merge": "pr" gets the task's branch pushed and a PR opened; the
dashboard follows its CI checks and merges it when the CEO says so (or by itself with pr_merge auto).

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
import test_projects as tp  # noqa: E402
from babd import flow, github, projects  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402


class FakeGitHub:
    def __init__(self):
        self.calls, self.checks, self.merged = [], "pending", False
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self, method):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                fake.calls.append((method, self.path, body, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != "Bearer gh-token":
                    return self.reply(401, {"message": "Bad credentials"})
                if method == "POST" and self.path == "/repos/acme/shop/pulls":
                    return self.reply(201, {"number": 7, "html_url": "https://github.com/acme/shop/pull/7", "head": {"sha": "abc123"}})
                if self.path == "/repos/acme/shop/pulls/7":
                    return self.reply(200, {"state": "closed" if fake.merged else "open", "merged": fake.merged, "head": {"sha": "abc123"}})
                if "/check-runs" in self.path:
                    runs = [] if fake.checks == "none" else [{"status": "completed" if fake.checks != "pending" else "in_progress",
                                                              "conclusion": fake.checks}]
                    return self.reply(200, {"check_runs": runs})
                if self.path.endswith("/status"):
                    return self.reply(200, {"statuses": []})
                if method == "PUT" and self.path == "/repos/acme/shop/pulls/7/merge":
                    fake.merged = True
                    return self.reply(200, {"merged": True})
                return self.reply(404, {"message": "Not Found"})

            def do_GET(self):
                self.handle_any("GET")

            def do_POST(self):
                self.handle_any("POST")

            def do_PUT(self):
                self.handle_any("PUT")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


class RemoteTest(unittest.TestCase):
    def test_parse_remote(self):
        for url in ("https://github.com/acme/shop.git", "git@github.com:acme/shop.git", "ssh://git@github.com/acme/shop",
                    "https://x-access-token:t@github.com/acme/shop"):
            self.assertEqual(github.parse_remote(url), ("github.com", "acme", "shop"), url)
        self.assertIsNone(github.parse_remote("/srv/git/shop"))

    def test_the_token_never_reaches_a_command_line(self):
        env = github.push_env("secret-token", "github.com")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "http.https://github.com/.extraheader")
        self.assertNotIn("secret-token", env["GIT_CONFIG_VALUE_0"])  # base64 in a header, in the env only


class PullRequestFlowTest(tp.TempProjects):
    def setUp(self):
        super().setUp()
        self.gh = FakeGitHub()
        self.addCleanup(self.gh.server.shutdown)
        self.bare = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.bare], check=True)
        self.cfg = copy.deepcopy(load_config(tp.FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=False, use_projects=True, require_approval=[], github_api=self.gh.url)
        self.cfg["projects"] = [{"id": "shop", "name": "Shop", "merge": "pr", "github_repo": "acme/shop"}]
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
        env = mock.patch.dict(os.environ, {"GITHUB_TOKEN": "gh-token"})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def ask(agent, prompt, **kw):
        if agent.id == "developer":
            return "```python file=cart.py\nprint(1)\n```"
        return td.scripted_ask(agent, prompt, **kw)

    def run_task(self):
        project_dir = os.path.join(projects.PROJECTS_DIR, "shop")
        projects.ensure(projects.get(self.cfg, "shop"))
        subprocess.run(["git", "remote", "add", "origin", self.bare], cwd=project_dir, check=True)
        with mock.patch.object(Agent, "ask", self.ask):
            return flow.Run(Team(self.cfg, log=lambda m: None), "Add a cart", project_id="shop").execute()

    def test_task_opens_a_pull_request(self):
        state = self.run_task()
        self.assertEqual(state["status"], "done", state["error"])
        res = state["workspace"]["result"]
        self.assertFalse(res["merged"])
        self.assertEqual((res["pr"]["number"], res["pr"]["state"]), (7, "open"))
        self.assertIn("pull request #7", res["note"])
        branch = state["workspace"]["branch"]
        self.assertTrue(subprocess.run(["git", "rev-parse", "--verify", branch], cwd=self.bare, capture_output=True).returncode == 0)
        method, path, body, _ = self.gh.calls[0]
        self.assertEqual((method, path, body["head"], body["base"]), ("POST", "/repos/acme/shop/pulls", branch, "main"))
        self.assertIn("**QA:** PASS", body["body"])

    def test_without_a_token_the_task_says_so(self):
        os.environ.pop("GITHUB_TOKEN")
        state = self.run_task()
        self.assertIn("no pull request: no GitHub token", state["workspace"]["result"]["note"])


class PullRequestDashboardTest(unittest.TestCase):
    setUp_dash = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def setUp(self):
        self.setUp_dash()
        self.gh = FakeGitHub()
        self.addCleanup(self.gh.server.shutdown)
        self.call("PUT", "/api/project", {"github_token": "gh-token"})
        cfg = json.loads(td.read(self.cfg_path))
        cfg["project"]["github_api"] = self.gh.url
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)
        rid = "20260101-000000"
        os.makedirs(os.path.join(flow.RUNS_DIR, rid))
        state = {"id": rid, "goal": "Add a cart", "status": "done", "steps": [], "workspace": {"result": {
            "pr": {"number": 7, "url": "https://github.com/acme/shop/pull/7", "owner": "acme", "repo": "shop", "sha": "abc123",
                   "state": "open", "checks": "pending", "merged": False, "merge_requested": False}}}}
        with open(os.path.join(flow.RUNS_DIR, rid, "state.json"), "w") as f:
            json.dump(state, f)
        self.rid = rid

    def pr(self):
        return self.dash.load_run(self.rid)["workspace"]["result"]["pr"]

    def test_merge_waits_for_green_ci(self):
        _, state = self.call("GET", "/api/state")
        self.assertTrue(state["github_token_set"])
        self.assertNotIn("gh-token", json.dumps(state))
        _, out = self.call("GET", "/api/prs")
        self.assertEqual(out["prs"][0]["number"], 7)
        status, out = self.call("POST", f"/api/runs/{self.rid}/merge-pr")
        self.assertEqual(status, 200, out)
        self.assertIn("will merge when CI is green", out["note"])
        self.assertFalse(self.pr()["merged"])
        self.gh.checks = "success"
        self.dash.refresh_prs()
        self.assertTrue(self.pr()["merged"])
        self.assertTrue(any(m == "PUT" for m, *_ in self.gh.calls))
        self.assertEqual(self.call("POST", f"/api/runs/{self.rid}/merge-pr")[0], 409)

    def test_failed_ci_never_merges_and_auto_mode(self):
        self.gh.checks = "failure"
        self.call("POST", f"/api/runs/{self.rid}/merge-pr")
        self.dash.refresh_prs()
        self.assertEqual((self.pr()["checks"], self.pr()["merged"]), ("failure", False))
        self.call("PUT", "/api/project", {"pr_merge": "auto"})
        self.gh.checks = "success"
        self.dash.refresh_prs()
        self.assertTrue(self.pr()["merged"])


if __name__ == "__main__":
    unittest.main()
