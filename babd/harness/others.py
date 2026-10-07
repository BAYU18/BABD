"""The other harnesses: direct LLM API call, Claude Code CLI, and any command (`process`)."""
import json

from ..llm import LLMClient
from .base import Harness, HarnessError, render_prompt
from .routing import claude_code_routing, generic_routing


class Direct(Harness):
    """Plain API call to the agent's LLM (Anthropic SDK or OpenAI-compatible SDK). No tools."""
    type = "direct"
    label = "Direct API"

    def __init__(self, agent_cfg):
        super().__init__(agent_cfg)
        self.client = LLMClient(self.llm)

    def describe(self):
        return f"{self.client.api} SDK · no tools"

    def complete(self, system, messages, max_tokens=None, effort=None):
        return self.client.complete(system, messages, max_tokens=max_tokens, effort=effort)


class ClaudeCode(Harness):
    """Runs `claude --print` (Claude Code) with this agent's Anthropic-compatible endpoint, key and model."""
    type = "claude_local"
    label = "Claude Code"

    def describe(self):
        return "claude --print · Claude Code tools"

    def build(self, system, messages, effort=None):
        env = claude_code_routing(self.llm)
        argv = [self.resolve_command("claude"), "--print", "--output-format", "json",
                "--append-system-prompt", system]
        if self.llm.get("model"):
            argv += ["--model", self.llm["model"]]
        effort = effort or self.llm.get("effort")
        if effort:
            argv += ["--effort", effort]
        if self.cfg.get("max_turns"):
            argv += ["--max-turns", str(self.cfg["max_turns"])]
        if self.cfg.get("dangerously_skip_permissions"):
            argv.append("--dangerously-skip-permissions")
        argv += list(self.cfg.get("extra_args") or [])
        prompt = messages[-1]["content"] if len(messages) == 1 else render_prompt("", messages).lstrip("-\n ")
        return argv, env, prompt

    def complete(self, system, messages, max_tokens=None, effort=None):
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
        return text


class Process(Harness):
    """Any command. Gets the prompt on stdin, the LLM settings in env vars, and returns its stdout.

    `args` may use {model} and {base_url}. The API key is only passed in env vars, never on the
    command line.
    """
    type = "process"
    label = "Custom process"

    def describe(self):
        return " ".join([self.cfg.get("command", "?")] + list(self.cfg.get("args") or []))[:40]

    def complete(self, system, messages, max_tokens=None, effort=None):
        if not self.cfg.get("command"):
            raise HarnessError("process: harness.command is required")
        subst = {"model": self.llm.get("model", ""), "base_url": self.llm.get("base_url", "")}
        argv = [self.resolve_command(self.cfg["command"])]
        argv += [str(a).format(**subst) for a in self.cfg.get("args") or []]
        env = generic_routing(self.llm)
        env["BABD_AGENT_ID"] = self.agent_id
        env["BABD_SYSTEM_PROMPT"] = system
        text = self.run_process(argv, env, stdin_text=render_prompt(system, messages)).strip()
        if not text:
            raise HarnessError(f"process {self.cfg['command']}: empty output")
        return text
