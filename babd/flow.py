"""The team's communication flow.

    CEO -> Team Lead                       goal
    Team Lead -> Architect -> Team Lead    design
    Team Lead -> Developer -> Team Lead    code
    Team Lead -> QA -> Team Lead           test report + VERDICT
        (FAIL) Team Lead -> Developer (fix) -> Team Lead -> QA (re-test) ...  up to max_fix_rounds
    Team Lead -> CEO                       approval request before deploy   (project.require_approval)
    Team Lead -> DevOps -> Team Lead       deploy + monitoring              (only after PASS + approval)
    Team Lead -> CEO                       report

Every message goes through MessageBus.send(), which only allows the routes above: the Team Lead
is the hub, specialists never talk to each other or to the CEO directly.
"""
import datetime
import json
import os
import re
import threading
import time

from .config import ROOT
from . import skillpacks
from .gbrain import one_line, slugify

RUNS_DIR = os.path.join(ROOT, "runs")
ROLES = ("lead", "architect", "developer", "qa", "devops")

ROUTES = {("ceo", "lead"), ("lead", "ceo")} | {(r, "lead") for r in ROLES[1:]} | {("lead", r) for r in ROLES[1:]}

STAGES = [  # (key, label, owner, progress when the stage is finished)
    ("plan", "PLAN", "lead", 10),
    ("design", "DESIGN", "architect", 25),
    ("code", "CODE", "developer", 45),
    ("test", "TEST", "qa", 65),
    ("approval", "APPROVAL", "ceo", 70),
    ("deploy", "DEPLOY", "devops", 90),
    ("report", "REPORT", "lead", 100),
]
STAGE_PROGRESS = {k: p for k, _, _, p in STAGES}
VERDICT_RE = re.compile(r"VERDICT:\s*\**\s*(PASS|FAIL)", re.I)


class FlowError(Exception):
    pass


class FlowCancelled(Exception):
    pass


def extract_json(text):
    """First JSON object in a model reply (tolerates ```json fences and surrounding prose)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def parse_verdict(text):
    """'PASS' / 'FAIL' from QA's last VERDICT line; a missing verdict counts as FAIL."""
    found = VERDICT_RE.findall(text or "")
    return found[-1].upper() if found else "FAIL"


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class MessageBus:
    def __init__(self, emit, run_dir):
        self.messages = []
        self.emit = emit
        self.path = os.path.join(run_dir, "messages.jsonl")

    def send(self, sender, recipient, kind, content, **meta):
        if (sender, recipient) not in ROUTES:
            raise FlowError(f"route {sender} -> {recipient} is not part of the team flow")
        msg = {"seq": len(self.messages) + 1, "at": now(), "from": sender, "to": recipient, "kind": kind,
               "content": content, **meta}
        self.messages.append(msg)
        with open(self.path, "a") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.emit("message", msg)
        return msg


class Run:
    """One team run on a goal. State is plain JSON so the dashboard can show it as-is."""

    def __init__(self, team, goal, approver=None, on_event=None, run_id=None):
        self.team = team
        self.goal = goal
        self.approver = approver           # fn(request_dict) -> (approved: bool, note: str); None = no approver
        self.on_event = on_event or (lambda kind, data: None)
        self.cancelled = threading.Event()
        base = run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.id, n = base, 1
        while os.path.exists(os.path.join(RUNS_DIR, self.id)):  # two runs in the same second
            n += 1
            self.id = f"{base}-{n}"
        self.dir = os.path.join(RUNS_DIR, self.id)
        os.makedirs(self.dir)
        project = team.cfg.get("project", {})
        self.require_approval = project.get("require_approval", ["deploy"])
        self.max_fix_rounds = int(project.get("max_fix_rounds", 2))
        self.state = {
            "id": self.id, "goal": goal, "status": "running", "stage": None, "progress": 0,
            "started_at": now(), "finished_at": None, "error": None, "dir": self.dir,
            "agents": {a.id: {"status": "idle", "task": ""} for a in team.agents},
            "stages": {k: "todo" for k, *_ in STAGES}, "qa_rounds": 0, "verdict": None,
            "approval": None, "deployed": False, "blockers": [], "report": None, "memory": [], "skills": [],
        }
        self.bus = MessageBus(self.emit, self.dir)
        self.state["messages"] = self.bus.messages
        self.steps = 0

    # -- state + events ----------------------------------------------------------------------

    def emit(self, kind, data):
        if kind != "message":
            self.save()
        self.on_event(kind, {"run": self.id, **data} if isinstance(data, dict) else data)

    def save(self):
        state = {k: v for k, v in self.state.items() if k != "messages"}
        with open(os.path.join(self.dir, "state.json"), "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def write(self, name, content):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(content)

    def check_cancel(self):
        if self.cancelled.is_set():
            raise FlowCancelled("run cancelled by the CEO")

    def stage(self, key):
        self.check_cancel()
        for k, state in self.state["stages"].items():
            if state == "active":
                self.state["stages"][k] = "done"
        self.state["stages"][key] = "active"
        self.state["stage"] = key
        self.emit("stage", {"stage": key})

    def finish_stage(self, key, result="done"):
        self.state["stages"][key] = result
        if result == "done" and (key != "report" or self.state["deployed"]):
            self.state["progress"] = max(self.state["progress"], STAGE_PROGRESS[key])
        self.emit("stage", {"stage": key, "result": result})

    def agent(self, agent_id, status, task=None):
        a = self.state["agents"][agent_id]
        a["status"] = status
        if task is not None:
            a["task"] = task
        self.emit("agent", {"agent": agent_id, **a})

    # -- one agent step, always through the GBrain cycle (read -> work -> write) ---------------

    def work(self, agent_id, prompt, task, kind, fact=None, skills_for=None):
        agent = self.team.by_id[agent_id]
        skills = skillpacks.for_step(agent.skill_packs, skills_for or kind)

        def on_skills(entry):
            entry = {**entry, "after_seq": len(self.bus.messages), "kind": kind}
            self.state["skills"].append(entry)
            self.emit("skills", entry)
        self.steps += 1
        goal_short = one_line(self.goal, 80)

        def default_fact(out):
            return f"{agent.name} ({kind}) for '{goal_short}': {one_line(out, 220)}"

        def on_memory(entry):
            entry = {**entry, "after_seq": len(self.bus.messages), "kind": kind}
            self.state["memory"].append(entry)
            self.emit("memory", entry)

        return agent.work(prompt, query=(self.goal, task), task=task, page_title=f"{agent.name} · {kind} · {goal_short}",
                          page_slug=f"babd/runs/{self.id}/{self.steps:02d}-{agent_id}-{kind}",
                          entity=f"babd/goals/{slugify(self.goal)}",
                          provenance=f"babd run {self.id} · {agent.name} · {kind}",
                          fact=fact or default_fact, on_memory=on_memory, skills=skills, on_skills=on_skills)

    # -- one exchange: Team Lead -> agent -> Team Lead -----------------------------------------

    def delegate(self, agent_id, kind, task, prompt, reply_kind):
        """Lead sends `task` to an agent, the agent works on `prompt`, and reports back to the lead."""
        self.check_cancel()
        self.bus.send("lead", agent_id, kind, task)
        self.agent(agent_id, "working", task)
        started = time.monotonic()
        try:
            fact = None
            if reply_kind == "test_report":
                fact = (lambda o: f"QA verdict {parse_verdict(o)} for '{one_line(self.goal, 80)}': {one_line(o, 200)}")
            out = self.work(agent_id, prompt, task, reply_kind, fact=fact)
        except Exception:
            self.agent(agent_id, "blocked")
            raise
        self.bus.send(agent_id, "lead", reply_kind, out, seconds=round(time.monotonic() - started, 1))
        self.agent(agent_id, "done")
        return out

    # -- the flow ----------------------------------------------------------------------------

    def execute(self):
        try:
            self._flow()
            self.state["status"] = "done"
        except FlowCancelled as e:
            self.state["status"] = "cancelled"
            self.state["error"] = str(e)
        except Exception as e:  # any agent / harness failure ends the run with a clear error
            self.state["status"] = "failed"
            self.state["error"] = f"{type(e).__name__}: {e}"
        self.state["finished_at"] = now()
        self.emit("finished", {"status": self.state["status"], "error": self.state["error"],
                               "report": self.state["report"]})
        return self.state

    def _flow(self):
        team, goal = self.team, self.goal
        missing = [r for r in ROLES if r not in team.by_id]
        if missing:
            raise FlowError(f"agents.json needs agents with these ids: {', '.join(missing)}")
        names = {a.id: a.name for a in team.agents}
        self.emit("started", {"goal": goal})
        self.bus.send("ceo", "lead", "goal", goal)

        # PLAN
        self.stage("plan")
        self.agent("lead", "working", "Plan work and assign agents")
        specialists = ROLES[1:]
        team_desc = "\n".join(f"- {r}: {names[r]} - main task {team.by_id[r].main_task}; skills: "
                              f"{', '.join(team.by_id[r].cfg.get('skills', []))}" for r in specialists)
        slots = ", ".join(f'"{r}": "<task>"' for r in specialists)
        plan_text = self.work("lead",
            f"CEO goal:\n{goal}\n\nYour team:\n{team_desc}\n\n"
            "The work flows through you: Architect designs, Developer builds, QA tests (failed tests go back "
            "to the Developer), DevOps deploys and sets up monitoring after QA passes and the CEO approves.\n"
            "Plan the work and assign one concrete task to every agent. Answer with only a JSON object:\n"
            '{"plan_summary": "<2-4 sentences>", "assignments": {' + slots + "}}",
            "Plan the work and assign agents", "plan",
            fact=lambda out: f"Team Lead plan for '{one_line(goal, 80)}': "
                             f"{one_line((extract_json(out) or {}).get('plan_summary') or out, 240)}")
        plan = extract_json(plan_text) or {}
        assignments = plan.get("assignments") if isinstance(plan.get("assignments"), dict) else {}
        summary = plan.get("plan_summary") or plan_text
        self.write("01-plan.md", plan_text)
        self.agent("lead", "working", "Coordinate results")
        self.finish_stage("plan")

        def task_for(role):
            return str(assignments.get(role) or "") or f"Do your part ({team.by_id[role].main_task}) for the goal."

        context = f"CEO goal:\n{goal}\n\nTeam Lead plan:\n{summary}"

        # DESIGN
        self.stage("design")
        design = self.delegate("architect", "assign", task_for("architect"),
                               f"{context}\n\nYour assignment:\n{task_for('architect')}", "design")
        self.write("02-architect.md", design)
        self.finish_stage("design")

        # CODE
        self.stage("code")
        code = self.delegate("developer", "assign", task_for("developer"),
                             f"{context}\n\nYour assignment:\n{task_for('developer')}\n\n"
                             f"### Design from {names['architect']}\n{design}", "code")
        self.write("03-developer.md", code)
        self.finish_stage("code")

        # TEST, with the fix loop
        self.stage("test")
        qa_instr = ("\n\nTest the work against the goal and the design. List every bug you find. "
                    "End your answer with exactly one line: VERDICT: PASS or VERDICT: FAIL")
        report = self.delegate("qa", "assign", task_for("qa"),
                               f"{context}\n\nYour assignment:\n{task_for('qa')}\n\n### Design\n{design}\n\n"
                               f"### Code from {names['developer']}\n{code}{qa_instr}", "test_report")
        verdict = parse_verdict(report)
        self.write("04-qa-round0.md", report)
        rounds = 0
        while verdict == "FAIL" and rounds < self.max_fix_rounds:
            rounds += 1
            self.state["qa_rounds"] = rounds
            fix_task = f"Fix the bugs QA reported (round {rounds})."
            code = self.delegate("developer", "fix_request", fix_task,
                                 f"{context}\n\n{fix_task}\n\n### Your previous code\n{code}\n\n"
                                 f"### QA report\n{report}\n\nReturn the complete fixed code.", "fix")
            self.write(f"03-developer-fix{rounds}.md", code)
            report = self.delegate("qa", "retest", f"Verify the fixes (round {rounds}).",
                                   f"{context}\n\nVerify the fixes for your earlier report.\n\n### Your earlier "
                                   f"report\n{report}\n\n### Fixed code\n{code}{qa_instr}", "test_report")
            verdict = parse_verdict(report)
            self.write(f"04-qa-round{rounds}.md", report)
        self.state["verdict"] = verdict
        if verdict == "FAIL":
            self.state["blockers"].append(f"QA still failing after {rounds} fix round(s)")
            self.agent("qa", "blocked")
        self.finish_stage("test", "done" if verdict == "PASS" else "failed")

        # APPROVAL + DEPLOY (only after QA passes)
        deploy = None
        if verdict == "PASS":
            approved, note = True, ""
            if "deploy" in self.require_approval:
                approved, note = self._ask_ceo(f"QA passed. Approve deploying: {goal}?")
            else:
                self.finish_stage("approval", "skipped")
            if approved:
                self.stage("deploy")
                deploy = self.delegate("devops", "assign", task_for("devops"),
                                       f"{context}\n\nYour assignment:\n{task_for('devops')}\n\nQA verdict: PASS"
                                       f"\nCEO approval: {note or 'approved'}\n\n### Design\n{design}\n\n"
                                       f"### Code\n{code}\n\n### QA report\n{report}\n\n"
                                       "Deploy it and set up monitoring.", "deploy_report")
                self.write("05-devops.md", deploy)
                self.state["deployed"] = True
                self.finish_stage("deploy")
            else:
                self.agent("devops", "waiting", "Deploy waits for CEO approval")
                self.finish_stage("deploy", "skipped")
        else:
            self.agent("devops", "waiting", "Deploy waits for QA to pass")
            self.finish_stage("approval", "skipped")
            self.finish_stage("deploy", "skipped")

        # REPORT
        self.stage("report")
        self.agent("lead", "working", "Report to the CEO")
        facts = (f"QA verdict: {verdict} after {rounds} fix round(s). "
                 f"Deployed: {'yes' if deploy else 'no'}. "
                 f"CEO approval: {self.state['approval']['result'] if self.state['approval'] else 'not requested'}.")
        outputs = f"### Design\n{design}\n\n### Code\n{code}\n\n### QA report\n{report}"
        if deploy:
            outputs += f"\n\n### Deploy report\n{deploy}"
        report_text = self.work("lead",
            f"CEO goal:\n{goal}\n\nFacts: {facts}\n\nTeam output:\n\n{outputs}\n\n"
            "Write the CEO report: high-level status only, no code. Answer with only a JSON object:\n"
            '{"current_goal": "<max 4 words>", "active_task": "<max 3 words>", "recent_result": "<max 4 words>", '
            '"next_action": "<max 4 words>", "summary": "<short paragraph for the CEO>", '
            '"blocker_list": ["<blocker>"]}',
            "Report to the CEO", "report",
            skills_for="report_blocked" if self.state["blockers"] else "report",
            fact=lambda out: f"CEO report for '{one_line(goal, 80)}' ({facts}): "
                             f"{one_line((extract_json(out) or {}).get('summary') or out, 240)}")
        rep = extract_json(report_text) or {"summary": report_text}
        rep.update(self._facts(verdict, bool(deploy)))
        self.state["report"] = rep
        self.write("99-ceo-report.json", json.dumps(rep, indent=2, ensure_ascii=False))
        self.bus.send("lead", "ceo", "report", rep.get("summary") or report_text, report=rep)
        self.agent("lead", "done")
        self.finish_stage("report")

    def _ask_ceo(self, question):
        self.stage("approval")
        request = {"question": question, "requested_at": now(), "result": "pending", "note": ""}
        self.state["approval"] = request
        self.state["status"] = "waiting_approval"
        self.agent("devops", "waiting", "Waiting for CEO approval to deploy")
        self.bus.send("lead", "ceo", "approval_request", question)
        if self.approver is None:
            approved, note = False, "no approver available (run with --approve, or from the dashboard)"
        else:
            approved, note = self.approver(request)
        self.check_cancel()
        request.update(result="approved" if approved else "rejected", note=note or "", resolved_at=now())
        self.state["status"] = "running"
        self.bus.send("ceo", "lead", "approval", f"{request['result'].upper()}{': ' + note if note else ''}")
        if not approved:
            self.state["blockers"].append(f"Deploy not approved by the CEO{': ' + note if note else ''}")
        self.finish_stage("approval", "done" if approved else "rejected")
        return approved, note

    def _facts(self, verdict, deployed):
        """Dashboard numbers from what actually happened, not from the model's opinion."""
        pending = self.state["approval"] and self.state["approval"]["result"] != "approved" and verdict == "PASS"
        if deployed:
            status = "DONE"
        elif self.state["blockers"]:
            status = "BLOCKED"
        else:
            status = "ACTIVE"
        return {"status": status, "progress": 100 if deployed else self.state["progress"],
                "approval_needed": 1 if pending else 0, "blockers": len(self.state["blockers"]),
                "qa_verdict": verdict, "fix_rounds": self.state["qa_rounds"], "deployed": deployed,
                "blocker_list": self.state["blockers"]}
