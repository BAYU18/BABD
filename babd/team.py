"""AI development team: agents built from agents.json, orchestrated by the Team Lead."""
from .config import load_skill_text
from .flow import Run, extract_json  # noqa: F401  (extract_json re-exported for callers)
from .harness import create_harness


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg.get("short_name") or cfg["name"]
        self.harness = create_harness(cfg)
        self.history = []

    @property
    def main_task(self):
        return " ".join(self.cfg["main_task"]).title()

    def system_prompt(self):
        c = self.cfg
        subs = ", ".join(s["name"] for s in c["sub_tasks"])
        lines = [
            f"You are the {c['name'].title()} of an AI software development team. "
            "A human CEO supervises the team through the Team Lead.",
            f"Your main task: {self.main_task}.",
            f"Your sub-tasks: {subs}.",
        ]
        if c.get("skills"):
            lines.append(f"Your skills: {', '.join(c['skills'])}.")
        for skill in c.get("skills", []):
            text = load_skill_text(skill)
            if text:
                lines.append(f"\n## Skill: {skill}\n{text}")
        lines.append("\nWork concretely: produce the actual design, code, tests or steps, not a description "
                     "of what you would do. Say plainly what is still missing or blocked.")
        return "\n".join(lines)

    def ask(self, message, **kwargs):
        """One-off request with no memory."""
        return self.harness.complete(self.system_prompt(), [{"role": "user", "content": message}], **kwargs)

    def chat(self, message):
        """Multi-turn conversation: keeps this agent's history."""
        self.history.append({"role": "user", "content": message})
        reply = self.harness.complete(self.system_prompt(), self.history)
        self.history.append({"role": "assistant", "content": reply})
        return reply


class Team:
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.agents = [Agent(a) for a in cfg["agents"]]
        self.lead, self.specialists = self.agents[0], self.agents[1:]
        self.by_id = {a.id: a for a in self.agents}
        self.log = log

    def check(self):
        """Ping every agent through its harness. Returns {agent_id: (ok, reply_or_error)}."""
        results = {}
        for a in self.agents:
            try:
                reply = a.ask("Reply with exactly: OK", max_tokens=1024, effort="low")
                results[a.id] = (True, reply)
            except Exception as e:  # report every failure, keep checking the others
                results[a.id] = (False, str(e))
        return results

    def run(self, goal, approver=None, on_event=None, run_id=None):
        """Run the team flow (see babd/flow.py) on a goal. Returns the final run state."""
        return Run(self, goal, approver=approver, on_event=on_event, run_id=run_id).execute()


DASHBOARD_FIELDS = ["status", "progress", "current_goal", "active_task", "approval_needed", "blockers",
                    "recent_result", "next_action"]


def apply_report_to_dashboard(cfg, report):
    """Copy the CEO report's dashboard fields into cfg['project'] (only fields that are present)."""
    project = cfg["project"]
    for k in DASHBOARD_FIELDS:
        if k in report and report[k] not in (None, ""):
            project[k] = report[k]
    if "progress" in project:
        try:
            project["progress"] = max(0, min(100, int(project["progress"])))
        except (TypeError, ValueError):
            project["progress"] = 0
    for k in ("approval_needed", "blockers"):
        try:
            project[k] = int(project[k])
        except (TypeError, ValueError):
            project[k] = 0
    project["status"] = str(project.get("status", "ACTIVE")).upper()
    return cfg


def apply_run_to_config(cfg, state):
    """After a run: CEO report -> project fields, run stages -> workflow strip, agent states -> cards."""
    if state.get("report"):
        apply_report_to_dashboard(cfg, state["report"])
    stage_of_step = {"PLAN": "plan", "DESIGN": "design", "CODE": "code", "TEST": "test",
                     "DEPLOY": "deploy", "MONITOR": "deploy"}
    for step in cfg.get("workflow", []):
        st = state["stages"].get(stage_of_step.get(step["step"], ""), "todo")
        step["state"] = {"done": "done", "active": "active", "failed": "active"}.get(st, "todo")
    for a in cfg["agents"]:
        s = state["agents"].get(a["id"], {}).get("status", "idle")
        a["status"] = {"done": "idle", "working": "working"}.get(s, s)
        if s == "done":
            for sub in a["sub_tasks"]:
                sub["state"] = "done"
    return cfg
