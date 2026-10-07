"""Skill packs: sets of vendored skills (skills/<pack>/<skill>/SKILL.md) that run locally and are always used.

Two packs ship with BABD: Superpowers (babd/superpowers.py) and Matt Pocock's skills (babd/mattpocock.py).
Each pack says which skills it recommends for which agent (`recommended`, also the default when
agents.json has no list for the agent) and which skills apply to which step of the team flow (`steps`).
An agent's list for a pack lives in agents.json under the pack's key (`superpowers`, `mattpocock`).

Always used, enforced by BABD rather than left to the model:

  * every agent's system prompt carries the rule and the catalog of its skills;
  * every step of a team run gets the FULL text of the agent's skills that apply to that step, plus
    each pack's ADAPTATION.md (how the skills map onto this team);
  * the answer must end with "Skills applied:" naming each of those skills; if one is missing, the
    agent is asked once to redo the step (when the pack's `enforce` is on), and the result is recorded;
  * agents with native skill support also get the files: Hermes in HERMES_HOME/skills/<pack>/,
    Claude Code in its private config dir's skills/ (only when BABD owns that dir).
"""
import os
import re
import shutil

from .config import ROOT

ADAPTATION = "ADAPTATION.md"

# Skills (free-text, agents.json `skills`) each role should list: shown as recommended in the dashboard.
GENERAL_RECOMMENDED = {
    "lead": ["GBrain", "Planning", "Task Routing", "Reporting"],
    "architect": ["GBrain", "System Design", "Web Research", "Diagrams"],
    "developer": ["GBrain", "Python", "TypeScript", "Git"],
    "qa": ["GBrain", "Unit Tests", "E2E Tests", "Bug Triage"],
    "devops": ["GBrain", "Docker", "CI/CD", "Monitoring"],
}
_FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


class SkillError(Exception):
    pass


class Pack:
    def __init__(self, key, title, source, url, recommended, steps, why, plain, optional=None):
        self.key = key                  # agents.json field and project setting name
        self.title = title
        self.source = source            # "owner/repo"
        self.url = url
        self.dir = os.path.join(ROOT, "skills", key)
        self.recommended = recommended  # agent id -> skills that agent needs
        self.steps = steps              # flow step -> skills that apply to it
        self.why = why                  # skill -> one technical line
        self.plain = plain              # skill -> what it does for you, in plain words
        self.optional = optional or {}  # skill -> why no agent gets it by default

    def skill_names(self):
        if not os.path.isdir(self.dir):
            return []
        return sorted(d for d in os.listdir(self.dir) if os.path.isfile(os.path.join(self.dir, d, "SKILL.md")))

    def load(self, name):
        """(meta, body) of a skill. meta has name and description from the frontmatter."""
        path = os.path.join(self.dir, name, "SKILL.md")
        if not os.path.isfile(path):
            raise SkillError(f"{self.key} skill {name!r} not found in {os.path.relpath(self.dir, ROOT)}")
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

    def catalog(self):
        return [{**self.load(n)[0], "why": self.why.get(n, ""), "plain": self.plain.get(n, ""),
                 "optional": self.optional.get(n, ""),
                 "steps": [k for k, v in self.steps.items() if n in v]} for n in self.skill_names()]

    def enabled(self, project_cfg):
        return (project_cfg or {}).get(self.key, {}).get("enabled", True) and bool(self.skill_names())

    def enforce(self, project_cfg):
        return (project_cfg or {}).get(self.key, {}).get("enforce", True)

    def assigned(self, agent_cfg):
        """The agent's skills: its list in agents.json, or the ones recommended for its role."""
        names = agent_cfg.get(self.key)
        if names is None:
            names = self.recommended.get(agent_cfg.get("id"), [])
        known = self.skill_names()
        return [n for n in names if n in known]

    def for_step(self, agent_cfg, kind):
        """Skills of this pack the agent must use on this step, in the step's order."""
        mine = set(self.assigned(agent_cfg))
        return [n for n in self.steps.get(kind, []) if n in mine]

    def adaptation(self):
        path = os.path.join(self.dir, ADAPTATION)
        if not os.path.isfile(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read().strip()


def packs():
    from . import mattpocock, superpowers
    return [superpowers.PACK, mattpocock.PACK]


def get(key):
    for p in packs():
        if p.key == key:
            return p
    raise SkillError(f"unknown skill pack {key!r}")


def pack_of(name):
    for p in packs():
        if name in p.skill_names():
            return p
    raise SkillError(f"skill {name!r} is in no skill pack")


def agent_skills(agent_cfg, project_cfg=None):
    """{pack key: skill names} of the agent, for the packs that are enabled."""
    return {p.key: p.assigned(agent_cfg) for p in packs() if p.enabled(project_cfg)}


def all_names(skills_by_pack):
    return [n for names in skills_by_pack.values() for n in names]


def for_step(skills_by_pack, kind):
    """All skills the agent must use on this step, pack by pack."""
    out = []
    for p in packs():
        if p.key in skills_by_pack:
            out += p.for_step({p.key: skills_by_pack[p.key]}, kind)
    return out


def recommended(agent_id):
    """{pack key: skills recommended for this agent}."""
    return {p.key: [n for n in p.recommended.get(agent_id, []) if n in p.skill_names()] for p in packs()}


def recommendation_status(agent_cfg):
    """How the agent's skills compare with what is recommended for its role (all packs, enabled or not)."""
    out = {"packs": {}, "recommended": 0, "have": 0}
    for p in packs():
        rec = [n for n in p.recommended.get(agent_cfg.get("id"), []) if n in p.skill_names()]
        mine = p.assigned(agent_cfg)
        out["packs"][p.key] = {"recommended": rec, "missing": [n for n in rec if n not in mine],
                               "extra": [n for n in mine if n not in rec]}
    general = GENERAL_RECOMMENDED.get(agent_cfg.get("id"), [])
    listed = {s.lower() for s in agent_cfg.get("skills", [])}
    out["general"] = {"recommended": general, "missing": [n for n in general if n.lower() not in listed]}
    for part in list(out["packs"].values()) + [out["general"]]:
        out["recommended"] += len(part["recommended"])
        out["have"] += len(part["recommended"]) - len(part["missing"])
    return out


def system_section(skills_by_pack):
    """The always-on part of the system prompt: the rule and the agent's catalog, pack by pack."""
    if not all_names(skills_by_pack):
        return ""
    lines = ["## Skills (always on)",
             "You have these skills. If there is even a small chance one applies to what you are doing, "
             "use it: announce \"Using <skill> to <purpose>\" and follow it exactly. Process skills "
             "(brainstorming, grilling, debugging) come first, then implementation skills."]
    for p in packs():
        names = skills_by_pack.get(p.key) or []
        if names:
            lines.append(f"\n### {p.title} ({p.source})")
            lines += [f"- {n}: {p.load(n)[0]['description']}" for n in names]
    return "\n".join(lines)


LEAN_CHARS = 1500


def lean_text(body, path):
    """The start of a skill (its core rules come first), cut at a paragraph, plus where the rest is."""
    if len(body) <= LEAN_CHARS:
        return body
    cut = body.rfind("\n\n", 0, LEAN_CHARS)
    return body[:cut if cut > 400 else LEAN_CHARS].rstrip() + f"\n\n[... the rest of this skill is in {path}]"


def step_block(names, lean=False):
    """Prompt section for one step: each pack's adaptation notes and the text of each skill (in full, or
    with `lean` (project.skills_mode "lean") only its start, to save tokens)."""
    if not names:
        return ""
    parts = [f"# Skills you must use for this step: {', '.join(names)}"]
    for p in packs():
        mine = [n for n in names if n in p.skill_names()]
        if not mine:
            continue
        parts.append(p.adaptation())
        for n in mine:
            path = f"skills/{p.key}/{n}/SKILL.md"
            body = p.load(n)[1]
            parts.append(f"<skill name=\"{n}\" pack=\"{p.source}\" path=\"{path}\">\n"
                         f"{lean_text(body, path) if lean else body}\n</skill>")
    parts.append("**End your answer with a section** `Skills applied:` **with one line for each of: "
                 f"{', '.join(names)}** (`- <skill-name>: <what you did that this skill requires>`). "
                 "BABD checks this section.")
    return "\n\n".join(parts)


def missing(output, names):
    """Skills not accounted for in the answer's "Skills applied:" section."""
    m = re.search(r"skills applied\s*:?(.*)\Z", output or "", re.I | re.S)
    section = m.group(1).lower() if m else ""
    return [n for n in names if not re.search(rf"(?<![\w-]){re.escape(n.lower())}(?![\w-])", section)]


def enforced(project_cfg, names):
    """The names whose pack asks for a redo when they are skipped."""
    return [n for n in names if pack_of(n).enforce(project_cfg)]


def install_native(names, dest):
    """Copy skill folders (from any pack) into a harness's skills dir (dest/<name>), dropping skills
    there that the agent no longer has. Returns the names copied."""
    os.makedirs(dest, exist_ok=True)
    keep = set(names)
    for existing in os.listdir(dest):
        if existing not in keep and os.path.isfile(os.path.join(dest, existing, "SKILL.md")):
            shutil.rmtree(os.path.join(dest, existing))
    for n in names:
        target = os.path.join(dest, n)
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(pack_of(n).dir, n), target)
    return list(names)
