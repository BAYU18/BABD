"""Dashboard API tests over real HTTP: security, config edits, API keys, chat jobs and a full team
run with CEO approval through the API.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import config, flow  # noqa: E402
from babd.config import ROOT, load_config  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")  # not the live agents.json
from babd.dashboard.server import Dashboard, make_handler  # noqa: E402
from babd.team import Agent  # noqa: E402

TOKEN = "test-token-123"


def read(path):
    with open(path) as f:
        return f.read()


def scripted_ask(self, prompt, **kw):
    if self.id == "lead":
        if '"assignments"' in prompt:
            return json.dumps({"plan_summary": "p", "assignments": {}})
        return json.dumps({"next_action": "Monitor", "recent_result": "Shipped", "summary": "done"})
    if self.id == "qa":
        return "ok\nVERDICT: PASS"
    time.sleep(0.05)
    return f"{self.id} output"


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg_path = os.path.join(self.tmp, "agents.json")
        cfg = copy.deepcopy(load_config(FIXTURE))
        cfg["project"]["gbrain"] = {"enabled": False}  # memory is covered in test_gbrain.py
        cfg["project"]["parallel_prep"] = False  # the parallel flow is covered in test_parallel.py
        cfg["project"]["superpowers"] = {"enabled": False}  # covered in test_superpowers.py
        cfg["project"]["mattpocock"] = {"enabled": False}  # covered in test_mattpocock.py
        for a in cfg["agents"]:
            a["harness"] = {"type": "direct"}
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)
        for p in (mock.patch.object(config, "ENV_PATH", os.path.join(self.tmp, ".env")),
                  mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs")),
                  mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-env"})):
            p.start()
            self.addCleanup(p.stop)
        self.dash = Dashboard(self.cfg_path, regenerate_image=False)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = self.server.server_port
        self.server.RequestHandlerClass = make_handler(self.dash, TOKEN, {f"127.0.0.1:{port}"})
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method, path, body=None, token=TOKEN, host=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        if token:
            req.add_header("X-BABD-Token", token)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                return r.status, json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def waiting(self, run_id):
        ctx = self.dash.active.get(run_id)
        return bool(ctx and ctx["approval"])

    def wait(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            v = cond()
            if v:
                return v
            time.sleep(0.05)
        self.fail("timed out waiting")

    def test_page_and_auth(self):
        status, html = self.call("GET", "/", token=None)
        self.assertEqual(status, 200)
        self.assertIn(b"BABD Command Center", html)
        self.assertEqual(self.call("GET", "/api/state", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/state", token="wrong")[0], 401)
        self.assertEqual(self.call("GET", "/api/state", host="evil.example:80")[0], 401)  # DNS rebinding
        status, state = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(state["agents"]), 5)
        self.assertIn("hermes_local", state["harnesses"])
        self.assertEqual([s["key"] for s in state["flow"]["stages"]][0], "plan")

    def test_keys_never_leave_the_server(self):
        cfg = load_config(self.cfg_path)
        cfg["agents"][4]["llm"]["api_key"] = "sk-inline-secret"
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)
        status, raw = self.call("GET", "/api/state")
        self.assertNotIn("sk-inline-secret", json.dumps(raw))
        self.assertNotIn("sk-env", json.dumps(raw))
        devops = [a for a in raw["agents"] if a["id"] == "devops"][0]
        self.assertTrue(devops["llm"]["api_key_set"])
        self.assertTrue(devops["llm"]["api_key_inline"])

    def test_update_llm_and_key_goes_to_env(self):
        status, a = self.call("PUT", "/api/agents/devops", {
            "llm": {"model": "llama3.3:70b", "base_url": "http://gpu-box:8000/v1", "api_key_env": "DEVOPS_KEY"},
            "api_key": "sk-new-secret"})
        self.assertEqual(status, 200, a)
        self.assertEqual(a["llm"]["model"], "llama3.3:70b")
        saved = [x for x in load_config(self.cfg_path)["agents"] if x["id"] == "devops"][0]
        self.assertEqual(saved["llm"]["api_key_env"], "DEVOPS_KEY")
        self.assertNotIn("api_key", saved["llm"])
        self.assertNotIn("sk-new-secret", read(self.cfg_path))
        env_file = os.path.join(self.tmp, ".env")
        self.assertIn("DEVOPS_KEY=sk-new-secret", read(env_file))
        self.assertEqual(oct(os.stat(env_file).st_mode & 0o777), "0o600")
        self.assertEqual(os.environ["DEVOPS_KEY"], "sk-new-secret")

    def test_key_variable_cannot_be_a_system_variable(self):
        status, err = self.call("PUT", "/api/agents/devops", {"llm": {"api_key_env": "PATH"}, "api_key": "x"})
        self.assertEqual(status, 400)
        self.assertIn("system variable", err["error"])
        self.assertNotEqual(os.environ.get("PATH"), "x")

    def test_switch_harness_and_options(self):
        status, a = self.call("PUT", "/api/agents/qa", {"harness": {"type": "hermes_local"}})
        self.assertEqual(status, 200, a)
        self.assertEqual(a["harness"]["toolsets"], ["terminal", "file"])  # defaults when switching
        status, a = self.call("PUT", "/api/agents/qa", {"harness": {"type": "hermes_local", "toolsets": ["web"],
                                                                    "max_turns": 9, "yolo": False}})
        self.assertEqual(a["harness"], {"type": "hermes_local", "toolsets": ["web"], "max_turns": 9, "yolo": False})
        self.assertEqual(self.call("PUT", "/api/agents/qa", {"harness": {"type": "nope", "x": 1}})[0], 400)
        self.assertEqual(self.call("PUT", "/api/agents/ghost", {})[0], 404)

    def test_role_skills_project(self):
        status, a = self.call("PUT", "/api/agents/developer", {"skills": ["Go", "Rust"], "main_task": ["SHIP", "CODE"]})
        self.assertEqual((a["skills"], a["main_task"]), (["Go", "Rust"], ["SHIP", "CODE"]))
        status, p = self.call("PUT", "/api/project", {"name": "Shop", "require_approval": False, "max_fix_rounds": 9})
        self.assertEqual((p["name"], p["require_approval"], p["max_fix_rounds"]), ("Shop", [], 5))

    def test_skill_packs_and_recommendations(self):
        state = self.call("GET", "/api/state")[1]
        self.assertEqual([p["key"] for p in state["skillpacks"]], ["superpowers", "mattpocock"])
        mp = state["skillpacks"][1]
        self.assertEqual(len(mp["catalog"]), 38)
        tdd = [c for c in mp["catalog"] if c["name"] == "tdd"][0]
        self.assertTrue(tdd["plain"] and tdd["steps"])
        self.assertIn("tdd", mp["recommended"]["developer"])
        self.assertIn("Docker", state["general_skills"]["devops"])
        dev = [a for a in state["agents"] if a["id"] == "developer"][0]
        self.assertEqual(dev["skill_status"]["have"], dev["skill_status"]["recommended"])
        self.assertEqual(self.call("PUT", "/api/agents/developer", {"mattpocock": ["tdd", "nope"]})[0], 400)
        self.assertEqual(self.call("PUT", "/api/agents/developer", {"mattpocock": "tdd"})[0], 400)
        status, dev = self.call("PUT", "/api/agents/developer", {"mattpocock": ["tdd", "teach"]})
        self.assertEqual(status, 200)
        self.assertEqual(dev["mattpocock"], ["tdd", "teach"])
        self.assertIn("diagnosing-bugs", dev["skill_status"]["packs"]["mattpocock"]["missing"])
        self.assertEqual(dev["skill_status"]["packs"]["mattpocock"]["extra"], ["teach"])
        self.assertEqual(json.loads(read(self.cfg_path))["agents"][2]["mattpocock"], ["tdd", "teach"])
        p = self.call("PUT", "/api/project", {"mattpocock": {"enabled": True, "enforce": False}})[1]
        self.assertEqual(p["mattpocock"], {"enabled": True, "enforce": False})

    def test_chat_job(self):
        with mock.patch.object(Agent, "chat", lambda self, m, **kw: (self.history.append({"role": "user", "content": m}),
                                                               "hi from " + self.id)[1]):
            status, job = self.call("POST", "/api/agents/architect/chat", {"message": "hello"})
            self.assertEqual(status, 200)
            done = self.wait(lambda: self.dash.jobs[job["id"]]["status"] != "running" and self.dash.jobs[job["id"]])
        self.assertEqual(done["result"]["reply"], "hi from architect")
        self.assertEqual(self.call("POST", "/api/agents/architect/chat", {"message": " "})[0], 400)

    def test_team_run_with_approval(self):
        with mock.patch.object(Agent, "ask", scripted_ask):
            status, run = self.call("POST", "/api/runs", {"goal": "Build login"})
            self.assertEqual(status, 200, run)
            run_id = run["id"]
            self.wait(lambda: self.waiting(run_id))
            _, state = self.call("GET", "/api/state")
            self.assertEqual(state["run"]["status"], "waiting_approval")
            self.assertEqual(state["run"]["agents"]["devops"]["status"], "waiting")
            status, _ = self.call("POST", f"/api/runs/{run_id}/approve", {"approved": True, "note": "ship it"})
            self.assertEqual(status, 200)
            self.wait(lambda: run_id not in self.dash.active)
        _, r = self.call("GET", f"/api/runs/{run_id}")
        self.assertEqual(r["status"], "done")
        self.assertTrue(r["deployed"])
        kinds = [m["kind"] for m in r["messages"]]
        self.assertEqual(kinds[-5:], ["approval_request", "approval", "assign", "deploy_report", "report"])
        project = load_config(self.cfg_path)["project"]  # dashboard fields updated after the run
        self.assertEqual((project["status"], project["next_action"]), ("DONE", "Monitor"))
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["runs"][0]["id"], run_id)

    def test_cancel_while_waiting(self):
        with mock.patch.object(Agent, "ask", scripted_ask):
            _, run = self.call("POST", "/api/runs", {"goal": "Build login"})
            self.wait(lambda: self.waiting(run["id"]))
            self.assertEqual(self.call("POST", f"/api/runs/{run['id']}/cancel")[0], 200)
            self.wait(lambda: run["id"] not in self.dash.active)
        self.assertEqual(self.dash.last_run.state["status"], "cancelled")
        self.assertFalse(self.dash.last_run.state["deployed"])

    def test_event_stream(self):
        req = urllib.request.Request(self.base + f"/api/events?token={TOKEN}")
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.headers["Content-Type"], "text/event-stream")
            self.assertEqual(r.readline(), b"retry: 2000\n")
            r.readline()
            self.dash.hub.publish("log", {"msg": "hello"})
            self.assertEqual(r.readline(), b"event: log\n")
            self.assertIn(b"hello", r.readline())


if __name__ == "__main__":
    unittest.main()
