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


def create_harness(agent_cfg):
    kind = harness_config(agent_cfg).get("type", "direct")
    cls = HARNESSES.get(kind)
    if not cls:
        raise HarnessError(f"agent {agent_cfg['id']}: unknown harness {kind!r} (known: {', '.join(HARNESSES)})")
    return cls(agent_cfg)


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


__all__ = ["HARNESSES", "Harness", "HarnessError", "create_harness", "register_harness", "select_harness"]
