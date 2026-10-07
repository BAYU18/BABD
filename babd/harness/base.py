"""Harness interface: how an agent turns (system prompt, conversation) into a reply.

Modelled on Paperclip's adapters (packages/adapters/* in paperclipai/paperclip): every harness gets
the agent's own `llm` block and projects it into whatever that harness needs (SDK client,
config file, environment variables), so each agent keeps its custom LLM whatever harness it uses.
"""
import os
import shutil
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

    def resolve_command(self, default):
        command = self.cfg.get("command") or default
        path = shutil.which(command)
        if not path:
            raise HarnessError(f"{self.label}: command {command!r} not found on PATH")
        return path

    def run_process(self, argv, env_overrides, stdin_text=None):
        env = dict(os.environ)
        env.update(self.cfg.get("env") or {})
        env.update(env_overrides)
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
