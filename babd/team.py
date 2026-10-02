"""AI development team: agents built from agents.json, orchestrated by the Team Lead."""
import datetime
import json
import os
import re

from .config import ROOT, load_skill_text
from .llm import LLMClient

RUNS_DIR = os.path.join(ROOT, "runs")


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg.get("short_name") or cfg["name"]
        self.llm = LLMClient(cfg["llm"])
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
        return self.llm.complete(self.system_prompt(), [{"role": "user", "content": message}], **kwargs)

    def chat(self, message):
        """Multi-turn conversation: keeps this agent's history."""
        self.history.append({"role": "user", "content": message})
        reply = self.llm.complete(self.system_prompt(), self.history)
        self.history.append({"role": "assistant", "content": reply})
        return reply


def extract_json(text):
    """Parse the first JSON object in a model reply (tolerates ```json fences and surrounding prose)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class Team:
    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.agents = [Agent(a) for a in cfg["agents"]]
        self.lead, self.specialists = self.agents[0], self.agents[1:]
        self.by_id = {a.id: a for a in self.agents}
        self.log = log

    def check(self):
        """Ping every agent's LLM. Returns {agent_id: (ok, reply_or_error)}."""
        results = {}
        for a in self.agents:
            try:
                reply = a.ask("Reply with exactly: OK", max_tokens=1024, effort="low")
                results[a.id] = (True, reply)
            except Exception as e:  # report every failure, keep checking the others
                results[a.id] = (False, str(e))
        return results

    def run(self, goal):
        """Plan -> each specialist works in order -> CEO report. Saves everything under runs/."""
        run_dir = os.path.join(RUNS_DIR, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)

        def save(name, content):
            with open(os.path.join(run_dir, name), "w") as f:
                f.write(content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False))

        team_desc = "\n".join(
            f"- {a.id}: {a.name} - main task {a.main_task}; skills: {', '.join(a.cfg.get('skills', []))}"
            for a in self.specialists)
        ids = ", ".join(f'"{a.id}"' for a in self.specialists)
        slots = ", ".join(f'"{a.id}": "<task>"' for a in self.specialists)

        # 1. Team Lead plans and assigns
        self.log(f"[{self.lead.name}] planning ...")
        plan_text = self.lead.ask(
            f"CEO goal:\n{goal}\n\nYour team:\n{team_desc}\n\n"
            "Plan the work and assign one concrete task to every agent. They work in the order listed, "
            "each seeing the previous agents' output.\n"
            "Answer with only a JSON object:\n"
            '{"plan_summary": "<2-4 sentences>", "assignments": {' + slots + '}}\n'
            f"The assignments object must have exactly these keys: {ids}.")
        plan = extract_json(plan_text) or {}
        assignments = plan.get("assignments")
        if not isinstance(assignments, dict):
            assignments = {}
        save("01-plan.md", plan_text)

        # 2. Specialists work in order, each seeing the plan and earlier outputs
        outputs = {}
        for i, a in enumerate(self.specialists, start=2):
            task = str(assignments.get(a.id) or "") or f"Do your part ({a.main_task}) for the goal, following this plan:\n{plan_text}"
            self.log(f"[{a.name}] {task[:90]}{'...' if len(task) > 90 else ''}")
            previous = "\n\n".join(f"### Output from {self.by_id[k].name}\n{v}" for k, v in outputs.items())
            msg = (f"CEO goal:\n{goal}\n\nTeam Lead plan:\n{plan.get('plan_summary', plan_text)}\n\n"
                   f"Your assignment:\n{task}")
            if previous:
                msg += f"\n\nWork already done by the team:\n\n{previous}"
            outputs[a.id] = a.ask(msg)
            save(f"{i:02d}-{a.id}.md", outputs[a.id])

        # 3. Team Lead reports to the CEO
        self.log(f"[{self.lead.name}] writing the CEO report ...")
        all_out = "\n\n".join(f"### {self.by_id[k].name}\n{v}" for k, v in outputs.items())
        report_text = self.lead.ask(
            f"CEO goal:\n{goal}\n\nTeam output:\n\n{all_out}\n\n"
            "Write the CEO report. The CEO wants high-level status only, no code. "
            "Answer with only a JSON object:\n"
            '{"status": "ACTIVE|BLOCKED|DONE", "progress": <0-100>, "current_goal": "<max 4 words>", '
            '"active_task": "<max 3 words>", "approval_needed": <int>, "blockers": <int>, '
            '"recent_result": "<max 4 words>", "next_action": "<max 4 words>", '
            '"summary": "<short paragraph for the CEO>", "approvals": ["<what the CEO must approve>"], '
            '"blocker_list": ["<blocker>"]}')
        report = extract_json(report_text) or {"summary": report_text}
        save("99-ceo-report.json", report)
        save("99-ceo-report.md", report.get("summary", report_text))
        return {"dir": run_dir, "plan": plan, "plan_text": plan_text, "outputs": outputs, "report": report}


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
