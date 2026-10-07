"""Retries on temporary LLM errors and the per-agent fallback model.

Run: python -m unittest discover -s tests
"""
import copy
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, resilience  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.harness.others import Direct  # noqa: E402
from babd.llm import LLMError  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")
FAST = {"attempts": 3, "base_delay": 0, "max_delay": 0}


class ResilienceTest(unittest.TestCase):
    def test_what_counts_as_temporary(self):
        for e in ("rate limited (429)", "API error 503: overloaded", "cannot reach http://x: connection refused",
                  "Hermes Agent: timed out after 1200s", "Hermes Agent: empty response", "API error 529: Overloaded"):
            self.assertTrue(resilience.is_transient(LLMError(e)), e)
        for e in ("authentication failed - check the API key (401)", "model or endpoint not found: x",
                  "request declined by the model (cyber)", "no API key: set X"):
            self.assertFalse(resilience.is_transient(LLMError(e)), e)

    def test_retry_then_success(self):
        calls, waits, seen = [], [], []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise LLMError("rate limited")
            return "ok"
        cfg = {"attempts": 4, "base_delay": 2, "max_delay": 3}
        self.assertEqual(resilience.call(fn, cfg, seen.append, sleep=waits.append), "ok")
        self.assertEqual(waits, [2, 3])  # 2, then 4 capped at 3
        self.assertEqual([i["attempt"] for i in seen], [1, 2])

    def test_permanent_error_is_not_retried(self):
        calls = []

        def fn():
            calls.append(1)
            raise LLMError("authentication failed")
        with self.assertRaises(LLMError):
            resilience.call(fn, FAST, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_cancel_stops_the_wait(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(LLMError):
            resilience.call(lambda: (_ for _ in ()).throw(LLMError("timed out")), {"attempts": 5, "base_delay": 60,
                            "max_delay": 60}, cancelled=ev)

    def test_settings(self):
        self.assertEqual(resilience.settings({}), resilience.DEFAULTS)
        self.assertEqual(resilience.settings({"retry": {"attempts": 99}})["attempts"], 10)


class FallbackRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                                   parallel_prep=False, require_approval=[], retry=FAST)
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def fake_complete(self, broken_models, failures):
        def complete(harness, system, messages, **kw):
            model = harness.llm.get("model")
            if model in broken_models:
                failures.append((harness.agent_id, model))
                raise LLMError(broken_models[model])
            prompt = messages[-1]["content"]
            agent = type("A", (), {"id": harness.agent_id})()
            return td.scripted_ask(agent, prompt) + f"\n(by {model})"
        return complete

    def test_flaky_model_is_retried_and_the_step_records_it(self):
        state_box = {"n": 0}

        def complete(harness, system, messages, **kw):
            if harness.agent_id == "architect" and state_box["n"] < 2:
                state_box["n"] += 1
                raise LLMError("API error 503: overloaded")
            agent = type("A", (), {"id": harness.agent_id})()
            return td.scripted_ask(agent, messages[-1]["content"])
        with mock.patch.object(Direct, "complete", complete):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build login").execute()
        self.assertEqual(state["status"], "done", state["error"])
        design = [s for s in state["steps"] if s["kind"] == "design"][0]
        self.assertEqual(design["retries"], 2)
        self.assertIn("503", design["last_error"])

    def test_fallback_model_takes_over(self):
        dev = [a for a in self.cfg["agents"] if a["id"] == "developer"][0]
        broken = dev["llm"]["model"] = "dev-only-model"
        dev["llm"]["fallback"] = {"model": "backup-model"}
        failures = []
        with mock.patch.object(Direct, "complete", self.fake_complete({broken: "API error 500: down"}, failures)):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build login").execute()
        self.assertEqual(state["status"], "done", state["error"])
        code = [s for s in state["steps"] if s["kind"] == "code"][0]
        self.assertEqual((code["retries"], code["fallback"]), (2, "backup-model"))
        self.assertIn("(by backup-model)", [m for m in state["messages"] if m["kind"] == "code"][0]["content"])
        self.assertEqual(len([f for f in failures if f[0] == "developer"]), 3)

    def test_no_fallback_means_the_step_fails(self):
        dev = [a for a in self.cfg["agents"] if a["id"] == "developer"][0]
        dev["llm"]["model"] = "dev-only-model"
        with mock.patch.object(Direct, "complete", self.fake_complete({"dev-only-model": "API error 500: down"}, [])):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build login").execute()
        self.assertEqual(state["status"], "failed")
        self.assertIn("API error 500", state["error"])


class FallbackApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def test_set_fallback_and_retries(self):
        status, a = self.call("PUT", "/api/agents/qa", {"llm": {"fallback": {"model": "small", "api": "openai", "junk": "x"}}})
        self.assertEqual((status, a["llm"]["fallback"]), (200, {"model": "small", "api": "openai"}))
        self.assertEqual(self.call("PUT", "/api/agents/qa", {"llm": {"fallback": {"api": "openai"}}})[0], 400)
        status, a = self.call("PUT", "/api/agents/qa", {"llm": {"fallback": ""}})
        self.assertNotIn("fallback", a["llm"])
        p = self.call("PUT", "/api/project", {"retry": {"attempts": 50}})[1]
        self.assertEqual(p["retry"]["attempts"], 10)


if __name__ == "__main__":
    unittest.main()
