"""End-to-end tests: real HTTP calls through the Anthropic and OpenAI SDKs to a local mock LLM server.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")  # not the live agents.json
from babd.llm import LLMClient, LLMError  # noqa: E402
from babd.team import Team, apply_report_to_dashboard  # noqa: E402

PLAN = {"plan_summary": "Build login.", "assignments": {
    "architect": "Design auth", "developer": "Write auth code", "qa": "Test auth", "devops": "Ship auth"}}
REPORT = {"status": "active", "progress": "85", "current_goal": "Ship Login", "active_task": "Deploy",
          "approval_needed": 1, "blockers": 0, "recent_result": "Tests Passed", "next_action": "Approve Deploy",
          "summary": "Login is built and tested."}


def reply_for(system, prompt):
    if '"assignments"' in prompt:
        return "Here is the plan:\n```json\n" + json.dumps(PLAN) + "\n```"
    if '"next_action"' in prompt:
        return json.dumps(REPORT)
    if "Reply with exactly: OK" in prompt:
        return "OK"
    if "VERDICT: PASS or VERDICT: FAIL" in prompt:
        return "all tests pass\nVERDICT: PASS"
    return f"done by [{system.splitlines()[0][:40]}]"


class MockLLM(BaseHTTPRequestHandler):
    requests = []
    fail_auth = False

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        MockLLM.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if MockLLM.fail_auth:
            return self._send(401, {"type": "error", "error": {"type": "authentication_error",
                                                               "message": "invalid x-api-key"}})
        last = body["messages"][-1]["content"]
        if self.path == "/v1/messages":
            text = reply_for(body.get("system", ""), last)
            return self._send(200, {
                "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
        if self.path == "/v1/chat/completions":
            system = body["messages"][0]["content"]
            text = reply_for(system, last)
            return self._send(200, {
                "id": "c1", "object": "chat.completion", "created": 0, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        self._send(404, {"error": "not found"})


class TeamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), MockLLM)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockLLM.requests = []
        MockLLM.fail_auth = False
        self.tmp = tempfile.mkdtemp()
        os.environ["TEST_ANTHROPIC_KEY"] = "sk-ant-test"
        cfg = copy.deepcopy(load_config(FIXTURE))
        cfg["project"]["gbrain"] = {"enabled": False}  # memory is covered in test_gbrain.py
        cfg["project"]["parallel_prep"] = False  # the parallel flow is covered in test_parallel.py
        cfg["project"]["superpowers"] = {"enabled": False}  # covered in test_superpowers.py
        cfg["project"]["mattpocock"] = {"enabled": False}  # covered in test_mattpocock.py
        # Point every agent at the mock: Anthropic agents keep the Anthropic API style,
        # custom ones keep the OpenAI-compatible style.
        for a in cfg["agents"]:
            a["harness"] = {"type": "direct"}  # these tests cover the direct API path
            llm = a["llm"]
            if llm["api"] == "anthropic":
                llm.update(base_url=self.url + "/v1", api_key_env="TEST_ANTHROPIC_KEY")
            else:
                llm.update(base_url=self.url + "/v1", api_key="local-key")
        self.cfg = cfg

    def test_anthropic_request_shape(self):
        lead = self.cfg["agents"][0]["llm"]
        reply = LLMClient(lead).complete("sys", [{"role": "user", "content": "hi"}])
        self.assertTrue(reply.startswith("done by"))
        req = MockLLM.requests[-1]
        self.assertEqual(req["path"], "/v1/messages")  # trailing /v1 in base_url is not doubled
        self.assertEqual(req["headers"]["x-api-key"], "sk-ant-test")
        self.assertEqual(req["body"]["model"], lead["model"])
        self.assertEqual(req["body"]["output_config"], {"effort": lead["effort"]})
        self.assertNotIn("fallbacks", req["body"])  # only sent to api.anthropic.com

    def test_fallback_only_on_claude_api(self):
        cfg = {"api": "anthropic", "model": "claude-opus-5-5", "base_url": "https://api.anthropic.com",
               "api_key": "x"}
        self.assertTrue(LLMClient(cfg).use_fallback)
        self.assertFalse(LLMClient(dict(cfg, model="claude-haiku-4-5")).use_fallback)
        self.assertFalse(LLMClient(dict(cfg, refusal_fallback=False)).use_fallback)

    def test_openai_compatible_request_shape(self):
        devops = self.cfg["agents"][-1]["llm"]
        self.assertEqual(devops["api"], "openai")
        reply = LLMClient(devops).complete("sys", [{"role": "user", "content": "hi"}])
        self.assertTrue(reply.startswith("done by"))
        req = MockLLM.requests[-1]
        self.assertEqual(req["path"], "/v1/chat/completions")
        self.assertEqual(req["headers"]["authorization"], "Bearer local-key")
        self.assertEqual(req["body"]["messages"][0], {"role": "system", "content": "sys"})

    def test_auth_error_is_reported(self):
        MockLLM.fail_auth = True
        with self.assertRaises(LLMError) as ctx:
            LLMClient(dict(self.cfg["agents"][0]["llm"])).complete("s", [{"role": "user", "content": "x"}])
        self.assertIn("authentication failed", str(ctx.exception))

    def test_missing_key_message(self):
        os.environ.pop("NO_SUCH_KEY_ENV", None)
        llm = {"api": "anthropic", "model": "claude-opus-5-5", "base_url": self.url, "api_key_env": "NO_SUCH_KEY_ENV"}
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
                os.environ.pop(k, None)
            with self.assertRaises(LLMError) as ctx:
                LLMClient(llm).complete("s", [{"role": "user", "content": "x"}])
        self.assertIn("NO_SUCH_KEY_ENV", str(ctx.exception))

    def test_check(self):
        results = Team(self.cfg, log=lambda m: None).check()
        self.assertEqual({k: ok for k, (ok, _) in results.items()}, {a["id"]: True for a in self.cfg["agents"]})

    def test_skills_in_system_prompt(self):
        dev = Team(self.cfg, log=lambda m: None).by_id["developer"]
        prompt = dev.system_prompt()
        self.assertIn("Build Software", prompt)
        for s in dev.cfg["skills"]:
            self.assertIn(s, prompt)
        self.assertIn("## Skill: Python", prompt)  # skills/python.md is loaded

    def test_full_run(self):
        with mock.patch.object(flow, "RUNS_DIR", self.tmp):
            state = Team(self.cfg, log=lambda m: None).run("Build a login page", approver=lambda r: (True, ""))
        self.assertEqual(state["status"], "done")
        replies = {m["from"]: m["content"] for m in state["messages"] if m["to"] == "lead"}
        self.assertEqual(set(replies) - {"ceo"}, {"architect", "developer", "qa", "devops"})
        self.assertEqual(state["report"]["next_action"], "Approve Deploy")
        # plan, 4 specialists, report: real HTTP calls through both SDKs
        self.assertEqual(len(MockLLM.requests), 6)
        dev_prompt = MockLLM.requests[2]["body"]["messages"][-1]["content"]
        self.assertIn("Write auth code", dev_prompt)
        self.assertIn("Design from Architect", dev_prompt)
        self.assertEqual(MockLLM.requests[4]["path"], "/v1/chat/completions")  # DevOps: custom endpoint
        files = sorted(os.listdir(state["dir"]))
        # flow.py writes both: 01-plan.md (readable doc for the CEO download) and
        # 01-plan.json (raw plan JSON the orchestrator parses).
        self.assertIn("01-plan.md", files)
        self.assertIn("01-plan.json", files)
        self.assertIn("99-ceo-report.json", files)
        # The readable markdown doc must be the rendered plan, not the raw JSON blob.
        plan_md = (Path(state["dir"]) / "01-plan.md").read_text(encoding="utf-8")
        self.assertNotIn("assignments", plan_md)
        self.assertTrue(plan_md.strip())

    def test_apply_report_to_dashboard(self):
        cfg = apply_report_to_dashboard(copy.deepcopy(self.cfg), REPORT)
        p = cfg["project"]
        self.assertEqual((p["status"], p["progress"], p["approval_needed"], p["next_action"]),
                         ("ACTIVE", 85, 1, "Approve Deploy"))


class PlanMarkdownTest(unittest.TestCase):
    """flow.plan_markdown renders the CEO-readable 01-plan.md document."""

    def test_renders_summary_assignments_and_packages(self):
        plan = {
            "plan_size": "medium",
            "plan_summary": "Ship a login page.",
            "assignments": {"architect": "Design it", "developer": "Build it"},
            "work_packages": [
                {"title": "Design", "agent": "architect", "task": "Draw the spec"},
                {"title": "Build", "agent": "developer", "depends_on": ["Design"], "task": "Write code"},
            ],
        }
        md = flow.plan_markdown("Build a login page", plan, json.dumps(plan))
        self.assertIn("# Rencana: Build a login page", md)
        self.assertIn("## Ringkasan", md)
        self.assertIn("Ship a login page.", md)
        self.assertIn("**Ukuran tugas:** medium", md)
        self.assertIn("## Pembagian tugas", md)
        self.assertIn("| architect | Design it |", md)
        self.assertIn("## Paket kerja", md)
        self.assertIn("Build", md)
        # The rendered doc must not leak the raw JSON structure.
        self.assertNotIn('"plan_summary"', md)
        self.assertNotIn('"assignments"', md)

    def test_falls_back_to_raw_text_when_plan_unparsed(self):
        md = flow.plan_markdown("Some goal", {}, "raw lead output")
        self.assertIn("# Rencana: Some goal", md)
        self.assertIn("raw lead output", md)

    def test_escapes_pipes_in_table_cells(self):
        plan = {"assignments": {"developer": "do a | b"}, "plan_summary": ""}
        md = flow.plan_markdown("g", plan, "")
        self.assertIn("do a \\| b", md)
        # A raw unescaped pipe inside a cell would break the table row count.
        row = [ln for ln in md.splitlines() if ln.startswith("| developer")][0]
        self.assertNotIn("| do a | b |", row)


if __name__ == "__main__":
    unittest.main()
