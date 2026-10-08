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

Not every task needs the whole team. First the Team Lead triages the goal with one short call
(project.fast_lane, on by default) and picks a route:
    answer   the Team Lead answers the CEO itself (a question, advice)
    direct   one specialist does it in one go (a command, a key, a config change, a small script):
             Team Lead -> agent -> Team Lead -> CEO, no design / QA / deploy rounds
    team     the flow above, with only the specialists the task needs (no Architect for small
             changes, no DevOps when nothing is deployed)
A task's `mode` option overrides it: "quick" (never the whole team) or "full" (always the flow above).

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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .config import ROOT
from . import projects, servers, skillpacks, taskdocs
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
EVIDENCE_RE = re.compile(r"EVIDENCE\s*:?\**\s*\n?(.*?)(?=\n\s*\**VERDICT:|\Z)", re.I | re.S)


QUESTION_RE = re.compile(r"^\s*\**\s*QUESTION\s*\**\s*:\s*\**\s*(.+?)\s*$", re.M)
OPTIONS_RE = re.compile(r"^\s*\**\s*OPTIONS\s*\**\s*:\s*\**\s*(.+?)\s*$", re.M)
ASK_INSTRUCTION = ("If something essential is unclear and you cannot reasonably decide it yourself (a password you "
                   "were not given, which server, a choice only the CEO can make), end your answer with a line "
                   "`QUESTION: <your question>` and, when there are clear choices, a line `OPTIONS: <a> | <b> | <c>`. "
                   "The CEO answers and you do the step again with the answer. Ask only when you must; otherwise "
                   "decide, and say what you assumed.")


def parse_question(text):
    """{"question", "options"} when an agent's answer ends with a QUESTION: line (in its last lines)."""
    tail = "\n".join((text or "").strip().splitlines()[-15:])
    found = QUESTION_RE.findall(tail)
    if not found:
        return None
    question = found[-1].strip().strip("`*").strip()
    if not question or question.lower().startswith("<"):
        return None
    opts = OPTIONS_RE.findall(tail)
    options = [o.strip().strip("`*").strip() for o in (opts[-1].split("|") if opts else []) if o.strip()][:6]
    return {"question": question[:500], "options": [o[:60] for o in options]}


def evidence_of(report):
    """QA's EVIDENCE section when it shows real runs (commands with output), else None."""
    m = EVIDENCE_RE.search(report or "")
    if not m:
        return None
    text = m.group(1).strip()
    if not text or re.match(r"^\**\s*not run", text, re.I):
        return None
    shows_run = "```" in text or re.search(r"^\s*(\$|>|❯)\s*\S", text, re.M) or re.search(r"exit (code|status)", text, re.I)
    return text if shows_run else None


class Live:
    """Text built again each time it is used in an f-string (so a later prompt sees new answers)."""

    def __init__(self, fn):
        self.fn = fn

    def __format__(self, spec):
        return format(self.fn(), spec)

    __str__ = lambda self: self.fn()  # noqa: E731


class FlowError(Exception):
    pass


class FlowCancelled(Exception):
    pass


class BudgetExceeded(FlowError):
    pass


def add_usage(total, u):
    """Add one call's usage {"input", "output", "cost", "estimated"} into a running total."""
    total["input"] = total.get("input", 0) + u["input"]
    total["output"] = total.get("output", 0) + u["output"]
    total["calls"] = total.get("calls", 0) + 1
    if u.get("cost") is not None:
        total["cost"] = round(total.get("cost", 0.0) + float(u["cost"]), 6)
    else:
        total["cost_unknown"] = True
    if u.get("estimated"):
        total["estimated"] = True
    return total


SKIPPABLE = {"architect": "no Architect: the Team Lead's plan is the design (small changes)",
             "devops": "no DevOps: no deploy, the task ends after QA and the report",
             "prep": "no parallel preparation: QA and DevOps do not prepare while the Developer builds"}


MODES = {"auto": "the Team Lead decides who is needed (fast for small jobs)",
         "quick": "fast lane: the Team Lead answers or one agent does it, never the whole team",
         "full": "the whole flow: plan, design, code, test, approval, deploy"}
ROUTES_TAKEN = ("answer", "direct", "team")
SECRETS_RULE = ("Secrets you create or find (private keys, passwords, tokens) never go into the workspace or "
                "your answer: keep them in their usual place on this machine (for example ~/.ssh, mode 600) and "
                "give only their path. Public keys may be shown in full.")


def task_options(options, agent_ids=None):
    """Validated per-task options: {"mode": ..., "skip": [...], "models": {agent: model}}."""
    options = options or {}
    mode = str(options.get("mode") or "auto").strip().lower()
    if mode not in MODES:
        raise FlowError(f"mode must be one of {', '.join(MODES)}")
    skip = [x for x in dict.fromkeys(options.get("skip") or []) if x]
    bad = [x for x in skip if x not in SKIPPABLE]
    if bad:
        raise FlowError(f"cannot skip {', '.join(map(str, bad))} (only {', '.join(SKIPPABLE)})")
    models = {}
    for agent, model in (options.get("models") or {}).items():
        model = str(model or "").strip()
        if not model:
            continue
        if agent_ids is not None and agent not in agent_ids:
            raise FlowError(f"no agent {agent!r} to set a model for")
        if len(model) > 120:
            raise FlowError("model name too long")
        models[agent] = model
    return {"mode": mode, "skip": skip, "models": models}


def apply_models(cfg, models):
    """A copy of the team config with this task's model per agent."""
    import copy
    cfg = copy.deepcopy(cfg)
    for a in cfg["agents"]:
        if a["id"] in models:
            a["llm"]["model"] = models[a["id"]]
    return cfg


def budget_of(project_cfg):
    b = (project_cfg or {}).get("budget") or {}
    out = {}
    for k in ("tokens_per_task", "cost_per_task", "tokens_per_day", "cost_per_day"):
        try:
            out[k] = max(0.0, float(b.get(k) or 0))
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def over_budget(usage, tokens_limit, cost_limit):
    """A reason string when `usage` is at or over a limit (0 = no limit), else None."""
    tokens = usage.get("input", 0) + usage.get("output", 0)
    if tokens_limit and tokens >= tokens_limit:
        return f"{tokens:,} tokens used of a {int(tokens_limit):,} token budget"
    if cost_limit and usage.get("cost", 0) >= cost_limit:
        return f"${usage['cost']:.2f} spent of a ${cost_limit:.2f} budget"
    return None


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
                 project_id=None, resume=False, options=None, asker=None):
        self.team = team
        self.goal = goal
        self.asker = asker                 # fn(question_dict) -> answer text (None = no answer); None = never ask
        self.docs = list(docs or [])       # task documents (babd/taskdocs.py): the brief every agent gets
        self.approver = approver           # fn(request_dict) -> (approved: bool, note: str); None = no approver
        self.on_event = on_event or (lambda kind, data: None)
        self.slots = slots or AgentSlots(team.cfg)  # shared between runs by the dashboard
        self.cancelled = threading.Event()
        self.paused = threading.Event()    # set = pause before the next step (a step already working finishes)
        self.lock = threading.RLock()      # steps of one run can run at the same time
        project = team.cfg.get("project", {})
        self.require_approval = project.get("require_approval", ["deploy"])
        self.max_questions = int(project.get("max_questions", 3)) if project.get("ask_ceo", True) else 0
        self.max_fix_rounds = int(project.get("max_fix_rounds", 2))
        self.parallel_prep = bool(project.get("parallel_prep", True))
        self.budget = budget_of(project)
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
        if not resume or options is not None:
            self.state["task_options"] = task_options(options, set(team.by_id))
        self.options = self.state.get("task_options") or {"skip": [], "models": {}}
        self.mode = self.options.get("mode") or "auto"
        self.fast_lane = bool(project.get("fast_lane", True))
        self.skip = set(self.options["skip"])
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
            "usage": {}, "questions": [], "question": None,
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
                  verdict=None, deployed=False, resumes=st.get("resumes", 0) + 1, paused=False, question=None)
        st["questions"] = [q for q in st.get("questions") or [] if q.get("answer") is not None]
        st.setdefault("checkpoints", [])
        st.setdefault("usage", {})
        st.setdefault("steps", [])
        st["stages"] = {k: "todo" for k, *_ in STAGES}
        for a in st["agents"].values():
            a.update(status="idle", task="")
        for step in st["steps"]:
            if step.get("status") in ("queued", "working"):
                step["status"] = "interrupted"
            if step.get("status") == "interrupted" and not step.get("finished_at"):
                step["finished_at"] = now()

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
        from . import agentlog
        for e in agentlog.record(self.id, self.goal, kind, data, {a.id: a.name for a in self.team.agents}):
            self.on_event("agentlog", e)
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
        answered = [q for q in self.state.get("questions") or [] if q.get("answer")]
        if answered:
            text += "\n\n## The CEO's answers to the team's questions\n" + "\n".join(
                f"- Q ({q['agent']}): {q['question']}\n  A: {q['answer']}" for q in answered)
        if self.asker and self.max_questions:
            text += "\n\n" + ASK_INSTRUCTION
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
        self.wait_if_paused()
        if self.cancelled.is_set():
            raise FlowCancelled("run cancelled by the CEO")

    def pause(self, on=True):
        """Pause (the steps already working finish, the next ones wait) or continue the task."""
        if on:
            self.paused.set()
        else:
            self.paused.clear()
        with self.lock:
            if not on and self.state["status"] == "paused":
                self.state["status"] = "running"
            self.state["paused"] = bool(on)
        self.emit("paused" if on else "unpaused", {"paused": bool(on)})

    def wait_if_paused(self):
        if not self.paused.is_set() or self.cancelled.is_set():
            return
        with self.lock:
            before = self.state["status"]
            if before == "running":
                self.state["status"] = "paused"
        self.emit("paused", {"paused": True, "waiting": True})
        while self.paused.is_set() and not self.cancelled.is_set():
            self.cancelled.wait(0.2)
        with self.lock:
            if self.state["status"] == "paused":
                self.state["status"] = before

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
            if result == "done" and (key != "report" or self.state["deployed"] or self.quick_route
                                     or ("devops" in getattr(self, "skip", ()) and self.state["verdict"] == "PASS")):
                self.state["progress"] = max(self.state["progress"], STAGE_PROGRESS[key])
        self.emit("stage", {"stage": key, "result": result})

    @property
    def quick_route(self):
        return (self.state.get("route") or {}).get("route") in ("answer", "direct")

    def agent(self, agent_id, status, task=None):
        with self.lock:
            a = self.state["agents"][agent_id]
            a["status"] = status
            if task is not None:
                a["task"] = task
            a = dict(a)
        self.emit("agent", {"agent": agent_id, **a})

    # -- one agent step, always through the GBrain cycle (read -> work -> write) ---------------

    def work(self, agent_id, prompt, task, kind, fact=None, skills_for=None, light=False, memory=True):
        self.check_cancel()  # also waits here while the task is paused
        reason = over_budget(self.state["usage"], self.budget["tokens_per_task"], self.budget["cost_per_task"])
        if reason:
            raise BudgetExceeded(f"task budget reached: {reason} (raise project.budget, then Resume)")
        agent = self.team.by_id[agent_id]
        try:
            reach = servers.prompt_block(self.team.cfg, agent_id)
        except servers.ServerError:
            reach = ""
        if reach:
            prompt = f"{prompt}\n\n{reach}"
        skills = [] if light else skillpacks.for_step(agent.skill_packs, skills_for or kind)

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

        def on_retry(info):  # temporary LLM errors: retried, then the agent's fallback model
            with self.lock:
                if info.get("fallback"):
                    step["fallback"] = info["fallback"]
                else:
                    step["retries"] = step.get("retries", 0) + 1
                step["last_error"] = info.get("error")
            self.emit("retry", {"agent": agent_id, "kind": kind, **info})
        def on_usage(u):
            with self.lock:
                add_usage(step.setdefault("usage", {}), u)
                add_usage(self.state["usage"], u)
                add_usage(self.state["usage"].setdefault("by_agent", {}).setdefault(agent_id, {}), u)
        agent.listener.on_retry, agent.listener.cancelled = on_retry, self.cancelled
        agent.listener.on_usage = on_usage
        try:
            out = agent.work(prompt, query=(self.goal, task), task=task, page_title=f"{agent.name} · {kind} · {goal_short}",
                             page_slug=f"babd/runs/{self.id}/{n:02d}-{agent_id}-{kind}",
                             entity=f"babd/goals/{slugify(self.goal)}",
                             provenance=f"babd run {self.id} · {agent.name} · {kind}",
                             fact=fact or default_fact, on_memory=on_memory, skills=skills, on_skills=on_skills,
                             light=light, memory=memory)
            result = "done"
            return out
        except BaseException:
            result = "failed"
            raise
        finally:
            agent.listener.on_retry = agent.listener.cancelled = agent.listener.on_usage = None
            self.slots.release(agent_id)
            with self.lock:
                step.update(status=result, finished_at=now(), seconds=round(time.monotonic() - started, 1))
            self.emit("step", dict(step))

    # -- one exchange: Team Lead -> agent -> Team Lead -----------------------------------------

    def delegate(self, agent_id, kind, task, prompt, reply_kind, **work_kw):
        """Lead sends `task` to an agent, the agent works on `prompt`, and reports back to the lead."""
        self.check_cancel()
        self.bus.send("lead", agent_id, kind, task)
        self.agent(agent_id, "working", task)
        started = time.monotonic()
        try:
            fact = None
            if reply_kind == "test_report":
                fact = (lambda o: f"QA verdict {parse_verdict(o)} for '{one_line(self.goal, 80)}': {one_line(o, 200)}")
            out = self.work(agent_id, prompt, task, reply_kind, fact=fact, **work_kw)
            q = parse_question(out)
            while q and self.can_ask():
                answer = self.ask_question(agent_id, q)
                if not answer:
                    break
                out = self.work(agent_id, f"{prompt}\n\n### You asked the CEO\n{q['question']}\n\n### The CEO answered\n"
                                f"{answer}\n\nNow do your task again, using this answer.", task, reply_kind, fact=fact, **work_kw)
                q = parse_question(out)
        except Exception:
            self.agent(agent_id, "blocked")
            raise
        self.write_files(agent_id, out, reply_kind)
        self.bus.send(agent_id, "lead", reply_kind, out, seconds=round(time.monotonic() - started, 1))
        self.agent(agent_id, "done")
        return out

    # -- questions: an agent asks the CEO and waits for the answer ----------------------------------

    def can_ask(self):
        return bool(self.asker) and len(self.state.get("questions") or []) < self.max_questions

    def ask_question(self, agent_id, q):
        """Ask the CEO (dashboard / Telegram), wait for the answer, return it (None: no answer)."""
        name = self.team.by_id[agent_id].name
        with self.lock:
            entry = {"n": len(self.state["questions"]) + 1, "agent": agent_id, "question": q["question"],
                     "options": q.get("options") or [], "asked_at": now(), "answer": None}
            self.state["questions"].append(entry)
            self.state["question"] = entry
            before = self.state["status"]
            self.state["status"] = "waiting_answer"
        self.agent(agent_id, "waiting", "Waiting for the CEO's answer")
        self.bus.send("lead", "ceo", "question", f"{name} asks: {q['question']}"
                      + (f"\nOptions: {' | '.join(entry['options'])}" if entry["options"] else ""), agent=agent_id)
        self.emit("question", {**entry, "goal": self.goal, "agent_name": name})
        try:
            answer = self.asker({**entry, "run": self.id, "goal": self.goal, "agent_name": name})
        finally:
            with self.lock:
                self.state["question"] = None
                if self.state["status"] == "waiting_answer":
                    self.state["status"] = before
        self.check_cancel()
        answer = str(answer or "").strip()[:2000]
        with self.lock:
            entry.update(answer=answer or None, answered_at=now())
        if answer:
            self.bus.send("ceo", "lead", "answer", answer, agent=agent_id)
        self.agent(agent_id, "working", "Continuing with the CEO's answer")
        self.emit("answered", dict(entry))
        return answer or None

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
            if self.team.cfg.get("servers"):
                servers.write_config(self.team.cfg)
            if self.project:
                self.prepare_workspace()
            self._flow()
            self.state["status"] = "done"
        except FlowCancelled as e:
            self.state["status"] = "cancelled"
            self.state["error"] = str(e)
        except Exception as e:  # any agent / harness failure ends the run with a clear error
            if self.cancelled.is_set():  # the agent's program was stopped by the cancel
                self.state["status"] = "cancelled"
                self.state["error"] = "run cancelled by the CEO"
            else:
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

        # TRIAGE: who does this task needs?
        self.stage("plan")
        route = self.route()
        if route["route"] == "answer":
            return self._answer(route)
        if route["route"] == "direct":
            return self._direct(route)
        if "prep" in self.skip or "devops" in self.skip:
            self.parallel_prep = False

        # PLAN
        self.agent("lead", "working", "Plan work and assign agents")
        specialists = [r for r in ROLES[1:] if r not in self.skip]
        team_desc = "\n".join(f"- {r}: {names[r]} - main task {team.by_id[r].main_task}; skills: "
                              f"{', '.join(team.by_id[r].cfg.get('skills', []))}" for r in specialists)
        slots = ", ".join(f'"{r}": "<task>"' for r in specialists)
        plan_text = self.step("plan", lambda: self.work("lead",
            f"{self.goal_block}\n\nYour team:\n{team_desc}\n\n"
            + ("The work flows through you: " + ", ".join(
                {"architect": "Architect designs", "developer": "Developer builds",
                 "qa": "QA tests (failed tests go back to the Developer)",
                 "devops": "DevOps deploys and sets up monitoring after QA passes and the CEO approves"}[r]
                for r in specialists) + ".\n"
               + ("" if "architect" not in self.skip else "There is no Architect on this task: put the design "
                  "decisions the Developer needs into your plan.\n")
               + ("" if "devops" not in self.skip else "This task has no deploy.\n")) +
            "Plan the work and assign one concrete task to every agent.\n"
            "If the task is complex, also split it into small work packages that agents can do AT THE SAME TIME "
            "(for example backend, frontend, database, tests, deploy setup). Each package names one agent of the "
            "team and lists in depends_on only the packages whose output it really needs; a package starts as "
            "soon as those are done, the others run in parallel. Keep it to 2-8 packages; for a simple task leave "
            "work_packages empty. Answer with only a JSON object:\n"
            '{"plan_summary": "<2-4 sentences>", "assignments": {' + slots + '}, "work_packages": [{"id": "p1", '
            '"title": "<short>", "agent": "<agent id>", "task": "<what exactly to do>", "depends_on": []}]}',
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

        context = Live(lambda: f"{self.goal_block}\n\nTeam Lead plan:\n{summary}")  # picks up the CEO's answers

        packages = self.packages_of(plan)
        if packages:  # a complex task split into work packages: each starts as soon as what it needs is done
            design, code, test_plan, prep = self.run_packages(packages, context, plan_text)
        else:
            # DESIGN
            if "architect" in self.skip:
                design = f"(No Architect on this task: follow the Team Lead's plan.)\n\n{plan_text}"
                self.finish_stage("design", "skipped")
            else:
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
        qa_tools = self.team.by_id["qa"].harness.has_tools and self.team.by_id["qa"].harness.permissions != "plan"
        evidence_instr = ("\n\nRun the tests yourself in the workspace. Before the verdict, add a section EVIDENCE: with "
                          "each command you ran and its real output (in ``` blocks) and exit code. Never claim a result "
                          "you did not see." if qa_tools else
                          "\n\nYou cannot run commands: before the verdict write EVIDENCE: NOT RUN and list the "
                          "commands that should be run.")
        qa_instr = ("\n\nTest the work against the goal and the design. List every bug you find." + evidence_instr +
                    " End your answer with exactly one line: VERDICT: PASS or VERDICT: FAIL")
        plan_part = f"\n\n### Your test plan\n{test_plan}" if test_plan else ""
        tests = self.run_project_tests(0)
        report = self.step("qa0", lambda: self.delegate("qa", "assign", task_for("qa"),
                           f"{context}\n\nYour assignment:\n{task_for('qa')}\n\n### Design\n{design}{plan_part}\n\n"
                           f"### Code from {names['developer']}\n{code}{self.tests_part(tests)}{qa_instr}", "test_report"))
        report, verdict = self.check_evidence(report, tests, qa_tools, context, qa_instr, 0)
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
            tests = self.run_project_tests(rounds)
            report = self.step(f"qa{rounds}", lambda: self.delegate(
                "qa", "retest", f"Verify the fixes (round {rounds}).", f"{context}\n\nVerify the fixes for your earlier "
                f"report.\n\n### Your earlier report\n{report}\n\n### Fixed code\n{code}{self.tests_part(tests)}{qa_instr}",
                "test_report"))
            report, verdict = self.check_evidence(report, tests, qa_tools, context, qa_instr, rounds)
            self.write(f"04-qa-round{rounds}.md", report)
        self.state["verdict"] = verdict
        if verdict == "FAIL":
            self.state["blockers"].append(f"QA still failing after {rounds} fix round(s)")
            self.agent("qa", "blocked")
        self.finish_stage("test", "done" if verdict == "PASS" else "failed")

        # APPROVAL + DEPLOY (only after QA passes)
        deploy = None
        if verdict == "PASS" and "devops" in self.skip:  # nothing to deploy in this task
            self.finish_stage("approval", "skipped")
            self.finish_stage("deploy", "skipped")
        elif verdict == "PASS":
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
        ev = self.state.get("evidence") or {}
        no_deploy = "devops" in self.skip
        facts = (f"QA verdict: {verdict} after {rounds} fix round(s) "
                 f"({'verified by ' + ev['source'] if ev.get('verified') else 'NOT verified: ' + (ev.get('note') or 'no evidence')}). "
                 + (f"Deploy: not part of this task. " if no_deploy else f"Deployed: {'yes' if deploy else 'no'}. ") +
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

    # -- work packages: a complex task split into parts that run at the same time ----------------

    MAX_PACKAGES = 8

    def packages_of(self, plan):
        """The plan's work packages, cleaned: known agents that are on this task, unique ids, only known
        dependencies, no cycles. Fewer than two packages = no split (the normal flow)."""
        raw = plan.get("work_packages") if isinstance(plan, dict) else None
        if not isinstance(raw, list):
            return []
        allowed = [r for r in ROLES[1:] if r not in self.skip]
        out, ids = [], set()
        for i, p in enumerate(raw[:self.MAX_PACKAGES]):
            if not isinstance(p, dict) or not str(p.get("task") or "").strip():
                continue
            agent = str(p.get("agent") or "").strip().lower()
            if agent not in allowed:
                agent = "developer"
            pid = re.sub(r"[^A-Za-z0-9_-]", "", str(p.get("id") or "")) or f"p{i + 1}"
            while pid in ids:
                pid += "x"
            ids.add(pid)
            deps = p.get("depends_on") if isinstance(p.get("depends_on"), list) else []
            out.append({"id": pid, "title": one_line(str(p.get("title") or p["task"]), 80), "agent": agent,
                        "task": str(p["task"]).strip(), "depends_on": [str(d) for d in deps]})
        for p in out:
            p["depends_on"] = [d for d in dict.fromkeys(p["depends_on"]) if d in ids and d != p["id"]]
        # break cycles: a package may only depend on packages that can finish without it
        done, ordered = set(), []
        pending = list(out)
        while pending:
            ready = [p for p in pending if all(d in done for d in p["depends_on"])]
            if not ready:  # a cycle: drop the dependencies of the first package left
                pending[0]["depends_on"] = [d for d in pending[0]["depends_on"] if d in done]
                continue
            for p in ready:
                done.add(p["id"])
                ordered.append(p)
                pending.remove(p)
        if not any(p["agent"] == "developer" for p in ordered):
            return []  # nothing gets built: the normal flow
        return ordered if len(ordered) >= 2 else []

    def run_packages(self, packages, context, plan_text):
        """Run the work packages: each one as soon as the packages it depends on are done, the rest at the
        same time (each agent still runs at most `parallel` steps at once). Returns (design, code, test_plan, prep)."""
        names = {a.id: a.name for a in self.team.agents}
        with self.lock:
            self.state["packages"] = [{**p, "status": "todo", "started_at": None, "finished_at": None} for p in packages]
        state_of = {p["id"]: p for p in self.state["packages"]}
        self.emit("packages", {"packages": self.state["packages"]})
        self.write("01-work-packages.json", json.dumps(packages, indent=2, ensure_ascii=False))
        has_design = any(p["agent"] == "architect" for p in packages)
        if not has_design:
            self.finish_stage("design", "skipped")
        self.stage("design" if has_design else "code")
        results = {}

        def set_status(pid, status):
            with self.lock:
                st = state_of[pid]
                st["status"] = status
                st["started_at" if status == "working" else "finished_at"] = now()
            self.emit("package", dict(state_of[pid]))

        def job(p):
            set_status(p["id"], "working")
            inputs = "".join(f"\n\n### {names[results_of['agent']]} finished {d}: {results_of['title']}\n{results[d]}"
                             for d in p["depends_on"] for results_of in [next(x for x in packages if x["id"] == d)])
            others = "\n".join(f"- {x['id']} ({names[x['agent']]}): {x['title']}" for x in packages if x["id"] != p["id"])
            kind = {"architect": "design", "developer": "code", "qa": "test_plan", "devops": "deploy_prep"}[p["agent"]]
            extra = {"qa": " Prepare the tests (cases and test code); do not give a verdict yet: the full test "
                           "round comes after the build.",
                     "devops": " Prepare only: do not deploy yet, that waits for QA and the CEO."}.get(p["agent"], "")
            try:
                out = self.step(f"pkg-{p['id']}", lambda: self.delegate(
                    p["agent"], "assign", f"{p['id']}: {p['title']}",
                    f"{context}\n\nThe Team Lead split this task into work packages that run at the same time. "
                    f"Yours is {p['id']}: {p['title']}\n\n{p['task']}{extra}\n\nOther packages (done by others, "
                    f"do not do them):\n{others}{inputs}", kind))
            except BaseException:
                set_status(p["id"], "failed")
                raise
            set_status(p["id"], "done")
            return out

        pending = {p["id"]: p for p in packages}
        running = {}
        errors = []
        with ThreadPoolExecutor(max_workers=len(packages), thread_name_prefix=f"pkg-{self.id}") as pool:
            while pending or running:
                if not errors:
                    for pid, p in list(pending.items()):
                        if all(d in results for d in p["depends_on"]):
                            running[pool.submit(job, p)] = pid
                            del pending[pid]
                if not running:
                    break
                finished, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for f in finished:
                    pid = running.pop(f)
                    if f.exception() is not None:
                        errors.append(f.exception())
                    else:
                        results[pid] = f.result()
                if has_design and all(p["id"] in results for p in packages if p["agent"] == "architect") \
                        and self.state["stages"].get("design") == "active":
                    self.finish_stage("design")
                    self.stage("code")
        if errors:
            cancelled = [e for e in errors if isinstance(e, FlowCancelled)]
            raise (cancelled or errors)[0]

        def joined(agent):
            parts = [f"## {p['id']}: {p['title']}\n{results[p['id']]}" for p in packages if p["agent"] == agent]
            return "\n\n".join(parts) or None
        design = joined("architect") or f"(No separate design: follow the Team Lead's plan.)\n\n{plan_text}"
        code, test_plan, prep = joined("developer"), joined("qa"), joined("devops")
        self.write("02-architect.md", design)
        self.write("03-developer.md", code)
        if test_plan:
            self.write("03-qa-test-plan.md", test_plan)
        if prep:
            self.write("03-devops-prep.md", prep)
        if self.state["stages"].get("design") == "active":
            self.finish_stage("design")
        self.finish_stage("code")
        return design, code, test_plan, prep

    # -- triage and the fast lane -----------------------------------------------------------------

    def can_run(self, agent_id):
        h = self.team.by_id[agent_id].harness
        return bool(h.has_tools and h.permissions != "plan")

    def route(self):
        """How this task is handled: {"route": answer|direct|team, "agent", "agents", "task", "reason", "source"}.
        The Team Lead decides with one short call (no skills, no memory) unless the task's mode or the
        project says otherwise. Kept in state["route"] and as a checkpoint."""
        if self.mode == "full" or (self.mode == "auto" and not self.fast_lane):
            r = {"route": "team", "reason": "full team flow (task mode)" if self.mode == "full" else
                 "full team flow (project.fast_lane is off)", "source": "settings"}
        else:
            self.agent("lead", "working", "Decide who is needed")
            try:
                text = self.step("route", lambda: self.work("lead", self.triage_prompt(), "Decide who is needed",
                                                             "triage", light=True, memory=False))
                r = self.parse_route(extract_json(text) or {})
            except (FlowCancelled, BudgetExceeded):
                raise
            except Exception as e:  # triage is a shortcut: when it fails, the full flow runs
                r = {"route": "team", "reason": f"triage failed ({type(e).__name__}): full team flow", "source": "fallback"}
        if r["route"] == "team":
            agents = r.get("agents") or []
            for role in ("architect", "devops"):
                if agents and role not in agents:
                    self.skip.add(role)
            if self.mode == "quick":
                self.skip |= {"architect", "devops"}
            r["agents"] = [x for x in ROLES[1:] if x not in self.skip]
        with self.lock:
            self.state["route"] = r
        self.emit("route", r)
        names = {a.id: a.name for a in self.team.agents}
        who = (names["lead"] if r["route"] == "answer" else names[r["agent"]] if r["route"] == "direct"
               else ", ".join(names[x] for x in r["agents"]))
        self.write("01-route.md", f"Route: {r['route']} ({who})\nWhy: {r.get('reason') or '-'}\n")
        return r

    def triage_prompt(self):
        team = self.team
        lines = []
        for r in ROLES[1:]:
            a = team.by_id[r]
            lines.append(f"- {r}: {a.name} - {a.main_task}; "
                         + ("runs commands and changes files on this machine" if self.can_run(r)
                            else "cannot run commands (plans and writes text only)"))
        team_routes = ("" if self.mode == "quick" else
                       '- "team": real software work that needs building AND testing (a feature, an app, a bug fix '
                       'across files). List only the specialists it needs in "agents": developer and qa always; '
                       'architect only for a new system or a large change; devops only when something must be '
                       'deployed or set up on servers.\n')
        return (f"{self.goal_block}\n\nYou are the Team Lead. Decide who is needed for this request. Do NOT do the "
                "work now and do not plan it in detail. Pick the fastest route that does the job properly:\n"
                '- "answer": you can answer the CEO yourself from what you know (a question, an explanation, advice); '
                'put the full answer in "answer".\n'
                '- "direct": ONE specialist can do it in one go: a command or a few, an operational job (an SSH key, '
                'installing a package, checking a server, a service restart, a git action), a config change, a small '
                'script or a one-file fix. Name the agent in "agent" and its task in "task".\n'
                + team_routes +
                f"\nYour team:\n" + "\n".join(lines) + self.servers_note() + "\n\nAnswer with only a JSON object:\n"
                '{"route": "answer|direct' + ("" if self.mode == "quick" else "|team") + '", "agent": "<for direct>", '
                '"agents": ["<for team>"], "task": "<for direct: the exact task>", "reason": "<one short sentence>", '
                '"answer": "<for answer>"}')

    def servers_note(self):
        try:
            rows = servers.overview(self.team.cfg)
        except servers.ServerError:
            return ""
        return (f"\n\nServers the team can reach over SSH (a task about one of them goes to an agent that can "
                f"reach it):\n{rows}") if rows else ""

    def parse_route(self, data):
        route = str(data.get("route") or "").strip().lower()
        reason = one_line(str(data.get("reason") or ""), 200)
        r = {"route": route, "reason": reason, "source": "team lead"}
        if route == "answer" and str(data.get("answer") or "").strip():
            r["answer"] = str(data["answer"]).strip()
            return r
        agent = str(data.get("agent") or "").strip().lower()
        if route == "direct" or self.mode == "quick":
            if agent not in ROLES[1:] or agent in self.skip:
                agent = next((x for x in ("devops", "developer") if x not in self.skip and self.can_run(x)), "developer")
            return {**r, "route": "direct", "agent": agent, "task": str(data.get("task") or "").strip() or self.goal}
        agents = data.get("agents") if isinstance(data.get("agents"), list) else []
        return {**r, "route": "team", "agents": [str(x).strip().lower() for x in agents if str(x).strip()],
                "reason": reason or "full team flow"}

    def _skip_stages(self, *keys):
        for k in keys:
            self.finish_stage(k, "skipped")

    def _quick_report(self, text, who, result):
        """The CEO report of a fast-lane task, from the work itself (no extra call)."""
        self.stage("report")
        rep = {"current_goal": one_line(self.goal, 40), "active_task": "Quick task", "recent_result": result,
               "next_action": "Review the result", "summary": text, "blocker_list": [],
               "route": self.state["route"]["route"], "agent": self.team.by_id[who].name}
        rep.update(self._facts(None, False))
        self.state["report"] = rep
        self.write("99-ceo-report.json", json.dumps(rep, indent=2, ensure_ascii=False))
        self.bus.send("lead", "ceo", "report", text, report=rep, route=self.state["route"]["route"], agent=who)
        self.agent("lead", "done")
        self.finish_stage("report")

    def _answer(self, route):
        self.agent("lead", "working", "Answer the CEO")
        self.write("01-answer.md", route["answer"])
        self.finish_stage("plan")
        self._skip_stages("design", "code", "test", "approval", "deploy")
        self._quick_report(route["answer"], "lead", "Answered")

    def _direct(self, route):
        agent_id, task = route["agent"], route["task"]
        self.agent("lead", "waiting", f"Waits for {self.team.by_id[agent_id].name}")
        self.finish_stage("plan")
        self._skip_stages("design")
        self.stage("code")
        how = ("Do it now with your tools, check that it worked, then answer briefly: what you did (the commands), "
               "the result, and anything the CEO must still do." if self.can_run(agent_id) else
               "You cannot run commands here: give the exact commands or steps for the CEO, briefly.")
        out = self.step("direct", lambda: self.delegate(
            agent_id, "assign", task,
            f"{self.goal_block}\n\nThe Team Lead gave this task straight to you as a quick job: no design, test or "
            f"deploy rounds, so get it right yourself.\n\nYour task:\n{task}\n\n{how}\n{SECRETS_RULE}",
            "result", light=True))
        self.write("03-direct.md", out)
        self.finish_stage("code")
        self._skip_stages("test", "approval", "deploy")
        self._quick_report(out, agent_id, f"Done by {self.team.by_id[agent_id].name}"[:40])

    # -- evidence: a PASS must rest on tests that really ran ------------------------------------

    def run_project_tests(self, round_no):
        """BABD itself runs the project's test_command in the worktree (if the project has one)."""
        cmd = (self.project or {}).get("test_command")
        if not cmd or not self.workspace:
            return None
        self.emit("tests", {"round": round_no, "command": cmd, "status": "running"})
        result = projects.run_tests(cmd, self.workspace["dir"])
        with self.lock:
            self.state.setdefault("tests", []).append({"round": round_no, **result})
        self.write(f"04-tests-round{round_no}.txt", f"$ {cmd}\nexit code {result['exit']}\n\n{result['output']}\n")
        self.emit("tests", {"round": round_no, "command": cmd, "exit": result["exit"]})
        return result

    @staticmethod
    def tests_part(tests):
        if not tests:
            return ""
        return (f"\n\n### BABD ran the project's tests in the workspace\n$ {tests['command']}\nexit code {tests['exit']} "
                f"({tests['seconds']} s)\n```\n{tests['output'] or '(no output)'}\n```")

    def check_evidence(self, report, tests, qa_tools, context, qa_instr, round_no):
        """(report, verdict) after checking the PASS rests on evidence: the project's tests (when BABD
        ran them) decide; else QA's EVIDENCE section (asked for once more when missing)."""
        verdict = parse_verdict(report)
        require = bool((self.team.cfg.get("project") or {}).get("require_evidence", False))
        ev = {"round": round_no, "verified": False, "source": None, "note": ""}
        if tests is not None:
            ev.update(source="project tests", verified=tests["exit"] == 0,
                      note=f"`{tests['command']}` exit code {tests['exit']}")
            if verdict == "PASS" and tests["exit"] != 0:
                verdict = "FAIL"
                ev["note"] += ": QA said PASS but the project's tests fail, so the verdict is FAIL"
        elif verdict == "PASS":
            found = evidence_of(report)
            if not found and qa_tools:
                report = self.step(f"qa{round_no}e", lambda: self.delegate(
                    "qa", "evidence_request", "Show the evidence for your PASS.",
                    f"{context}\n\n### Your report\n{report}\n\nYou gave a PASS without evidence. Run the tests now "
                    f"and show the real commands and outputs.{qa_instr}", "test_report"))
                verdict, found = parse_verdict(report), evidence_of(report)
            if found:
                ev.update(source="QA evidence", verified=True, note="QA showed the commands it ran and their output")
            else:
                ev["note"] = ("QA has no tools to run tests (direct API)" if not qa_tools else
                              "QA gave no evidence that tests ran")
                if require and verdict == "PASS":
                    verdict = "FAIL"
                    ev["note"] += "; project.require_evidence turns the PASS into a FAIL"
        with self.lock:
            self.state["evidence"] = ev
        self.emit("evidence", ev)
        return report, verdict

    def finish_workspace(self):
        """Commit the task's work on its branch, and merge it per the project's merge policy."""
        policy = self.project["merge"]
        passed = self.state["status"] == "done" and self.state["verdict"] == "PASS"
        approved = not self.state["approval"] or self.state["approval"].get("result") == "approved"
        merge = passed and (policy == "on_pass" or (policy == "on_approval" and approved))
        result = projects.finish(self.project, self.workspace, f"babd: {one_line(self.goal, 72)} (task {self.id})", merge)
        good = self.state["status"] == "done" and self.state["verdict"] != "FAIL" and approved
        if policy == "pr" and result.get("commit") and good:
            from . import github
            rep = self.state.get("report") or {}
            body = (f"Task `{self.id}` by the BABD team.\n\n**Goal:** {self.goal}\n\n"
                    f"**QA:** {self.state.get('verdict') or 'no QA round (fast lane)'}"
                    + (f" · evidence: {(self.state.get('evidence') or {}).get('note')}" if self.state.get("evidence") else "")
                    + f"\n\n{rep.get('summary') or ''}")
            try:
                result["pr"] = github.open_pr(self.project, self.workspace, f"{one_line(self.goal, 90)} (babd {self.id})",
                                              body, self.team.cfg.get("project"))
                result["note"] = f"pull request #{result['pr']['number']} opened"
            except github.GitHubError as e:
                result["note"] = f"{result.get('note') + '; ' if result.get('note') else ''}no pull request: {e}"
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
        finished = deployed or self.quick_route or (verdict == "PASS" and "devops" in getattr(self, "skip", ()))
        if finished and not self.state["blockers"]:
            status = "DONE"
        elif self.state["blockers"]:
            status = "BLOCKED"
        else:
            status = "ACTIVE"
        return {"status": status, "progress": 100 if finished else self.state["progress"],
                "approval_needed": 1 if pending else 0, "blockers": len(self.state["blockers"]),
                "qa_verdict": verdict, "fix_rounds": self.state["qa_rounds"], "deployed": deployed,
                "verified": bool((self.state.get("evidence") or {}).get("verified")),
                "blocker_list": self.state["blockers"]}
