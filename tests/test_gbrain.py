"""GBrain memory tests: every agent step READS gbrain first and WRITES to it after.

A fake `gbrain` CLI (same commands and JSON shapes as the real one: init, apply-migrations, recall,
remember, put, search) keeps memory in a JSON file and logs every call, together with the agents'
work, into one ordered log.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.gbrain import GBrain, keywords  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FAKE_GBRAIN = r'''#!/usr/bin/env python3
import json, os, sys
home = os.environ["GBRAIN_HOME"]
store_path = os.path.join(home, "fake-store.json")
store = json.load(open(store_path)) if os.path.exists(store_path) else {"facts": [], "pages": {}}
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"who": "gbrain", "cmd": args[0], "args": args[1:],
                        "cloud_key": "ANTHROPIC_API_KEY" in os.environ}) + "\n")
if os.environ.get("FAKE_GBRAIN_FAIL") == args[0]:
    print("database is locked", file=sys.stderr); sys.exit(1)
def save():
    json.dump(store, open(store_path, "w"))
def opt(name):
    return args[args.index(name) + 1] if name in args else None
cmd = args[0]
if cmd == "--version":
    print("gbrain 0.0.0-fake")
elif cmd == "init":
    os.makedirs(os.path.join(home, ".gbrain", "brain.pglite"), exist_ok=True); print(json.dumps({"status": "success"}))
elif cmd == "apply-migrations":
    print("ok")
elif cmd == "remember":
    store["facts"].append({"id": len(store["facts"]) + 1, "fact": args[1], "entity_slug": opt("--entity"),
                           "provenance": opt("--provenance")}); save()
    print(json.dumps({"id": str(len(store["facts"])), "status": "inserted"}))
elif cmd == "put":
    store["pages"][args[1]] = sys.stdin.read(); save()
    print(json.dumps({"slug": args[1], "status": "created_or_updated"}))
elif cmd == "recall":
    words = [w for w in opt("--query").split(" or ") if w]
    results = [{"slug": s, "chunk": body[-200:]} for s, body in store["pages"].items()
               if any(w in body.lower() for w in words)]
    facts = [f for f in store["facts"] if any(w in f["fact"].lower() for w in words)]
    print(json.dumps({"facts": facts, "results": results, "budget_tokens": int(opt("--budget-tokens"))}))
elif cmd == "search":
    print(json.dumps([{"slug": s} for s, b in store["pages"].items() if args[1].lower() in b.lower()]))
'''


def scripted(log_path):
    def ask(self, prompt, **kw):
        with open(log_path, "a") as f:
            f.write(json.dumps({"who": self.id, "cmd": "ask", "memory": "## Team memory (gbrain)" in prompt,
                                "prompt": prompt}) + "\n")
        if self.id == "lead":
            if '"assignments"' in prompt:
                return json.dumps({"plan_summary": "Use JWT sessions.", "assignments": {}})
            return json.dumps({"summary": "Shipped login.", "next_action": "Monitor"})
        if self.id == "qa":
            return "All good\nVERDICT: PASS"
        return f"{self.id} output about jwt sessions"
    return ask


class GBrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        self.fake = os.path.join(bin_dir, "gbrain")
        with open(self.fake, "w") as f:
            f.write(FAKE_GBRAIN)
        os.chmod(self.fake, os.stat(self.fake).st_mode | stat.S_IEXEC)
        self.log = os.path.join(self.tmp, "log.jsonl")
        for p in (mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs")),
                  mock.patch.dict(os.environ, {"FAKE_LOG": self.log, "ANTHROPIC_API_KEY": "sk-agent"}),
                  mock.patch.object(Agent, "ask", scripted(self.log))):
            p.start()
            self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config())
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
        self.cfg["project"]["gbrain"] = {"command": self.fake, "home": os.path.join(self.tmp, "brain")}
        self.brain = GBrain(self.cfg["project"])
        self.brain.setup()
        open(self.log, "w").close()

    def entries(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def run_team(self, goal="Build login with JWT sessions"):
        return Team(self.cfg, log=lambda m: None).run(goal, approver=lambda r: (True, "ok"))

    def test_every_step_reads_first_and_writes_after(self):
        state = self.run_team()
        self.assertEqual(state["status"], "done", state["error"])
        log = self.entries()
        steps = [i for i, e in enumerate(log) if e["cmd"] == "ask"]
        self.assertEqual([log[i]["who"] for i in steps], ["lead", "architect", "developer", "qa", "devops", "lead"])
        for i in steps:
            self.assertEqual(log[i - 1]["cmd"], "recall", f"step {log[i]['who']} did not read gbrain first")
            self.assertTrue(log[i]["memory"], "memory was not put in the prompt")
            self.assertEqual([log[i + 1]["cmd"], log[i + 2]["cmd"]], ["put", "remember"],
                             f"step {log[i]['who']} did not write to gbrain after")

    def test_pages_facts_and_provenance(self):
        state = self.run_team()
        with open(os.path.join(self.tmp, "brain", "fake-store.json")) as f:
            store = json.load(f)
        slugs = sorted(store["pages"])
        self.assertEqual([s.split("/")[-1] for s in slugs],
                         ["01-lead-plan", "02-architect-design", "03-developer-code", "04-qa-test_report",
                          "05-devops-deploy_report", "06-lead-report"])
        self.assertTrue(all(s.startswith(f"babd/runs/{state['id']}/") for s in slugs))
        self.assertIn("architect output", store["pages"][slugs[1]])
        self.assertTrue(store["pages"][slugs[1]].startswith("---\ntitle:"))
        facts = store["facts"]
        self.assertEqual(len(facts), 6)
        self.assertTrue(all(f["entity_slug"] == "babd/goals/build-login-with-jwt-sessions" for f in facts))
        self.assertIn("Team Lead plan", facts[0]["fact"])
        self.assertIn("QA verdict PASS", facts[3]["fact"])
        self.assertIn("CEO report", facts[5]["fact"])
        self.assertEqual(facts[1]["provenance"], f"babd run {state['id']} · Architect · design")

    def test_next_run_reads_what_the_last_run_wrote(self):
        self.run_team()
        open(self.log, "w").close()
        self.run_team("Add JWT refresh tokens")
        first_ask = next(e for e in self.entries() if e["cmd"] == "ask")
        self.assertIn("Team Lead plan for 'Build login with JWT sessions'", first_ask["prompt"])
        self.assertIn("page babd/runs/", first_ask["prompt"])

    def test_memory_events_in_run_state(self):
        state = self.run_team()
        ops = [(m["agent"], m["op"]) for m in state["memory"]]
        self.assertEqual(ops[:4], [("lead", "read"), ("lead", "write"), ("architect", "read"), ("architect", "write")])
        self.assertEqual(len(ops), 12)
        self.assertTrue(all("after_seq" in m for m in state["memory"]))

    def test_strict_failure_stops_the_run(self):
        with mock.patch.dict(os.environ, {"FAKE_GBRAIN_FAIL": "recall"}):
            state = self.run_team()
        self.assertEqual(state["status"], "failed")
        self.assertIn("gbrain read failed", state["error"])
        self.assertIn("database is locked", state["error"])

    def test_non_strict_continues_without_memory(self):
        self.cfg["project"]["gbrain"]["strict"] = False
        with mock.patch.dict(os.environ, {"FAKE_GBRAIN_FAIL": "remember"}):
            state = self.run_team()
        self.assertEqual(state["status"], "done")
        self.assertEqual({m["op"] for m in state["memory"]}, {"read"})

    def test_cloud_keys_stay_away_from_gbrain(self):
        self.run_team()
        self.assertFalse(any(e["cloud_key"] for e in self.entries() if e["who"] == "gbrain"))
        self.cfg["project"]["gbrain"]["allow_cloud"] = True
        open(self.log, "w").close()
        self.run_team()
        self.assertTrue(all(e["cloud_key"] for e in self.entries() if e["who"] == "gbrain"))

    def test_disabled(self):
        self.cfg["project"]["gbrain"]["enabled"] = False
        self.run_team()
        self.assertFalse(any(e["who"] == "gbrain" for e in self.entries()))

    def test_chat_reads_and_writes(self):
        agent = Agent(self.cfg["agents"][2], self.brain)
        with mock.patch.object(agent.harness, "complete", return_value="Use argon2.") as complete:
            agent.chat("Which password hash?")
        self.assertIn("## Team memory (gbrain)", complete.call_args[0][1][-1]["content"])
        self.assertEqual(agent.history[-2], {"role": "user", "content": "Which password hash?"})
        cmds = [e["cmd"] for e in self.entries()]
        self.assertEqual(cmds, ["recall", "remember"])

    def test_harness_agents_get_the_gbrain_command(self):
        cfg = copy.deepcopy(self.cfg["agents"][1])
        cfg["harness"] = {"type": "process", "command": "true"}
        agent = Agent(cfg, self.brain)
        env = agent.harness.child_env({})
        self.assertEqual(env["GBRAIN_HOME"], self.brain.home)
        self.assertTrue(env["PATH"].startswith(os.path.dirname(self.fake)))

    def test_setup_is_idempotent(self):
        open(self.log, "w").close()
        self.assertIn("gbrain 0.0.0-fake", self.brain.setup())
        self.assertNotIn("init", [e["cmd"] for e in self.entries()])

    def test_keywords(self):
        self.assertEqual(keywords("Build a login page with email + password", "Test the login"),
                         ["login", "page", "email", "password", "test"])


if __name__ == "__main__":
    unittest.main()
