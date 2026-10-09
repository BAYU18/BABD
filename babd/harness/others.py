"""The other harnesses: direct LLM API call, Claude Code CLI, and any command (`process`)."""
import hashlib
import json
import os
import shlex
import subprocess

from ..config import ROOT, resolve_api_key
from ..llm import LLMClient
from .base import Harness, HarnessError, render_prompt
from .routing import claude_code_routing, generic_routing
from . import tools
from .tools import CLAUDE_CODE, log


class Direct(Harness):
    """Plain API call to the agent's LLM (Anthropic SDK or OpenAI-compatible SDK). No tools."""
    type = "direct"
    label = "Direct API"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
        self.client = LLMClient(self.llm)

    def describe(self):
        return f"{self.client.api} SDK · no tools"

    def configure(self):
        return [f"{self.client.api} SDK ready"]  # LLMClient() already installed the SDK if missing

    def complete(self, system, messages, max_tokens=None, effort=None):
        text = self.client.complete(system, messages, max_tokens=max_tokens, effort=effort)
        self.record_usage(getattr(self.client.usage, "last", None))
        return text


class ClaudeCode(Harness):
    """Runs `claude --print` (Claude Code) with this agent's Anthropic-compatible endpoint, key and model."""
    type = "claude_local"
    has_tools = True
    label = "Claude Code"
    install_spec = CLAUDE_CODE
    defaults = {"max_turns": 40, "timeout_sec": 1800, "dangerously_skip_permissions": False}

    def describe(self):
        return "claude --print · Claude Code tools"

    @property
    def config_dir(self):
        """Private Claude Code config dir for this agent, so it runs on the agent's own key and
        model rather than whatever account is logged in on this machine. None = shared login."""
        isolated = self.cfg.get("isolated_config")
        if isolated is None:
            isolated = bool(resolve_api_key(self.llm))
        if not isolated:
            return None
        d = self.cfg.get("config_dir") or os.path.join(".babd", "claude", self.agent_id)
        return d if os.path.isabs(d) else os.path.join(ROOT, d)

    def private_dirs(self):
        return [self.config_dir] if self.config_dir else []

    def configure(self):
        claude_code_routing(self.llm)  # fails early on a non-Anthropic endpoint
        if not self.config_dir:
            return ["using this machine's Claude Code login"]
        os.makedirs(self.config_dir, mode=0o700, exist_ok=True)
        notes = [f"config {os.path.relpath(self.config_dir, ROOT)}"]
        from .. import skillpacks
        names = skillpacks.all_names(self.skill_packs)
        if names:  # private config dir only: never touch the machine's own ~/.claude
            skillpacks.install_native(names, os.path.join(self.config_dir, "skills"))
            notes += [f"{len(v)} {k} skills" for k, v in self.skill_packs.items() if v]
        return notes

    def build(self, system, messages, effort=None):
        env = claude_code_routing(self.llm)
        if self.config_dir:
            env["CLAUDE_CONFIG_DIR"] = self.config_dir
        argv = [self.command_path(), "--print", "--output-format", "json"]
        # One argument over 128 KiB fails with "Argument list too long": a very long system prompt
        # goes at the top of the prompt on stdin instead.
        long_system = len(system.encode()) > 100_000
        if system and not long_system:
            argv += ["--append-system-prompt", system]
        if self.llm.get("model"):
            argv += ["--model", self.llm["model"]]
        effort = effort or self.llm.get("effort")
        if effort:
            argv += ["--effort", effort]
        if self.cfg.get("max_turns"):
            argv += ["--max-turns", str(self.cfg["max_turns"])]
        from .. import permissions
        profile = "full" if self.cfg.get("dangerously_skip_permissions") else self.permissions
        argv += permissions.claude_args(profile)
        argv += list(self.cfg.get("extra_args") or [])
        prompt = messages[-1]["content"] if len(messages) == 1 else render_prompt("", messages).lstrip("-\n ")
        if long_system:
            prompt = f"# Your instructions\n\n{system}\n\n---\n\n{prompt}"
        return argv, env, prompt

    def complete(self, system, messages, max_tokens=None, effort=None):
        self.configure()
        argv, env, prompt = self.build(system, messages, effort)
        stdout = self.run_process(argv, env, stdin_text=prompt)
        try:
            result = json.loads(stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as e:
            raise HarnessError(f"Claude Code: unexpected output: {stdout[:300]}") from e
        if result.get("is_error"):
            raise HarnessError(f"Claude Code: {result.get('result') or result.get('subtype') or 'error'}")
        text = (result.get("result") or "").strip()
        if not text:
            raise HarnessError("Claude Code: empty result")
        u = result.get("usage") or {}
        if u:
            self.record_usage({"input": sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                                     "cache_creation_input_tokens")),
                               "output": u.get("output_tokens") or 0, "cost": result.get("total_cost_usd")})
        return text


class Process(Harness):
    """Any command. Gets the prompt on stdin, the LLM settings in env vars, and returns its stdout.

    `args` may use {model} and {base_url}. The API key is only passed in env vars, never on the
    command line.
    """
    type = "process"
    label = "Custom process"

    @property
    def has_tools(self):
        """A `process` harness runs a real command (its own adapter), so it reads/writes files and
        runs commands itself: BABD must not write its file blocks, and triage must not describe it as
        "cannot run commands (plans and writes text only)". A process harness with no command is not
        a runner - keep the safe `False` default so BABD still writes its file blocks."""
        return bool(self.cfg.get("command"))

    def describe(self):
        return " ".join([self.cfg.get("command", "?")] + list(self.cfg.get("args") or []))[:40]

    def setup(self):
        """Run `install` (once per distinct install command), then check `command` exists."""
        if not self.cfg.get("command"):
            raise HarnessError("process: harness.command is required")
        install = self.cfg.get("install")
        if install:
            argv = shlex.split(install) if isinstance(install, str) else [str(a) for a in install]
            # A relative `install` (e.g. `scripts/researcher_setup.sh` in agents.json) is ROOT-relative,
            # exactly like `command`: resolve it to an absolute path so the subprocess launched from
            # any cwd still finds the program (QA B-9: with cwd = DEFAULT_WORKSPACE it used to die with
            # `FileNotFoundError: 'scripts/researcher_setup.sh'`, so the researcher agent's first-run
            # install - and the dashboard Setup button - never worked).
            if argv and not os.path.isabs(argv[0]) and os.sep in argv[0]:
                argv[0] = os.path.join(ROOT, argv[0])
            digest = hashlib.sha256(json.dumps(argv).encode()).hexdigest()[:16]
            marker = os.path.join(tools.TOOLS_DIR, f"process-{self.agent_id}.{digest}.installed")
            if not os.path.exists(marker):
                log(f"{self.agent_id}: running install: {' '.join(argv)}")
                try:
                    proc = subprocess.run(argv, capture_output=True, text=True, cwd=self.cwd, timeout=1200)
                except FileNotFoundError as e:
                    # Mirror `ensure_command`'s friendly message instead of leaking a raw
                    # FileNotFoundError from deep inside subprocess (QA B-10).
                    raise HarnessError(
                        f"process install: {argv[0]!r} not found (check harness.install in agents.json)") from e
                if proc.returncode != 0:
                    tail = " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:])
                    raise HarnessError(f"process install failed: {tail[:400]}")
                os.makedirs(tools.TOOLS_DIR, exist_ok=True)
                open(marker, "w").close()
        return self.command_path()

    def command_path(self):
        from .tools import ensure_command
        # Pass the whole harness cfg (not a fresh {"command": ...} dict) so options such as
        # `auto_install`/`version` keep working; `Process` has no InstallSpec of its own.
        return ensure_command(self.label, self.cfg, self.install_spec)

    def complete(self, system, messages, max_tokens=None, effort=None):
        self.setup()
        subst = {"model": self.llm.get("model", ""), "base_url": self.llm.get("base_url", "")}
        argv = [self.command_path()]
        argv += [str(a).format(**subst) for a in self.cfg.get("args") or []]
        env = generic_routing(self.llm)
        env["BABD_AGENT_ID"] = self.agent_id
        env["BABD_SYSTEM_PROMPT"] = system
        text = self.run_process(argv, env, stdin_text=render_prompt(system, messages)).strip()
        if not text:
            raise HarnessError(f"process {self.cfg['command']}: empty output")
        return text
