"""Harness tests. Fake `hermes` / `claude` executables on PATH record the argv, environment and
config they receive, so we can check how each agent's custom LLM is projected into each harness.

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import stat
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import flow  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.harness import HarnessError, create_harness  # noqa: E402
from babd.harness import hermes as hermes_mod  # noqa: E402
from babd.harness import tools  # noqa: E402
from babd.harness.hermes import clean_hermes_output  # noqa: E402
from babd.team import Team  # noqa: E402

FAKE_HERMES = r'''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:3] == ["gateway", "run"]:
    # Minimal Hermes API server: /health, POST /v1/runs, GET /v1/runs/<id>
    from http.server import BaseHTTPRequestHandler, HTTPServer
    key, model = os.environ["API_SERVER_KEY"], open(os.environ["HERMES_HOME"] + "/config.yaml").read()
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps({"gateway": sys.argv[1:], "key_len": len(key), "config": model,
                            "host": os.environ["API_SERVER_HOST"]}) + "\n")
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def reply(self, body, code=200):
            data = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health":
                return self.reply({"status": "ok"})
            if self.headers.get("Authorization") != "Bearer " + key:
                return self.reply({}, 401)
            self.reply({"status": "completed", "output": "auto gateway answer"})
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("Authorization") != "Bearer " + key:
                return self.reply({}, 401)
            self.reply({"run_id": "r9", "status": "started"})
    HTTPServer(("127.0.0.1", int(os.environ["API_SERVER_PORT"])), H).serve_forever()
home = os.environ["HERMES_HOME"]
cfg = open(os.path.join(home, "config.yaml")).read()
log = {"argv": sys.argv[1:], "cwd": os.getcwd(), "config": cfg,
       "env": {k: os.environ.get(k) for k in ("HERMES_HOME", "OPENAI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                                              "ANTHROPIC_BASE_URL")}}
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(log) + "\n")
q = sys.argv[sys.argv.index("-q") + 1]
if '"assignments"' in q:
    body = '{"plan_summary": "p", "assignments": {}}'
else:
    body = "hermes did: " + q.splitlines()[0][:40]
    if "VERDICT: PASS or VERDICT: FAIL" in q:
        body += "\nVERDICT: PASS"
print("[tool] terminal ls\n┊ 💬 " + body + "\n\nsession_id: 20261007_abc")
'''

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
prompt = sys.stdin.read()
log = {"argv": sys.argv[1:], "stdin": prompt,
       "env": {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
                                              "CLAUDE_CONFIG_DIR", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")}}
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(log) + "\n")
if os.environ.get("FAKE_CLAUDE_FAIL"):
    print(json.dumps({"type": "result", "is_error": True, "result": "Credit balance is too low"}))
else:
    print(json.dumps({"type": "result", "is_error": False, "result": "claude did: " + prompt[:30]}))
'''

FAKE_TOOL = r'''#!/usr/bin/env python3
import os, sys
data = sys.stdin.read()
print(f"tool {sys.argv[1:]} model={os.environ['BABD_LLM_MODEL']} key={os.environ['BABD_LLM_API_KEY']} "
      f"base={os.environ['OPENAI_BASE_URL']} lines={len(data.splitlines())}")
'''


def write_exe(directory, name, source):
    path = os.path.join(directory, name)
    with open(path, "w") as f:
        f.write(source)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class Gateway(BaseHTTPRequestHandler):
    runs = {}
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, body, code=200):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        Gateway.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if self.headers.get("Authorization") != "Bearer gw-key":
            return self._send({"error": "unauthorized"}, 401)
        if self.path == "/v1/runs":
            Gateway.runs["r1"] = 0
            return self._send({"run_id": "r1", "status": "queued"})
        self._send({})

    def do_GET(self):
        Gateway.runs["r1"] += 1  # first poll: running, second: completed
        if Gateway.runs["r1"] < 2:
            return self._send({"run_id": "r1", "status": "running"})
        self._send({"run_id": "r1", "status": "completed", "output": "gateway answer"})


class InstallTest(unittest.TestCase):
    """ensure_command(): explicit command -> managed install -> PATH -> auto-install."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.spec = tools.InstallSpec("faketool", "pip", "fake-tool", "fake-tool-cli")
        patcher = mock.patch.object(tools, "TOOLS_DIR", os.path.join(self.tmp, "tools"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runs = []

        def fake_run(argv, what):  # stands in for venv creation / pip install
            self.runs.append(argv)
            if "pip" in argv:
                write_exe(os.path.join(tools.tool_dir(self.spec), "bin"), "fake-tool-cli", "#!/bin/sh\necho hi\n")

        os.makedirs(os.path.join(tools.TOOLS_DIR, "faketool", "bin"), exist_ok=True)
        run_patch = mock.patch.object(tools, "_run", side_effect=fake_run)
        run_patch.start()
        self.addCleanup(run_patch.stop)
        self.env = mock.patch.dict(os.environ, {"PATH": os.path.join(self.tmp, "empty")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_auto_install_when_missing(self):
        path = tools.ensure_command("Fake", {}, self.spec)
        self.assertEqual(path, tools.managed_path(self.spec))
        self.assertIn("fake-tool", self.runs[-1])
        self.assertEqual(tools.installed_requirement(self.spec), "fake-tool")
        self.runs.clear()
        self.assertEqual(tools.ensure_command("Fake", {}, self.spec), path)  # already installed: no reinstall
        self.assertEqual(self.runs, [])

    def test_version_pin_reinstalls(self):
        tools.ensure_command("Fake", {}, self.spec)
        tools.ensure_command("Fake", {"version": "1.2.3"}, self.spec)
        self.assertIn("fake-tool==1.2.3", self.runs[-1])
        self.assertEqual(tools.installed_requirement(self.spec), "fake-tool==1.2.3")

    def test_extras_installed_and_topped_up(self):
        spec = tools.InstallSpec("faketool", "pip", "fake-tool", "fake-tool-cli", extras=("aiohttp>=3.9",))
        tools.ensure_command("Fake", {}, self.spec)  # an install from before extras existed
        self.runs.clear()
        tools.ensure_command("Fake", {}, spec)
        self.assertEqual(self.runs[-1][-2:], ["fake-tool", "aiohttp>=3.9"])
        self.assertEqual(tools.installed_requirement(spec), "fake-tool aiohttp>=3.9")

    def test_prefers_program_on_path(self):
        bin_dir = os.path.join(self.tmp, "empty")
        os.makedirs(bin_dir)
        write_exe(bin_dir, "fake-tool-cli", "#!/bin/sh\n")
        self.assertEqual(tools.ensure_command("Fake", {}, self.spec), os.path.join(bin_dir, "fake-tool-cli"))
        self.assertEqual(self.runs, [])

    def test_auto_install_off(self):
        with self.assertRaisesRegex(HarnessError, "auto_install is off .*pip install fake-tool"):
            tools.ensure_command("Fake", {"auto_install": False}, self.spec)

    def test_npm_layout(self):
        spec = tools.InstallSpec("cc", "npm", "@anthropic-ai/claude-code", "claude")
        self.assertTrue(tools.managed_path(spec).endswith(os.path.join("cc", "node_modules", ".bin", "claude")))
        self.assertEqual(spec.requirement("2.1.0"), "@anthropic-ai/claude-code@2.1.0")


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        write_exe(self.bin, "hermes", FAKE_HERMES)
        write_exe(self.bin, "claude", FAKE_CLAUDE)
        write_exe(self.bin, "faketool", FAKE_TOOL)
        self.log = os.path.join(self.tmp, "calls.jsonl")
        self.env = mock.patch.dict(os.environ, {
            "PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_LOG": self.log,
            "ANTHROPIC_API_KEY": "sk-ant-agent", "LOCAL_LLM_API_KEY": "local-secret"})
        self.env.start()
        self.addCleanup(self.env.stop)
        # never use a real Hermes / Claude Code installed under .babd/tools
        tools_patch = mock.patch.object(tools, "TOOLS_DIR", os.path.join(self.tmp, "tools"))
        tools_patch.start()
        self.addCleanup(tools_patch.stop)
        self.cfg = copy.deepcopy(load_config())
        self.cfg["project"]["gbrain"] = {"enabled": False}  # memory is covered in test_gbrain.py
        for a in self.cfg["agents"]:
            if a["harness"]["type"] != "direct":
                a["harness"]["home"] = os.path.join(self.tmp, "homes", a["id"])
                a["harness"]["cwd"] = os.path.join(self.tmp, "workspace")
        self.agents = {a["id"]: a for a in self.cfg["agents"]}

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def test_hermes_custom_openai_llm(self):
        devops = self.agents["devops"]  # custom OpenAI-compatible endpoint through Hermes
        reply = create_harness(devops).complete("SYS", [{"role": "user", "content": "deploy it"}])
        self.assertEqual(reply, "hermes did: SYS")
        call = self.calls()[-1]
        self.assertIn('provider: "custom"', call["config"])
        self.assertIn('base_url: "http://localhost:11434/v1"', call["config"])
        self.assertIn('api_key: "${OPENAI_API_KEY}"', call["config"])
        self.assertNotIn("local-secret", call["config"])  # key only in the environment
        self.assertEqual(call["env"]["OPENAI_API_KEY"], "local-secret")
        self.assertEqual(call["env"]["HERMES_HOME"], devops["harness"]["home"])
        argv = call["argv"]
        self.assertEqual(argv[:2], ["chat", "-q"])
        self.assertIn("deploy it", argv[2])
        self.assertEqual(argv[argv.index("-m") + 1], "qwen2.5-coder:7b")
        self.assertNotIn("--provider", argv)
        self.assertEqual(argv[argv.index("-t") + 1], "terminal,file")
        self.assertNotIn("--yolo", argv)
        self.assertNotIn("-s", argv)
        self.assertEqual(call["cwd"], devops["harness"]["cwd"])
        mode = stat.S_IMODE(os.stat(os.path.join(devops["harness"]["home"], "config.yaml")).st_mode)
        self.assertEqual(mode, 0o600)

    def test_hermes_anthropic_llm(self):
        arch = self.agents["architect"]
        create_harness(arch).complete("SYS", [{"role": "user", "content": "design"}])
        call = self.calls()[-1]
        self.assertIn('provider: "anthropic"', call["config"])
        self.assertIn('default: "claude-opus-5-5"', call["config"])
        self.assertNotIn("base_url", call["config"])
        self.assertEqual(call["env"]["ANTHROPIC_API_KEY"], "sk-ant-agent")
        self.assertEqual(call["env"]["ANTHROPIC_BASE_URL"], "https://api.anthropic.com")
        self.assertEqual(call["argv"][call["argv"].index("--provider") + 1], "anthropic")

    def test_hermes_options(self):
        agent = copy.deepcopy(self.agents["qa"])
        agent["harness"].update(skills=["github-pr-workflow", "test-driven-development"], yolo=True, max_turns=5)
        create_harness(agent).complete("S", [{"role": "user", "content": "x"}])
        argv = self.calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("-s") + 1], "github-pr-workflow,test-driven-development")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "5")
        self.assertIn("--yolo", argv)
        self.assertEqual(argv[argv.index("--source") + 1], "tool")

    def test_each_agent_gets_its_own_hermes_home(self):
        create_harness(self.agents["qa"]).complete("S", [{"role": "user", "content": "x"}])
        create_harness(self.agents["devops"]).complete("S", [{"role": "user", "content": "x"}])
        qa, devops = self.calls()
        self.assertNotEqual(qa["env"]["HERMES_HOME"], devops["env"]["HERMES_HOME"])
        self.assertIn("claude-sonnet-5-5", qa["config"])
        self.assertIn("qwen2.5-coder:7b", devops["config"])

    def test_claude_code(self):
        dev = copy.deepcopy(self.agents["developer"])
        dev["llm"]["base_url"] = "https://llm-proxy.example.com/v1"
        dev["harness"]["config_dir"] = os.path.join(self.tmp, "claude-dev")
        reply = create_harness(dev).complete("SYS", [{"role": "user", "content": "write code"}])
        self.assertEqual(reply, "claude did: write code")
        call = self.calls()[-1]
        argv = call["argv"]
        self.assertEqual(argv[:3], ["--print", "--output-format", "json"])
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1], "SYS")
        self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-5-5")
        self.assertEqual(argv[argv.index("--effort") + 1], "medium")
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertEqual(call["env"]["ANTHROPIC_BASE_URL"], "https://llm-proxy.example.com")
        self.assertEqual(call["env"]["ANTHROPIC_MODEL"], "claude-sonnet-5-5")
        self.assertEqual(call["env"]["ANTHROPIC_API_KEY"], "sk-ant-agent")
        # the agent has its own key, so Claude Code gets a private config dir (not the machine's login)
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], os.path.join(self.tmp, "claude-dev"))

    def test_claude_code_shared_login_without_key(self):
        dev = copy.deepcopy(self.agents["developer"])
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "ANTHROPIC_BASE_URL": "http://host-proxy"}):
            create_harness(dev).complete("S", [{"role": "user", "content": "x"}])
        env = self.calls()[-1]["env"]
        self.assertIsNone(env["CLAUDE_CONFIG_DIR"])
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://host-proxy")  # machine's own setup kept

    def test_claude_code_own_key_beats_inherited_auth(self):
        """An inherited proxy URL or OAuth token must not override the agent's own key."""
        dev = copy.deepcopy(self.agents["developer"])
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "http://host-proxy",
                                          "ANTHROPIC_AUTH_TOKEN": "other-login", "CLAUDE_CODE_OAUTH_TOKEN": "x"}):
            create_harness(dev).complete("S", [{"role": "user", "content": "x"}])
        env = self.calls()[-1]["env"]
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.anthropic.com")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-ant-agent")
        self.assertIsNone(env["ANTHROPIC_AUTH_TOKEN"])
        self.assertIsNone(env["CLAUDE_CODE_OAUTH_TOKEN"])

    def test_claude_code_error_and_wrong_llm(self):
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_FAIL": "1"}):
            with self.assertRaisesRegex(HarnessError, "Credit balance"):
                create_harness(self.agents["developer"]).complete("S", [{"role": "user", "content": "x"}])
        dev = copy.deepcopy(self.agents["developer"])
        dev["llm"] = self.agents["devops"]["llm"]  # OpenAI-compatible endpoint
        with self.assertRaisesRegex(HarnessError, "Anthropic-compatible"):
            create_harness(dev).complete("S", [{"role": "user", "content": "x"}])

    def test_process_install_runs_once(self):
        agent = copy.deepcopy(self.agents["devops"])
        marker = os.path.join(self.tmp, "installed.txt")
        agent["harness"] = {"type": "process", "command": "faketool", "cwd": os.path.join(self.tmp, "workspace"),
                            "install": [sys.executable, "-c", f"open({marker!r}, 'a').write('x')"]}
        with mock.patch.object(tools, "TOOLS_DIR", os.path.join(self.tmp, "tools")):
            h = create_harness(agent)
            h.complete("S", [{"role": "user", "content": "x"}])
            h.complete("S", [{"role": "user", "content": "y"}])
        self.assertEqual(open(marker).read(), "x")

    def test_process_harness(self):
        agent = copy.deepcopy(self.agents["devops"])
        agent["harness"] = {"type": "process", "command": "faketool", "args": ["--model", "{model}"],
                            "cwd": os.path.join(self.tmp, "workspace")}
        reply = create_harness(agent).complete("SYS", [{"role": "user", "content": "go"}])
        self.assertIn("['--model', 'qwen2.5-coder:7b']", reply)
        self.assertIn("key=local-secret", reply)
        self.assertIn("base=http://localhost:11434/v1", reply)

    def test_missing_command(self):
        agent = copy.deepcopy(self.agents["qa"])
        agent["harness"]["command"] = "no-such-hermes"
        with self.assertRaisesRegex(HarnessError, "'no-such-hermes' not found"):
            create_harness(agent).complete("S", [{"role": "user", "content": "x"}])

    def test_unknown_harness(self):
        agent = copy.deepcopy(self.agents["qa"])
        agent["harness"] = "codex_cloud"
        with self.assertRaisesRegex(HarnessError, "unknown harness"):
            create_harness(agent)

    def test_hermes_gateway(self):
        server = HTTPServer(("127.0.0.1", 0), Gateway)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        Gateway.seen = []
        agent = copy.deepcopy(self.agents["qa"])
        agent["harness"] = {"type": "hermes_gateway", "api_base_url": f"http://127.0.0.1:{server.server_port}/",
                            "api_key_env": "GW_KEY", "poll_interval_sec": 0.01, "send_model": True}
        with mock.patch.dict(os.environ, {"GW_KEY": "gw-key"}):
            reply = create_harness(agent).complete("SYS", [{"role": "user", "content": "test it"}])
        self.assertEqual(reply, "gateway answer")
        create = Gateway.seen[0]
        self.assertEqual(create["path"], "/v1/runs")
        self.assertEqual(create["body"]["instructions"], "SYS")
        self.assertEqual(create["body"]["input"], "test it")
        self.assertEqual(create["body"]["model"], "claude-sonnet-5-5")
        with mock.patch.dict(os.environ, {"GW_KEY": "wrong"}):
            with self.assertRaisesRegex(HarnessError, "HTTP 401"):
                create_harness(agent).complete("SYS", [{"role": "user", "content": "x"}])

    def test_hermes_gateway_auto_start(self):
        """No api_base_url: BABD starts a private gateway with the agent's LLM and a generated key."""
        agent = copy.deepcopy(self.agents["devops"])
        agent["harness"] = {"type": "hermes_gateway", "home": os.path.join(self.tmp, "gw"),
                            "cwd": os.path.join(self.tmp, "workspace"), "poll_interval_sec": 0.01}
        harness = create_harness(agent)
        self.assertIn("gateway starts on first run", harness.setup())
        try:
            reply = harness.complete("SYS", [{"role": "user", "content": "hi"}])
            self.assertEqual(reply, "auto gateway answer")
            started = [c for c in self.calls() if "gateway" in c][0]
            self.assertEqual(started["gateway"], ["gateway", "run", "--replace", "--accept-hooks"])
            self.assertEqual(started["key_len"], 64)  # Hermes rejects keys under 16 chars
            self.assertEqual(started["host"], "127.0.0.1")
            self.assertIn("qwen2.5-coder:7b", started["config"])
            key_file = os.path.join(self.tmp, "gw", "api_server_key")
            self.assertEqual(stat.S_IMODE(os.stat(key_file).st_mode), 0o600)
            # second call reuses the running gateway
            harness.complete("SYS", [{"role": "user", "content": "again"}])
            self.assertEqual(len([c for c in self.calls() if "gateway" in c]), 1)
        finally:
            hermes_mod._stop_started_gateways()

    def test_clean_hermes_output(self):
        out = ("⚠ tirith security scanner enabled but not available\n[tool] terminal ls\n┊ 💬 Line one\n\n\n\n"
               "Line two\n\nsession_id: 2026_x\n")
        self.assertEqual(clean_hermes_output(out), "Line one\n\nLine two")

    def test_full_run_with_mixed_harnesses(self):
        """Lead (direct, mocked SDK call) + Hermes + Claude Code agents in one team run."""
        replies = iter([
            '{"plan_summary": "p", "assignments": {"architect": "A", "developer": "D", "qa": "Q", "devops": "O"}}',
            '{"next_action": "Review", "summary": "ok"}',
        ])
        with mock.patch("babd.harness.others.Direct.complete", side_effect=lambda *a, **k: next(replies)), \
                mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs")):
            state = Team(self.cfg, log=lambda m: None).run("Build login", approver=lambda r: (True, ""))
        self.assertEqual(state["status"], "done", state["error"])
        out = {m["from"]: m["content"] for m in state["messages"] if m["to"] == "lead" and m["from"] != "ceo"}
        self.assertTrue(out["architect"].startswith("hermes did:"))
        self.assertTrue(out["developer"].startswith("claude did:"))
        self.assertEqual(state["report"]["next_action"], "Review")
        kinds = ["claude" if "stdin" in c else "hermes" for c in self.calls()]
        self.assertEqual(kinds, ["hermes", "claude", "hermes", "hermes"])
        # Developer (Claude Code) got the Architect's design in its prompt
        self.assertIn("Design from Architect", self.calls()[1]["stdin"])

if __name__ == "__main__":
    unittest.main()
