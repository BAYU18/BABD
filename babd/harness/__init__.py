"""Harness registry. Each agent picks one with `"harness": {"type": ...}` in agents.json.

Like Paperclip's adapter registry, new harnesses can be added at runtime with register_harness().
"""
from .base import Harness, HarnessError, harness_config
from .hermes import HermesGateway, HermesLocal
from .others import ClaudeCode, Direct, Process

HARNESSES = {}


def register_harness(cls):
    HARNESSES[cls.type] = cls
    return cls


for _cls in (Direct, HermesLocal, HermesGateway, ClaudeCode, Process):
    register_harness(_cls)


def create_harness(agent_cfg, project=None):
    """The agent's harness. With `project`, it also knows the agent's Superpowers skills (setup copies
    them into harnesses that load skills natively)."""
    kind = harness_config(agent_cfg).get("type", "direct")
    cls = HARNESSES.get(kind)
    if not cls:
        raise HarnessError(f"agent {agent_cfg['id']}: unknown harness {kind!r} (known: {', '.join(HARNESSES)})")
    h = cls(agent_cfg)
    if project is not None:
        from .. import superpowers
        h.superpowers = superpowers.assigned(agent_cfg) if superpowers.enabled(project) else []
    return h


# Option fields per harness for the dashboard's config form: (key, type, help).
HARNESS_OPTIONS = {
    "direct": [],
    "hermes_local": [
        ("toolsets", "list", "Hermes toolsets, e.g. terminal, file, web"),
        ("skills", "list", "Hermes-native skills to preload"),
        ("max_turns", "number", "Max tool-calling iterations"),
        ("timeout_sec", "number", "Stop a run after this many seconds"),
        ("yolo", "bool", "Skip dangerous-command approvals (only inside a sandbox)"),
        ("version", "text", "Pin the hermes-agent version to install"),
        ("auto_install", "bool", "Install Hermes automatically when missing"),
        ("command", "text", "Use this hermes program instead"),
    ],
    "hermes_gateway": [
        ("api_base_url", "text", "Existing Hermes server URL. Empty = start a private local gateway"),
        ("api_key_env", "text", "Env var with that server's API key"),
        ("send_model", "bool", "Send this agent's model with each run"),
        ("port", "number", "Port for the auto-started gateway (empty = any free port)"),
        ("timeout_sec", "number", "Stop a run after this many seconds"),
        ("version", "text", "Pin the hermes-agent version to install"),
    ],
    "claude_local": [
        ("max_turns", "number", "Max agent turns"),
        ("timeout_sec", "number", "Stop a run after this many seconds"),
        ("dangerously_skip_permissions", "bool", "Skip permission checks (only inside a sandbox)"),
        ("isolated_config", "bool", "Private Claude Code config dir (default: on when the agent has its own key)"),
        ("version", "text", "Pin the Claude Code version to install"),
        ("command", "text", "Use this claude program instead"),
    ],
    "process": [
        ("command", "text", "Program to run (prompt on stdin, reply on stdout)"),
        ("args", "list", "Arguments; {model} and {base_url} are filled in"),
        ("install", "text", "Command run once to install the program"),
        ("timeout_sec", "number", "Stop a run after this many seconds"),
    ],
}


def select_harness(agent_cfg, kind, overrides=None):
    """Point an agent at harness `kind`: keeps its options when the type is unchanged, otherwise
    starts from that harness's defaults. Applies `overrides`. Edits agent_cfg in place."""
    cls = HARNESSES.get(kind)
    if not cls:
        raise HarnessError(f"unknown harness {kind!r} (known: {', '.join(HARNESSES)})")
    current = harness_config(agent_cfg)
    new = current if current.get("type") == kind else {"type": kind, **cls.defaults}
    new.update(overrides or {})
    agent_cfg["harness"] = new
    return new


__all__ = ["HARNESS_OPTIONS", "HARNESSES", "Harness", "HarnessError", "create_harness", "register_harness", "select_harness"]
