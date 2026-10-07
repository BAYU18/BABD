"""The team's communication flow.

    CEO -> Team Lead                       goal
    Team Lead -> Architect -> Team Lead    design
    Team Lead -> Developer -> Team Lead    code                    } at the same time
    Team Lead -> QA -> Team Lead           test plan from design   } (project.parallel_prep)
    Team Lead -> DevOps -> Team Lead       deploy preparation      }
    Team Lead -> QA -> Team Lead           test report + VERDICT
        (FAIL) Team Lead -> Developer (fix) -> Team Lead -> QA (re-test) ...  up to max_fix_rounds
    Team Lead -> CEO                       approval request before deploy   (project.require_approval)
    Team Lead -> DevOps -> Team Lead       deploy + monitoring              (only after PASS + approval)
    Team Lead -> CEO                       report

Every message goes through MessageBus.send(), which only allows the routes above: the Team Lead
is the hub, specialists never talk to each other or to the CEO directly.

Many runs (tasks) can go at once. AgentSlots, shared by all of them, sets how many steps each agent
works on at the same time (`parallel` per agent in agents.json); a step waits for a free slot.
"""
import datetime
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .config import ROOT
from . import projects, skillpacks, taskdocs
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


DEFAULT_PARALLEL = 2  # steps one agent works on at the same time, when agents.json does not say


class AgentSlots:
    """How many steps each agent may work on at once, shared by every run. A step that finds all of
    the agent's slots taken waits (status "queued") until one is free."""

    def __init__(self, cfg=None):
        self.cond = threading.Condition()
        self.capacity, self.active, self.waiting = {}, {}, {}
        if cfg:
            self.configure(cfg)

    def configure(self, cfg):
        with self.cond:
            for a in cfg.get("agents", []):
                self.capacity[a["id"]] = parallel_of(a)
            self.cond.notify_all()

    def acquire(self, agent_id, cancelled=None):
        with self.cond:
            self.waiting[agent_id] = self.waiting.get(agent_id, 0) + 1
            try:
                while self.active.get(agent_id, 0) >= self.capacity.get(agent_id, DEFAULT_PARALLEL):
                    if cancelled is not None and cancelled.is_set():
                        raise FlowCancelled("run cancelled by the CEO")
                    self.cond.wait(0.5)
            finally:
                self.waiting[agent_id] -= 1
            self.active[agent_id] = self.active.get(agent_id, 0) + 1

    def release(self, agent_id):
        with self.cond:
            self.active[agent_id] = max(0, self.active.get(agent_id, 0) - 1)
            self.cond.notify_all()

    def free(self, agent_id):
        with self.cond:
            return self.active.get(agent_id, 0) < self.capacity.get(agent_id, DEFAULT_PARALLEL)

    def load(self):
        with self.cond:
            ids = set(self.capacity) | set(self.active)
            return {i: {"capacity": self.capacity.get(i, DEFAULT_PARALLEL), "active": self.active.get(i, 0),
                        "waiting": self.waiting.get(i, 0)} for i in ids}


def parallel_of(agent_cfg):
    try:
        return max(1, min(8, int(agent_cfg.get("parallel", DEFAULT_PARALLEL))))
    except (TypeError, ValueError):
        return DEFAULT_PARALLEL


class MessageBus:
    def __init__(self, emit, run_dir, lock=None):
        self.messages = []
        self.emit = emit
        self.lock = lock or threading.RLock()
        self.path = os.path.join(run_dir, "messages.jsonl")

    def send(self, sender, recipient, kind, content, **meta):
        if (sender, recipient) not in ROUTES:
            raise FlowError(f"route {sender} -> {recipient} is not part of the team flow")
        with self.lock:
            msg = {"seq": len(self.messages) + 1, "at": now(), "from": sender, "to": recipient, "kind": kind,
                   "content": content, **meta}
            self.messages.append(msg)
            with open(self.path, "a") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.emit("message", msg)
        return msg


class Run:
    """One team run on a goal. State is plain JSON so the dashboard can show it as-is."""

    def __init__(self, team, goal, approver=None, on_event=None, run_id=None, slots=None, docs=None,
                 project_id=None, resume=False):
        self.team = team
        self.goal = goal
        self.docs = list(docs or [])       # task documents (babd/taskdocs.py): the brief every agent gets
        self.approver = approver           # fn(request_dict) -> (approved: bool, note: str); None = no approver
        self.on_event = on_event or (lambda kind, data: None)
        self.slots = slots or AgentSlots(team.cfg)  # shared between runs by the dashboard
        self.cancelled = threading.Event()
        self.lock = threading.RLock()      # steps of one run can run at the same time
        project = team.cfg.get("project", {})
        self.require_approval = project.get("require_approval", ["deploy"])
        self.max_fix_rounds = int(project.get("max_fix_rounds", 2))
        self.parallel_prep = bool(project.get("parallel_prep", True))
        self.resumed = bool(resume)
        if resume:
            self._load(run_id)
        else:
            self._create(run_id, goal, team)
        # Where the agents work: a git worktree of the task's project, never the BABD installation.
        self.project, self.workspace = None, None
        if project.get("use_projects", True):
            project_id = (self.state.get("workspace") or {}).get("project") if resume else project_id
            self.project = projects.get(team.cfg, project_id)  # fails now for an unknown project
            ws = self.state.get("workspace") or {}
            ws.pop("result", None)
            self.state["workspace"] = {**ws, "project": self.project["id"], "name": self.project["name"]}
        self.state["pid"] = os.getpid()
        self.bus = MessageBus(self.emit, self.dir, self.lock)
        if resume:
            mp = os.path.join(self.dir, "messages.jsonl")
            if os.path.exists(mp):
                with open(mp) as f:
                    self.bus.messages.extend(json.loads(line) for line in f if line.strip())
        self.state["messages"] = self.bus.messages
        self.steps = max([st.get("n", 0) for st in self.state["steps"]] or [0])

    def _create(self, run_id, goal, team):
        base = run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.id, n = base, 1
        os.makedirs(RUNS_DIR, exist_ok=True)
        while True:  # two runs in the same second
            try:
                os.makedirs(os.path.join(RUNS_DIR, self.id))
                break
            except FileExistsError:
                n += 1
                self.id = f"{base}-{n}"
        self.dir = os.path.join(RUNS_DIR, self.id)
        self.brief = taskdocs.brief_of(self.docs) if self.docs else ""
        self.state = {
            "id": self.id, "goal": goal, "status": "running", "stage": None, "progress": 0,
            "started_at": now(), "finished_at": None, "error": None, "dir": self.dir,
            "agents": {a.id: {"status": "idle", "task": ""} for a in team.agents},
            "stages": {k: "todo" for k, *_ in STAGES}, "qa_rounds": 0, "verdict": None,
            "approval": None, "deployed": False, "blockers": [], "report": None, "memory": [], "skills": [],
            "steps": [], "documents": [taskdocs.summary(d) for d in self.docs], "checkpoints": [], "resumes": 0,
        }
        if self.docs:
            self.write("00-task.md", self.brief + "\n")

    def _load(self, run_id):
        """Pick up a run that was interrupted, failed or stopped: steps already done are reused."""
        self.id = os.path.basename(run_id or "")
        self.dir = os.path.join(RUNS_DIR, self.id)
        try:
            with open(os.path.join(self.dir, "state.json")) as f:
                self.state = json.load(f)
        except (OSError, ValueError) as e:
            raise FlowError(f"cannot resume {run_id!r}: no saved run") from e
        self.goal = self.state["goal"]
        brief_path = os.path.join(self.dir, "00-task.md")
        self.brief = open(brief_path).read().strip() if os.path.exists(brief_path) else ""
        st = self.state
        st.update(status="running", error=None, finished_at=None, report=None, blockers=[], stage=None, progress=0,
                  verdict=None, deployed=False, resumes=st.get("resumes", 0) + 1)
        st.setdefault("checkpoints", [])
        st.setdefault("steps", [])
        st["stages"] = {k: "todo" for k, *_ in STAGES}
        for a in st["agents"].values():
            a.update(status="idle", task="")
        for step in st["steps"]:
            if step.get("status") in ("queued", "working"):
                step["status"] = "interrupted"

    # -- checkpoints: each finished step is kept, so a resumed run continues after it -------------

    def step(self, key, fn):
        path = os.path.join(self.dir, "ckpt", f"{key}.txt")
        if key in self.state["checkpoints"] and os.path.exists(path):
            with open(path) as f:
                return f.read()
        out = fn()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(out)
        with self.lock:
            if key not in self.state["checkpoints"]:
                self.state["checkpoints"].append(key)
        self.save()
        return out

    # -- state + events ----------------------------------------------------------------------

    def emit(self, kind, data):
        if kind != "message":
            self.save()
        self.on_event(kind, {"run": self.id, **data} if isinstance(data, dict) else data)

    def save(self):
        with self.lock:
            state = json.dumps({k: v for k, v in self.state.items() if k != "messages"}, indent=2, ensure_ascii=False)
            with open(os.path.join(self.dir, "state.json"), "w") as f:
                f.write(state)

    def snapshot(self):
        """A copy of the state that is safe to read while steps are still running."""
        with self.lock:
            return json.loads(json.dumps(self.state, ensure_ascii=False, default=str))

    @property
    def goal_block(self):
        """The goal as every prompt shows it: the CEO's words plus the full task documents."""
        text = f"CEO goal:\n{self.goal}"
        if self.brief:
            text += (f"\n\nThe CEO gave the task as document(s); follow them. (Agents with file tools can also read "
                     f"them at {os.path.join(self.dir, '00-task.md')}.)\n\n{self.brief}")
        if self.workspace:
            ws = self.workspace
            text += (f"\n\n## Workspace\nProject: {ws['name']}. Work ONLY in this folder: {ws['dir']} (git branch "
                     f"{ws['branch']}; BABD commits and merges it when the task ends). Create, change and run files "
                     f"only there. Never change the BABD installation at {projects.ROOT} or any other project. "
                     "If you cannot write files yourself, give every file as a fenced block whose first line is "
                     "```<language> file=<path relative to the workspace>; BABD writes those files for you.")
        return text

    def write(self, name, content):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(content)

    def check_cancel(self):
        if self.cancelled.is_set():
            raise FlowCancelled("run cancelled by the CEO")

    def stage(self, key):
        self.check_cancel()
        with self.lock:
            for k, state in self.state["stages"].items():
                if state == "active":
                    self.state["stages"][k] = "done"
            self.state["stages"][key] = "active"
            self.state["stage"] = key
        self.emit("stage", {"stage": key})

    def finish_stage(self, key, result="done"):
        with self.lock:
            self.state["stages"][key] = result
            if result == "done" and (key != "report" or self.state["deployed"]):
                self.state["progress"] = max(self.state["progress"], STAGE_PROGRESS[key])
        self.emit("stage", {"stage": key, "result": result})

    def agent(self, agent_id, status, task=None):
        with self.lock:
            a = self.state["agents"][agent_id]
            a["status"] = status
            if task is not None:
                a["task"] = task
            a = dict(a)
        self.emit("agent", {"agent": agent_id, **a})

    # -- one agent step, always through the GBrain cycle (read -> work -> write) ---------------

    def work(self, agent_id, prompt, task, kind, fact=None, skills_for=None):
        agent = self.team.by_id[agent_id]
        skills = skillpacks.for_step(agent.skill_packs, skills_for or kind)

        def on_skills(entry):
            with self.lock:
                entry = {**entry, "after_seq": len(self.bus.messages), "kind": kind}
                self.state["skills"].append(entry)
            self.emit("skills", entry)
        with self.lock:
            self.steps += 1
            n = self.steps
            step = {"n": n, "agent": agent_id, "kind": kind, "task": task, "queued_at": now(),
                    "started_at": None, "finished_at": None, "seconds": None, "status": "queued"}
            self.state["steps"].append(step)
        goal_short = one_line(self.goal, 80)

        def default_fact(out):
            return f"{agent.name} ({kind}) for '{goal_short}': {one_line(out, 220)}"

        def on_memory(entry):
            with self.lock:
                entry = {**entry, "after_seq": len(self.bus.messages), "kind": kind}
                self.state["memory"].append(entry)
            self.emit("memory", entry)

        if not self.slots.free(agent_id):
            self.agent(agent_id, "queued", f"{task} (waiting: {agent.name} is busy with other tasks)")
            self.emit("step", dict(step))
        self.slots.acquire(agent_id, self.cancelled)
        started = time.monotonic()
        with self.lock:
            step.update(status="working", started_at=now())
            if self.state["agents"][agent_id]["status"] == "queued":
                self.state["agents"][agent_id].update(status="working", task=task)
        self.emit("step", dict(step))
        try:
            out = agent.work(prompt, query=(self.goal, task), task=task, page_title=f"{agent.name} · {kind} · {goal_short}",
                             page_slug=f"babd/runs/{self.id}/{n:02d}-{agent_id}-{kind}",
                             entity=f"babd/goals/{slugify(self.goal)}",
                             provenance=f"babd run {self.id} · {agent.name} · {kind}",
                             fact=fact or default_fact, on_memory=on_memory, skills=skills, on_skills=on_skills)
            result = "done"
            return out
        except BaseException:
            result = "failed"
            raise
        finally:
            self.slots.release(agent_id)
            with self.lock:
                step.update(status=result, finished_at=now(), seconds=round(time.monotonic() - started, 1))
            self.emit("step", dict(step))

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
        self.write_files(agent_id, out, reply_kind)
        self.bus.send(agent_id, "lead", reply_kind, out, seconds=round(time.monotonic() - started, 1))
        self.agent(agent_id, "done")
        return out

    def write_files(self, agent_id, out, kind):
        """An agent without file tools gives its files as ```lang file=path blocks: write them."""
        if not self.workspace or self.team.by_id[agent_id].harness.has_tools:
            return
        written = projects.write_file_blocks(out, self.workspace["dir"])
        if written:
            with self.lock:
                self.state["workspace"].setdefault("files_written", []).extend(
                    {"agent": agent_id, "kind": kind, "path": p} for p in written)
            self.emit("files", {"agent": agent_id, "kind": kind, "paths": written})

    # -- the flow ----------------------------------------------------------------------------

    def prepare_workspace(self):
        """Create / clone the project and this task's worktree; every agent works there."""
        self.workspace = projects.start(self.project, self.id)
        for a in self.team.agents:
            a.harness.cfg = {**a.harness.cfg, "cwd": self.workspace["dir"]}
        with self.lock:
            self.state["workspace"].update({k: self.workspace[k] for k in ("dir", "branch", "base")})
        self.emit("workspace", dict(self.state["workspace"]))

    def execute(self):
        try:
            if self.project:
                self.prepare_workspace()
            self._flow()
            self.state["status"] = "done"
        except FlowCancelled as e:
            self.state["status"] = "cancelled"
            self.state["error"] = str(e)
        except Exception as e:  # any agent / harness failure ends the run with a clear error
            self.state["status"] = "failed"
            self.state["error"] = f"{type(e).__name__}: {e}"
        if self.workspace:
            self.finish_workspace()
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
        self.emit("started", {"goal": goal, "resumed": self.resumed})
        if not self.bus.messages:
            self.bus.send("ceo", "lead", "goal", goal)

        # PLAN
        self.stage("plan")
        self.agent("lead", "working", "Plan work and assign agents")
        specialists = ROLES[1:]
        team_desc = "\n".join(f"- {r}: {names[r]} - main task {team.by_id[r].main_task}; skills: "
                              f"{', '.join(team.by_id[r].cfg.get('skills', []))}" for r in specialists)
        slots = ", ".join(f'"{r}": "<task>"' for r in specialists)
        plan_text = self.step("plan", lambda: self.work("lead",
            f"{self.goal_block}\n\nYour team:\n{team_desc}\n\n"
            "The work flows through you: Architect designs, Developer builds, QA tests (failed tests go back "
            "to the Developer), DevOps deploys and sets up monitoring after QA passes and the CEO approves.\n"
            "Plan the work and assign one concrete task to every agent. Answer with only a JSON object:\n"
            '{"plan_summary": "<2-4 sentences>", "assignments": {' + slots + "}}",
            "Plan the work and assign agents", "plan",
            fact=lambda out: f"Team Lead plan for '{one_line(goal, 80)}': "
                             f"{one_line((extract_json(out) or {}).get('plan_summary') or out, 240)}"))
        plan = extract_json(plan_text) or {}
        assignments = plan.get("assignments") if isinstance(plan.get("assignments"), dict) else {}
        summary = plan.get("plan_summary") or plan_text
        self.write("01-plan.md", plan_text)
        self.agent("lead", "waiting", "Coordinate results (waits for the team)")
        self.finish_stage("plan")

        def task_for(role):
            return str(assignments.get(role) or "") or f"Do your part ({team.by_id[role].main_task}) for the goal."

        context = f"{self.goal_block}\n\nTeam Lead plan:\n{summary}"

        # DESIGN
        self.stage("design")
        design = self.step("design", lambda: self.delegate("architect", "assign", task_for("architect"),
                           f"{context}\n\nYour assignment:\n{task_for('architect')}", "design"))
        self.write("02-architect.md", design)
        self.finish_stage("design")

        # CODE, with QA's test plan and DevOps' deploy preparation at the same time
        self.stage("code")
        jobs = {"developer": lambda: self.step("code", lambda: self.delegate(
            "developer", "assign", task_for("developer"),
            f"{context}\n\nYour assignment:\n{task_for('developer')}\n\n### Design from {names['architect']}\n{design}",
            "code"))}
        if self.parallel_prep:
            jobs["qa"] = lambda: self.step("test_plan", lambda: self.delegate(
                "qa", "prepare", "Write the test plan from the design while the Developer builds.",
                f"{context}\n\nYour assignment:\n{task_for('qa')}\n\n### Design from {names['architect']}\n{design}\n\n"
                "The Developer is building it now. Prepare the tests first: the test cases (acceptance criteria, "
                "edge cases, failure cases) and the test code you will run against the build. Do not give a "
                "verdict yet.", "test_plan"))
            jobs["devops"] = lambda: self.step("deploy_prep", lambda: self.delegate(
                "devops", "prepare", "Prepare the deployment while the Developer builds.",
                f"{context}\n\nYour assignment:\n{task_for('devops')}\n\n### Design from {names['architect']}\n{design}\n\n"
                "The Developer is building it now. Prepare the deployment: environments, pipeline, "
                "configuration and secrets needed (names only), health checks, monitoring and alerts, rollback "
                "plan, and any step a person must do by hand. Do not deploy yet: that waits for QA and the CEO.",
                "deploy_prep"))
        out = self.parallel(jobs)
        code, test_plan, prep = out["developer"], out.get("qa"), out.get("devops")
        self.write("03-developer.md", code)
        if test_plan:
            self.write("03-qa-test-plan.md", test_plan)
        if prep:
            self.write("03-devops-prep.md", prep)
        self.finish_stage("code")

        # TEST, with the fix loop
        self.stage("test")
        qa_instr = ("\n\nTest the work against the goal and the design. List every bug you find. "
                    "End your answer with exactly one line: VERDICT: PASS or VERDICT: FAIL")
        plan_part = f"\n\n### Your test plan\n{test_plan}" if test_plan else ""
        report = self.step("qa0", lambda: self.delegate("qa", "assign", task_for("qa"),
                           f"{context}\n\nYour assignment:\n{task_for('qa')}\n\n### Design\n{design}{plan_part}\n\n"
                           f"### Code from {names['developer']}\n{code}{qa_instr}", "test_report"))
        verdict = parse_verdict(report)
        self.write("04-qa-round0.md", report)
        rounds = 0
        while verdict == "FAIL" and rounds < self.max_fix_rounds:
            rounds += 1
            self.state["qa_rounds"] = rounds
            fix_task = f"Fix the bugs QA reported (round {rounds})."
            code = self.step(f"fix{rounds}", lambda: self.delegate(
                "developer", "fix_request", fix_task, f"{context}\n\n{fix_task}\n\n### Your previous code\n{code}\n\n"
                f"### QA report\n{report}\n\nReturn the complete fixed code.", "fix"))
            self.write(f"03-developer-fix{rounds}.md", code)
            report = self.step(f"qa{rounds}", lambda: self.delegate(
                "qa", "retest", f"Verify the fixes (round {rounds}).", f"{context}\n\nVerify the fixes for your earlier "
                f"report.\n\n### Your earlier report\n{report}\n\n### Fixed code\n{code}{qa_instr}", "test_report"))
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
                deploy = self.step("deploy", lambda: self.delegate("devops", "assign", task_for("devops"),
                                       f"{context}\n\nYour assignment:\n{task_for('devops')}\n\nQA verdict: PASS"
                                       f"\nCEO approval: {note or 'approved'}\n\n### Design\n{design}\n\n"
                                       f"### Code\n{code}\n\n### QA report\n{report}\n\n"
                                       + (f"### Your deploy preparation\n{prep}\n\n" if prep else "")
                                       + "Deploy it and set up monitoring.", "deploy_report"))
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
        report_text = self.step("report", lambda: self.work("lead",
            f"{self.goal_block}\n\nFacts: {facts}\n\nTeam output:\n\n{outputs}\n\n"
            "Write the CEO report: high-level status only, no code. Answer with only a JSON object:\n"
            '{"current_goal": "<max 4 words>", "active_task": "<max 3 words>", "recent_result": "<max 4 words>", '
            '"next_action": "<max 4 words>", "summary": "<short paragraph for the CEO>", '
            '"blocker_list": ["<blocker>"]}',
            "Report to the CEO", "report",
            skills_for="report_blocked" if self.state["blockers"] else "report",
            fact=lambda out: f"CEO report for '{one_line(goal, 80)}' ({facts}): "
                             f"{one_line((extract_json(out) or {}).get('summary') or out, 240)}"))
        rep = extract_json(report_text) or {"summary": report_text}
        rep.update(self._facts(verdict, bool(deploy)))
        self.state["report"] = rep
        self.write("99-ceo-report.json", json.dumps(rep, indent=2, ensure_ascii=False))
        self.bus.send("lead", "ceo", "report", rep.get("summary") or report_text, report=rep)
        self.agent("lead", "done")
        self.finish_stage("report")

    def finish_workspace(self):
        """Commit the task's work on its branch, and merge it per the project's merge policy."""
        policy = self.project["merge"]
        passed = self.state["status"] == "done" and self.state["verdict"] == "PASS"
        approved = not self.state["approval"] or self.state["approval"].get("result") == "approved"
        merge = passed and (policy == "on_pass" or (policy == "on_approval" and approved))
        result = projects.finish(self.project, self.workspace, f"babd: {one_line(self.goal, 72)} (task {self.id})", merge)
        with self.lock:
            self.state["workspace"]["result"] = result
        self.emit("workspace", result)

    def parallel(self, jobs):
        """Run {agent_id: fn} at the same time. Returns {agent_id: result}; re-raises the first error
        after every job has finished (a job that is already working is never abandoned)."""
        if len(jobs) == 1:
            return {k: fn() for k, fn in jobs.items()}
        with ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix=f"run-{self.id}") as pool:
            futures = {k: pool.submit(fn) for k, fn in jobs.items()}
            errors = [f.exception() for f in futures.values() if f.exception() is not None]
        if errors:
            cancelled = [e for e in errors if isinstance(e, FlowCancelled)]
            raise (cancelled or errors)[0]
        return {k: f.result() for k, f in futures.items()}

    def _ask_ceo(self, question):
        if "approval" in self.state["checkpoints"]:  # resumed after the CEO already answered
            decided = json.loads(self.step("approval", lambda: "{}"))
            if not decided["approved"]:
                self.state["blockers"].append(f"Deploy not approved by the CEO{': ' + decided['note'] if decided['note'] else ''}")
            self.finish_stage("approval", "done" if decided["approved"] else "rejected")
            return decided["approved"], decided["note"]
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
        self.step("approval", lambda: json.dumps({"approved": bool(approved), "note": note or ""}))
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
