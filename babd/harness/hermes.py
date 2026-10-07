"""Hermes Agent (NousResearch/hermes-agent) harnesses, after Paperclip's `hermes_local` and
`hermes_gateway` adapters (packages/adapters/hermes)."""
import json
import os
import re
import time
import urllib.error
import urllib.request

from ..config import ROOT
from .base import Harness, HarnessError, render_prompt
from .routing import hermes_routing

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


class HermesLocal(Harness):
    """Runs `hermes chat -q <prompt> -Q` with a per-agent HERMES_HOME holding this agent's model config."""
    type = "hermes_local"
    label = "Hermes Agent"

    @property
    def home(self):
        home = self.cfg.get("home") or os.path.join(ROOT, ".babd", "hermes", self.agent_id)
        if not os.path.isabs(home):
            home = os.path.join(ROOT, home)
        return home

    def describe(self):
        tools = ",".join(self.cfg.get("toolsets") or []) or "default tools"
        return f"hermes chat · {tools}"

    def build(self, system, messages):
        """(argv, env, config_yaml) for one run. Separate from complete() so it can be tested."""
        env, config_yaml, provider = hermes_routing(self.llm)
        env["HERMES_HOME"] = self.home
        prompt = render_prompt(system, messages)
        argv = [self.resolve_command("hermes"), "chat", "-q", prompt, "-Q"]
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
        return argv, env, config_yaml

    def complete(self, system, messages, max_tokens=None, effort=None):
        argv, env, config_yaml = self.build(system, messages)
        if self.cfg.get("manage_config", True):
            os.makedirs(self.home, mode=0o700, exist_ok=True)
            path = os.path.join(self.home, "config.yaml")
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.write(config_yaml)
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


class HermesGateway(Harness):
    """Calls a running Hermes API server: POST /v1/runs, then polls GET /v1/runs/{id}.

    The model is configured on the Hermes server itself; this agent's `llm` block is only sent
    along when `send_model` is true (for gateways that accept a per-run model).
    """
    type = "hermes_gateway"
    label = "Hermes Gateway"

    def describe(self):
        return f"gateway · {self.cfg.get('api_base_url', '?')}"

    def _request(self, method, url, body=None):
        key = self.cfg.get("api_key") or os.environ.get(self.cfg.get("api_key_env", "HERMES_GATEWAY_API_KEY"), "")
        if not key:
            raise HarnessError("Hermes Gateway: no API key (set harness.api_key_env or harness.api_key)")
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json",
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
        base = (self.cfg.get("api_base_url") or "").rstrip("/")
        if not base:
            raise HarnessError("Hermes Gateway: harness.api_base_url is required")
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
