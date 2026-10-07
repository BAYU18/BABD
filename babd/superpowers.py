"""Superpowers skills (https://github.com/obra/superpowers), vendored in skills/superpowers and run locally.

Each agent gets the skills that fit its role (`superpowers` in agents.json, defaults below). They are
always used, enforced by BABD rather than left to the model:

  * every agent's system prompt carries the using-superpowers rule and the catalog of its skills;
  * every step of a team run gets the FULL text of the agent's skills that apply to that step
    (STEP_SKILLS), plus ADAPTATION.md (how the skills map onto this team);
  * the answer must end with "Skills applied:" naming each of those skills; if one is missing, the
    agent is asked once to redo the step following it, and the result is recorded in the run;
  * agents with native skill support also get the files: Hermes in HERMES_HOME/skills/superpowers,
    Claude Code in its private config dir's skills/ (only when BABD owns that dir).
"""
import os
import re
import shutil

from .config import ROOT

SKILLS_DIR = os.path.join(ROOT, "skills", "superpowers")
ADAPTATION = "ADAPTATION.md"

# Which skills fit which agent (used when agents.json has no `superpowers` list for an agent).
DEFAULT_ASSIGNMENT = {
    "lead": ["using-superpowers", "brainstorming", "writing-plans", "subagent-driven-development",
             "dispatching-parallel-agents", "requesting-code-review", "verification-before-completion",
             "finishing-a-development-branch", "diagnosing-superpowers", "writing-skills"],
    "architect": ["using-superpowers", "brainstorming", "writing-plans", "dispatching-parallel-agents"],
    "developer": ["using-superpowers", "test-driven-development", "executing-plans", "systematic-debugging",
                  "receiving-code-review", "verification-before-completion", "using-git-worktrees"],
    "qa": ["using-superpowers", "test-driven-development", "systematic-debugging", "requesting-code-review",
           "verification-before-completion"],
    "devops": ["using-superpowers", "verification-before-completion", "finishing-a-development-branch",
               "using-git-worktrees", "systematic-debugging"],
}

# Which skills apply to which step of the team flow (a step uses those the agent has).
STEP_SKILLS = {
    "plan": ["brainstorming", "writing-plans", "subagent-driven-development", "dispatching-parallel-agents"],
    "design": ["brainstorming", "writing-plans"],
    "code": ["test-driven-development", "executing-plans", "using-git-worktrees", "verification-before-completion"],
    "test_report": ["test-driven-development", "systematic-debugging", "requesting-code-review",
                    "verification-before-completion"],
    "fix": ["systematic-debugging", "receiving-code-review", "test-driven-development",
            "verification-before-completion"],
    "deploy_report": ["verification-before-completion", "finishing-a-development-branch", "using-git-worktrees"],
    "report": ["verification-before-completion", "finishing-a-development-branch"],
    "report_blocked": ["verification-before-completion", "diagnosing-superpowers"],
}

WHY = {  # one line per agent/skill pair, shown in the dashboard
    "using-superpowers": "the rule: check for and use a matching skill before any action",
    "brainstorming": "clarify intent, constraints and alternatives before any design or code",
    "writing-plans": "turn the design into bite-sized, testable tasks with exact files and tests",
    "subagent-driven-development": "hand each task to the right agent with a precise brief, review each result",
    "dispatching-parallel-agents": "split independent work so it can proceed in parallel",
    "requesting-code-review": "review work against the requirements, issues by severity",
    "receiving-code-review": "verify review findings technically before changing code",
    "test-driven-development": "red-green-refactor: a failing test before any production code",
    "systematic-debugging": "root cause first, no fixes by guessing",
    "verification-before-completion": "no success claim without fresh evidence",
    "executing-plans": "execute the plan task by task, each proven by a test",
    "using-git-worktrees": "work in an isolated workspace / branch",
    "finishing-a-development-branch": "tests green, then merge / PR / keep / discard",
    "diagnosing-superpowers": "find out with evidence why a run went wrong",
    "writing-skills": "create or edit team skills, tested like code",
}

_FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


class SuperpowersError(Exception):
    pass


def skill_names():
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(d for d in os.listdir(SKILLS_DIR) if os.path.isfile(os.path.join(SKILLS_DIR, d, "SKILL.md")))


def load(name):
    """(meta, body) of a skill. meta has name and description from the frontmatter."""
    path = os.path.join(SKILLS_DIR, name, "SKILL.md")
    if not os.path.isfile(path):
        raise SuperpowersError(f"superpowers skill {name!r} not found in {os.path.relpath(SKILLS_DIR, ROOT)}")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    meta = {"name": name, "description": ""}
    m = _FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip() in ("name", "description"):
                meta[key.strip()] = value.strip().strip('"')
        text = text[m.end():]
    return meta, text.strip()


def catalog():
    return [{**load(n)[0], "why": WHY.get(n, ""),
             "steps": [k for k, v in STEP_SKILLS.items() if n in v]} for n in skill_names()]


def assigned(agent_cfg):
    """The agent's skills: its `superpowers` list, or the default for its role."""
    names = agent_cfg.get("superpowers")
    if names is None:
        names = DEFAULT_ASSIGNMENT.get(agent_cfg.get("id"), ["using-superpowers"])
    return [n for n in names if n in skill_names()]


def enabled(project_cfg):
    return (project_cfg or {}).get("superpowers", {}).get("enabled", True) and bool(skill_names())


def for_step(agent_cfg, kind):
    """Skills the agent must use on this step, in the step's order."""
    mine = set(assigned(agent_cfg))
    return [n for n in STEP_SKILLS.get(kind, []) if n in mine]


def system_section(agent_cfg):
    """The always-on part of the system prompt: the rule and the agent's catalog."""
    names = assigned(agent_cfg)
    if not names:
        return ""
    lines = ["## Superpowers skills (always on)",
             "You have these skills. If there is even a small chance one applies to what you are doing, "
             "use it: announce \"Using <skill> to <purpose>\" and follow it exactly. Process skills "
             "(brainstorming, systematic-debugging) come first, then implementation skills."]
    for n in names:
        lines.append(f"- {n}: {load(n)[0]['description']}")
    return "\n".join(lines)


def step_block(names):
    """Prompt section for one step: the adaptation notes and the full text of each skill."""
    if not names:
        return ""
    with open(os.path.join(SKILLS_DIR, ADAPTATION), encoding="utf-8") as f:
        adaptation = f.read().strip()
    parts = [f"# Skills you must use for this step: {', '.join(names)}", adaptation]
    for n in names:
        parts.append(f"<skill name=\"{n}\" path=\"skills/superpowers/{n}/SKILL.md\">\n{load(n)[1]}\n</skill>")
    return "\n\n".join(parts)


def missing(output, names):
    """Skills not accounted for in the answer's "Skills applied:" section."""
    m = re.search(r"skills applied\s*:?(.*)\Z", output or "", re.I | re.S)
    section = m.group(1).lower() if m else ""
    return [n for n in names if n.lower() not in section]


def install_native(names, dest):
    """Copy skill folders into a harness's skills dir (dest/<name>). Returns the names copied."""
    os.makedirs(dest, exist_ok=True)
    keep = set(names)
    for existing in os.listdir(dest):  # drop skills this agent no longer has
        if existing not in keep and os.path.isfile(os.path.join(dest, existing, "SKILL.md")):
            shutil.rmtree(os.path.join(dest, existing))
    for n in names:
        target = os.path.join(dest, n)
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(SKILLS_DIR, n), target)
    return list(names)
