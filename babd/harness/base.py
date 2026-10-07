"""Harness interface: how an agent turns (system prompt, conversation) into a reply.

Modelled on Paperclip's adapters (packages/adapters/* in paperclipai/paperclip): every harness gets
the agent's own `llm` block and projects it into whatever that harness needs (SDK client,
config file, environment variables), so each agent keeps its custom LLM whatever harness it uses.
"""
import os
import subprocess

from ..config import ROOT
from ..llm import LLMError

DEFAULT_TIMEOUT_SEC = 1800
DEFAULT_WORKSPACE = os.path.join(ROOT, "workspace")


class HarnessError(LLMError):
    pass


class Harness:
    type = ""
    label = ""
    install_spec = None   # tools.InstallSpec of the program this harness runs, if any
    defaults = {}         # options written to agents.json when this harness is selected

    def __init__(self, agent_cfg):
        self.agent_cfg = agent_cfg
        self.agent_id = agent_cfg["id"]
        self.llm = agent_cfg["llm"]
        self.cfg = harness_config(agent_cfg)

    def complete(self, system, messages, max_tokens=None, effort=None):
        raise NotImplementedError

    def describe(self):
        """Short text for the card / CLI, e.g. 'hermes chat - terminal,file'."""
        return self.label

    def setup(self):
        """Install what this harness needs and write its configuration. Safe to run repeatedly.
        Returns a one-line summary. Called by `babd setup` / `babd use`, and before the first run."""
        parts = []
        if self.install_spec:
            path = self.command_path()
            parts.append(os.path.relpath(path, ROOT) if path.startswith(ROOT + os.sep) else path)
        parts += self.configure() or []
        return " · ".join(parts) or "ready"

    def configure(self):
        """Write harness config files for this agent. Returns notes for the summary."""
        return []

    def command_path(self):
        from .tools import ensure_command  # tools imports this module
        return ensure_command(self.label, self.cfg, self.install_spec)

    # -- helpers for CLI harnesses ------------------------------------------------------------

    @property
    def timeout(self):
        return float(self.cfg.get("timeout_sec", DEFAULT_TIMEOUT_SEC)) or None

    @property
    def cwd(self):
        cwd = self.cfg.get("cwd") or DEFAULT_WORKSPACE
        if not os.path.isabs(cwd):
            cwd = os.path.join(ROOT, cwd)
        os.makedirs(cwd, exist_ok=True)
        return cwd

    def run_process(self, argv, env_overrides, stdin_text=None):
        from .tools import extra_path  # tools imports this module
        env = apply_env(os.environ, self.cfg.get("env") or {}, env_overrides)
        env["PATH"] = os.pathsep.join(extra_path() + [env.get("PATH", "")])
        try:
            proc = subprocess.run(argv, input=stdin_text, capture_output=True, text=True, env=env,
                                  cwd=self.cwd, timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise HarnessError(f"{self.label}: timed out after {self.timeout:.0f}s") from e
        if proc.returncode != 0:
            # CLIs print errors on stdout or stderr; the first and last meaningful lines carry the story.
            lines = [ln.strip() for ln in (proc.stdout + "\n" + proc.stderr).splitlines()
                     if ln.strip() and not ln.strip().startswith("session_id:")]
            detail = " | ".join(dict.fromkeys(lines[:1] + lines[-1:])) or "no output"
            raise HarnessError(f"{self.label}: exit code {proc.returncode}: {detail[:500]}")
        return proc.stdout


def apply_env(base, *layers):
    """Copy of `base` with each layer applied in order; a value of None removes the variable."""
    env = dict(base)
    for layer in layers:
        for k, v in layer.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = str(v)
    return env


def harness_config(agent_cfg):
    """The agent's harness block; a bare string is shorthand for {"type": <string>}."""
    h = agent_cfg.get("harness") or {"type": "direct"}
    return {"type": h} if isinstance(h, str) else dict(h)


def render_prompt(system, messages):
    """Flatten system prompt + conversation into one prompt for CLI harnesses that take a single query.

    Same shape Paperclip uses for Hermes: instructions first, a separator, then the task.
    """
    parts = [system.strip(), "---"]
    if len(messages) == 1:
        parts.append(messages[0]["content"])
    else:
        for m in messages:
            who = "User" if m["role"] == "user" else "You (earlier reply)"
            parts.append(f"## {who}\n{m['content']}")
    return "\n\n".join(parts)
