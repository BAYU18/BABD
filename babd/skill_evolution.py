"""Skill evolution: track which skills each agent actually uses, and adapt what gets loaded.

Two goals, both about saving tokens and getting better results over time:

1. **Progressive loading.** Instead of injecting the FULL text of every applicable skill into every
   step, BABD injects a compact catalog (name + when-to-use + path). The agent loads a skill's full
   text on demand with its file tool. This is the same trick a human uses: skim the shelf, pull one
   book when needed.

2. **Evolution.** Every step records which skills were *loaded* (named in the prompt or fetched by
   the agent) and which were *applied* (named in the "Skills applied:" section). Skills applied
   often rise; skills never applied sink into the compact catalog and eventually go dormant. Dormant
   skills are dropped from the catalog to save even the name line.

State lives in `.babd/skills-usage.json`, one entry per (agent, skill):
    { "uses": N, "applied": N, "last_used": ISO, "last_applied": ISO, "misses": N }

A skill is dormant for an agent when it has been offered at least DORMANT_MIN_OFFERS times and
applied at most DORMANT_MAX_APPLIED of them. Dormant skills are excluded from the catalog but can
still be named in the task ("use <skill>") — the agent just won't be nudged toward them.
"""
import json
import os
import re
import time

from .config import ROOT

DEFAULT_STATE_PATH = os.path.join(ROOT, ".babd", "skills-usage.json")
STATE_PATH = DEFAULT_STATE_PATH


def _path():
    """Where the usage store lives. Kept as a function so tests can point it at a temp file."""
    return STATE_PATH

# Tunables (kept small on purpose: the whole point is a short catalog).
DORMANT_MIN_OFFERS = 8      # offered at least this many times...
DORMANT_MAX_APPLIED = 0     # ...and never applied -> dormant
HOT_MIN_APPLIED = 2         # applied this many times -> hot, listed first
CATALOG_MAX_LINES = 40      # hard cap on catalog lines per agent (token ceiling)

# Alias: how many offers with no application make a skill dormant (the classic name for the rule).
DORMANT_AFTER = DORMANT_MIN_OFFERS


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"agents": {}}


def _save(state):
    target = _path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, target)


def _key(agent_id, skill):
    return f"{agent_id}::{skill}"


def record(agent_id, skills, applied=(), kind=""):
    """Record one step: `skills` were offered/loaded, `applied` of them were accounted for."""
    if not skills:
        return
    state = _load()
    bucket = state.setdefault("agents", {}).setdefault(agent_id, {})
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    applied_set = set(applied or ())
    for s in skills:
        entry = bucket.setdefault(s, {"uses": 0, "applied": 0, "misses": 0})
        entry["uses"] = entry.get("uses", 0) + 1
        entry["last_used"] = now
        if s in applied_set:
            entry["applied"] = entry.get("applied", 0) + 1
            entry["last_applied"] = now
        else:
            entry["misses"] = entry.get("misses", 0) + 1
        if kind:
            by_kind = entry.setdefault("kinds", {})
            by_kind[kind] = by_kind.get(kind, 0) + 1
    _save(state)


def entry(agent_id, skill):
    return _load().get("agents", {}).get(agent_id, {}).get(skill, {})


def reliability(agent_id, skill):
    """How often this skill was applied when offered: applied/uses in [0, 1].

    None when the skill has never been offered to this agent (no signal yet).
    """
    e = entry(agent_id, skill)
    uses = e.get("uses", 0)
    if not uses:
        return None
    return e.get("applied", 0) / uses


def is_dormant(agent_id, skill):
    e = entry(agent_id, skill)
    return e.get("uses", 0) >= DORMANT_MIN_OFFERS and e.get("applied", 0) <= DORMANT_MAX_APPLIED


def is_hot(agent_id, skill):
    return entry(agent_id, skill).get("applied", 0) >= HOT_MIN_APPLIED


def rank(agent_id, names):
    """Order skill names: hot first (most applied), then by applied count, then original order."""
    def key(n):
        e = entry(agent_id, n)
        hot = 1 if is_hot(agent_id, n) else 0
        return (-hot, -e.get("applied", 0), -e.get("uses", 0))
    return sorted(names, key=key)


def summary(agent_id):
    """(offered, applied, dormant) counts for the dashboard / reports."""
    bucket = _load().get("agents", {}).get(agent_id, {})
    offered = len(bucket)
    applied = sum(1 for e in bucket.values() if e.get("applied", 0) > 0)
    dormant = sum(1 for s in bucket if is_dormant(agent_id, s))
    return {"offered": offered, "applied": applied, "dormant": dormant}


def reset(agent_id=None):
    state = _load()
    if agent_id:
        state.get("agents", {}).pop(agent_id, None)
    else:
        state = {"agents": {}}
    _save(state)
