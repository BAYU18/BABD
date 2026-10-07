"""Hermes Agent (NousResearch/hermes-agent) harnesses, after Paperclip's `hermes_local` and
`hermes_gateway` adapters (packages/adapters/hermes)."""
import atexit
import json
import os
import re
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request

from ..config import ROOT
from .base import Harness, HarnessError, apply_env, render_prompt
from .routing import hermes_routing
from .tools import HERMES

SESSION_ID_RE = re.compile(r"^session_id:\s*(\S+)", re.M)


def clean_hermes_output(stdout):
    """Response text from `hermes chat -Q`: everything before the trailing `session_id:` line,
    minus tool / status / warning noise lines (Paperclip's cleanResponse filters, plus Hermes' "⚠" warnings)."""
    idx = stdout.rfind("\nsession_id:")
    if idx < 0 and stdout.startswith("session_id:"):
        idx = 0
    text = stdout[:idx] if idx >= 0 else stdout
    keep = []
    for line in text.splitlines():
        t = line.strip()
        if t.startswith(("[tool]", "[hermes]", "session_id:", "⚠")) or re.match(r"^\[\d{4}-\d{2}-\d{2}T", t):
            continue
        keep.append(re.sub(r"^\s*┊\s*💬\s*", "", line).rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(keep)).strip()


def _abs(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def _write_private(path, content):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(content)


def write_hermes_home(home, llm):
    """Write HERMES_HOME/config.yaml for this agent's LLM. Returns (env, provider_arg)."""
    env, config_yaml, provider = hermes_routing(llm)
    _write_private(os.path.join(home, "config.yaml"), config_yaml)
    env["HERMES_HOME"] = home
    return env, provider


class HermesLocal(Harness):
    """Runs `hermes chat -q <prompt> -Q` with a per-agent HERMES_HOME holding this agent's model config."""
    type = "hermes_local"
    label = "Hermes Agent"
    install_spec = HERMES
    defaults = {"toolsets": ["terminal", "file"], "max_turns": 30, "timeout_sec": 1200, "yolo": False}

    @property
    def home(self):
        return _abs(self.cfg.get("home") or os.path.join(".babd", "hermes", self.agent_id))

    def describe(self):
        tools = ",".join(self.cfg.get("toolsets") or []) or "default tools"
        return f"hermes chat · {tools}"

    def configure(self):
        if not self.cfg.get("manage_config", True):
            return [f"using existing {self.home}"]
        write_hermes_home(self.home, self.llm)
        return [f"config {os.path.relpath(os.path.join(self.home, 'config.yaml'), ROOT)}"]

    def build(self, system, messages):
        """(argv, env) for one run. Separate from complete() so it can be tested."""
        env, _, provider = hermes_routing(self.llm)
        env["HERMES_HOME"] = self.home
        prompt = render_prompt(system, messages)
        argv = [self.command_path(), "chat", "-q", prompt, "-Q"]
        if self.llm.get("model"):
            argv += ["-m", self.llm["model"]]
        if provider:
            argv += ["--provider", provider]
        if self.cfg.get("toolsets"):
            argv += ["-t", ",".join(self.cfg["toolsets"])]
        if self.cfg.get("skills"):
            argv += ["-s", ",".join(self.cfg["skills"])]  # Hermes-native skills to preload
        if self.cfg.get("max_turns"):
            argv += ["--max-turns", str(self.cfg["max_turns"])]
        if self.cfg.get("worktree"):
            argv.append("-w")
        if self.cfg.get("checkpoints"):
            argv.append("--checkpoints")
        argv += ["--source", "tool"]
        if self.cfg.get("yolo"):
            # Skip Hermes' dangerous-command approvals. Without a TTY those prompts can only deny,
            # so tools that need approval fail unless this is on. Use it only in a sandbox.
            argv.append("--yolo")
        argv += list(self.cfg.get("extra_args") or [])
        return argv, env

    def complete(self, system, messages, max_tokens=None, effort=None):
        self.configure()  # config.yaml always matches the agent's current llm block
        argv, env = self.build(system, messages)
        stdout = self.run_process(argv, env)
        text = clean_hermes_output(stdout)
        if not text:
            raise HarnessError("Hermes Agent: empty response")
        return text


TERMINAL = {"completed", "failed", "error", "cancelled", "canceled", "stopped", "interrupted"}


def _output_of(record):
    if not isinstance(record, dict):
        return None
    for k in ("output", "result", "text", "summary", "message"):
        if isinstance(record.get(k), str) and record[k].strip():
            return record[k]
    for k in ("data", "payload"):
        out = _output_of(record.get(k))
        if out:
            return out
    return None


_STARTED = {}  # agent id -> (Popen, base_url) for gateways this process started


def _stop_started_gateways():
    for proc, _ in _STARTED.values():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    _STARTED.clear()


atexit.register(_stop_started_gateways)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class HermesGateway(Harness):
    """Calls a Hermes API server: POST /v1/runs, then polls GET /v1/runs/{id}.

    With `api_base_url` it uses that server (its model is configured there). Without it, BABD
    installs Hermes and starts a private gateway for this agent on 127.0.0.1, configured with the
    agent's own LLM and a generated API key, and stops it when BABD exits.
    """
    type = "hermes_gateway"
    label = "Hermes Gateway"
    defaults = {"timeout_sec": 1200}

    @property
    def managed(self):
        return not self.cfg.get("api_base_url")

    @property
    def install_spec(self):
        return HERMES if self.managed else None

    @property
    def home(self):
        return _abs(self.cfg.get("home") or os.path.join(".babd", "hermes-gateway", self.agent_id))

    def describe(self):
        return f"gateway · {self.cfg.get('api_base_url') or 'auto-started on 127.0.0.1'}"

    def _managed_key(self):
        path = os.path.join(self.home, "api_server_key")
        if not os.path.exists(path):
            # Hermes refuses keys under 16 chars: this endpoint runs terminal-capable agent work.
            _write_private(path, secrets.token_hex(32))
        with open(path) as f:
            return f.read().strip()

    def _key(self):
        if self.managed:
            return self._managed_key()
        key = self.cfg.get("api_key") or os.environ.get(self.cfg.get("api_key_env", "HERMES_GATEWAY_API_KEY"), "")
        if not key:
            raise HarnessError("Hermes Gateway: no API key (set harness.api_key_env or harness.api_key)")
        return key

    def configure(self):
        if not self.managed:
            return [f"server {self.cfg['api_base_url']}"]
        write_hermes_home(self.home, self.llm)
        self._managed_key()
        return [f"config {os.path.relpath(self.home, ROOT)} (gateway starts on first run)"]

    def _start(self):
        """Start (or reuse) this agent's private gateway. Returns its base URL."""
        started = _STARTED.get(self.agent_id)
        if started and started[0].poll() is None:
            return started[1]
        hermes = self.command_path()
        routing_env, _ = write_hermes_home(self.home, self.llm)
        port = int(self.cfg.get("port") or _free_port())
        env = apply_env(os.environ, self.cfg.get("env") or {}, routing_env, {
            "API_SERVER_ENABLED": "true", "API_SERVER_KEY": self._managed_key(),
            "API_SERVER_HOST": "127.0.0.1", "API_SERVER_PORT": str(port), "NO_COLOR": "1"})
        log_path = os.path.join(self.home, "gateway.log")
        log = open(log_path, "w")
        proc = subprocess.Popen([hermes, "gateway", "run", "--replace", "--accept-hooks"], env=env, cwd=self.cwd,
                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        log.close()
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + float(self.cfg.get("start_timeout_sec", 90))
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as r:
                    if r.status == 200:
                        _STARTED[self.agent_id] = (proc, base)
                        return base
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        if proc.poll() is None:
            proc.terminate()
        with open(log_path) as f:
            tail = " | ".join(ln.strip() for ln in f.read().splitlines()[-3:])
        raise HarnessError(f"Hermes Gateway: local gateway did not start: {tail[:400]}")

    def _request(self, method, url, body=None):
        headers = {"Authorization": f"Bearer {self._key()}", "Accept": "application/json",
                   "X-Hermes-Session-Key": f"babd:{self.agent_id}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            raise HarnessError(f"Hermes Gateway: HTTP {e.code} from {url}") from e
        except urllib.error.URLError as e:
            raise HarnessError(f"Hermes Gateway: cannot reach {url}: {e.reason}") from e
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"text": raw}

    def complete(self, system, messages, max_tokens=None, effort=None):
        base = self._start() if self.managed else self.cfg["api_base_url"].rstrip("/")
        body = {"input": render_prompt("", messages).lstrip("-\n "), "instructions": system,
                "session_id": f"babd:{self.agent_id}"}
        if self.cfg.get("send_model") and self.llm.get("model"):
            body["model"] = self.llm["model"]
        created = self._request("POST", f"{base}/v1/runs", body)
        run_id = created.get("run_id") or created.get("runId") or created.get("id")
        if not run_id:
            raise HarnessError("Hermes Gateway: /v1/runs response had no run_id")

        deadline = time.monotonic() + (self.timeout or 1e9)
        interval = float(self.cfg.get("poll_interval_sec", 2))
        status = created
        while (status.get("status") or "").lower() not in TERMINAL:
            if time.monotonic() > deadline:
                try:
                    self._request("POST", f"{base}/v1/runs/{run_id}/stop", {})
                except HarnessError:
                    pass  # the timeout is the error to report
                raise HarnessError(f"Hermes Gateway: run {run_id} timed out")
            time.sleep(interval)
            status = self._request("GET", f"{base}/v1/runs/{run_id}")
        state = status["status"].lower()
        if state != "completed":
            raise HarnessError(f"Hermes Gateway: run {run_id} {state}: {status.get('error') or ''}".strip())
        out = _output_of(status)
        if not out:
            raise HarnessError(f"Hermes Gateway: run {run_id} completed without output")
        return out.strip()
