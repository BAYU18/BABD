"""AI development team: agents built from agents.json, orchestrated by the Team Lead."""
import datetime

from .config import load_skill_text
from .flow import Run, extract_json  # noqa: F401  (extract_json re-exported for callers)
from .gbrain import BrainError, GBrain, format_memory, one_line
from . import resilience, skillpacks
from .harness import create_harness


class Agent:
    def __init__(self, cfg, brain=None, project=None):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg.get("short_name") or cfg["name"]
        self.harness = create_harness(cfg, project)
        self.brain = brain if brain is not None and brain.enabled else None
        if self.brain:
            self.harness.extra_env = self.brain.agent_env()  # the agent's own `gbrain` command
        self.project = project or {}
        self.skill_packs = skillpacks.agent_skills(cfg, project)  # {pack: skills}, only enabled packs
        self.superpowers = self.skill_packs.get("superpowers", [])
        self.history = []
        self.retry = resilience.settings(project)
        self.listener = resilience.Listener()  # set by the run around each step (retry events, cancel)
        self._fallback = None

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
        section = skillpacks.system_section(self.skill_packs)
        if section:
            lines.append("\n" + section)
        lines.append("\nWork concretely: produce the actual design, code, tests or steps, not a description "
                     "of what you would do. Say plainly what is still missing or blocked.")
        return "\n".join(lines)

    def light_system_prompt(self):
        """A short system prompt (no skill texts) for quick jobs: much less for the model to read."""
        return (f"You are the {self.cfg['name'].title()} of an AI software development team (BABD). "
                "A human CEO supervises the team through the Team Lead.\n"
                f"Your main task: {self.main_task}.\n"
                "This is a quick job: do it directly, without ceremony. Answer briefly with what you did and the "
                "result. Say plainly what is missing or blocked.")

    def ask(self, message, system=None, **kwargs):
        """One request to the harness, no memory (used for pings and by work()); retried on temporary
        errors, then tried on the fallback model when the agent has one."""
        return self.complete(system or self.system_prompt(), [{"role": "user", "content": message}], **kwargs)

    def complete(self, system, messages, **kwargs):
        on_retry, cancelled = self.listener.on_retry, self.listener.cancelled

        def counted(harness):
            def call():
                text = harness.complete(system, messages, **kwargs)
                self.count(harness, system, messages, text)
                return text
            return call
        try:
            return resilience.call(counted(self.harness), self.retry, on_retry, cancelled)
        except Exception as e:
            fb = self.fallback_harness()
            if fb is None or (cancelled is not None and cancelled.is_set()):
                raise
            if on_retry:
                on_retry({"fallback": fb.llm.get("model"), "error": str(e)[:300]})
            return resilience.call(counted(fb), self.retry, on_retry, cancelled)

    def count(self, harness, system, messages, reply):
        """Token use of one call (from the harness, or estimated at ~4 characters a token) and its cost
        (llm.price: USD per million input / output tokens, or what the harness reports)."""
        u = harness.take_usage()
        estimated = not u
        if estimated:
            sent = len(system) + sum(len(m["content"]) if isinstance(m.get("content"), str) else len(str(m.get("content")))
                                     for m in messages)
            u = {"input": sent // 4, "output": len(reply or "") // 4}
        u = {"input": int(u.get("input") or 0), "output": int(u.get("output") or 0), "cost": u.get("cost"),
             "estimated": estimated, "model": harness.llm.get("model")}
        price = harness.llm.get("price") or self.cfg["llm"].get("price") or {}
        if u["cost"] is None and price:
            u["cost"] = (u["input"] * float(price.get("input", 0)) + u["output"] * float(price.get("output", 0))) / 1e6
        if self.listener.on_usage:
            self.listener.on_usage(u)
        return u

    def fallback_harness(self):
        """The agent's harness on its fallback model (llm.fallback), or None."""
        fb = self.cfg.get("llm", {}).get("fallback")
        if not fb or not fb.get("model"):
            return None
        if self._fallback is None:
            llm = {k: v for k, v in self.cfg["llm"].items() if k != "fallback"}
            if fb.get("api_key_env") and "api_key" in llm:
                llm.pop("api_key")
            self._fallback = create_harness({**self.cfg, "llm": {**llm, **fb}}, self.project or None)
            self._fallback.extra_env = self.harness.extra_env
            self._fallback.skill_packs = self.harness.skill_packs
        self._fallback.cfg = {**self._fallback.cfg, "cwd": self.harness.cfg.get("cwd")}  # this run's worktree
        return self._fallback

    def work(self, prompt, *, query, page_slug, page_title, entity, provenance, task="", fact=None, on_memory=None,
             skills=(), on_skills=None, light=False, memory=True, **kwargs):
        """One task with the GBrain cycle: READ gbrain -> work -> WRITE gbrain.

        `query`: texts whose keywords select the memory to read. After the agent answers, its full
        output is saved as page `page_slug` and a one-line fact (`fact(output)` or the output's start)
        is remembered under `entity` with `provenance`. `on_memory(event)` reports both steps.
        `light`: a quick job, with the short system prompt and no skills; `memory=False`: no GBrain cycle.
        """
        if light:
            skills, kwargs = (), {**kwargs, "system": self.light_system_prompt()}
        if not self.brain or not memory:
            return self._with_skills(prompt, skills, on_skills, **kwargs)
        emit = on_memory or (lambda e: None)
        memory = self._brain_step("read", lambda: self.brain.recall(*query))
        if memory is not None:
            emit({"agent": self.id, "op": "read", "query": memory["query"], "facts": len(memory["facts"]),
                  "pages": len(memory["results"]), "at": now(),
                  "items": [f.get("fact") for f in memory["facts"]][:5] + [r.get("slug") for r in memory["results"]][:5]})
            prompt = f"{format_memory(memory)}\n\n---\n\n{prompt}"
        out = self._with_skills(prompt, skills, on_skills, **kwargs)
        summary = fact(out) if fact else f"{self.name}: {one_line(out, 240)}"
        body = f"## Task\n{task or page_title}\n\n## Output from {self.name}\n{out}"
        written = self._brain_step("write", lambda: (
            self.brain.put_page(page_slug, page_title, body, tags=("babd", self.id)),
            self.brain.remember(summary, entity, provenance)))
        if written is not None:
            emit({"agent": self.id, "op": "write", "page": page_slug, "entity": entity, "fact": summary,
                  "fact_id": (written[1] or {}).get("id"), "at": now()})
        return out

    def _with_skills(self, prompt, skills, on_skills=None, **kwargs):
        """Run the step with its skills (all packs) in the prompt; check the answer accounts for each
        one in "Skills applied:", and ask once to redo the step when one is missing (if its pack enforces)."""
        mine = skillpacks.all_names(self.skill_packs)
        skills = [s for s in skills if s in mine]
        if not skills:
            return self.ask(prompt, **kwargs)
        lean = self.project.get("skills_mode") == "lean"
        full = f"{skillpacks.step_block(skills, lean)}\n\n---\n\n{prompt}"
        out = self.ask(full, **kwargs)
        miss, retried = skillpacks.missing(out, skills), False
        if skillpacks.enforced(self.project, miss):
            retried = True
            out = self.ask(f"{full}\n\n---\n\n## Your previous answer\n{out}\n\n## Redo required\n"
                           f"You did not show how you applied: {', '.join(miss)}. Redo the task following "
                           f"{'that skill' if len(miss) == 1 else 'those skills'}, and end with the "
                           f"\"Skills applied:\" section, one line for each of: {', '.join(skills)}.", **kwargs)
            miss = skillpacks.missing(out, skills)
        if on_skills:
            on_skills({"agent": self.id, "op": "skills", "skills": skills, "missing": miss, "retried": retried,
                       "at": now()})
        return out

    def _brain_step(self, op, fn):
        try:
            return fn()
        except BrainError as e:
            if self.brain.strict:
                raise BrainError(f"{self.name}: gbrain {op} failed: {e}") from e
            return None

    def chat(self, message, on_memory=None):
        """Multi-turn conversation with this agent, also through the GBrain cycle."""
        self.history.append({"role": "user", "content": message})
        if self.brain:
            memory = self._brain_step("read", lambda: self.brain.recall(message))
            if memory is not None and on_memory:
                on_memory({"agent": self.id, "op": "read", "query": memory["query"], "facts": len(memory["facts"]),
                           "pages": len(memory["results"]), "at": now()})
            turns = list(self.history)
            if memory is not None:
                turns[-1] = {"role": "user", "content": f"{format_memory(memory)}\n\n---\n\n{message}"}
            reply = self.complete(self.system_prompt(), turns)
            fact = f"CEO asked {self.name}: {one_line(message, 140)} -> {one_line(reply, 200)}"
            written = self._brain_step("write", lambda: self.brain.remember(
                fact, f"babd/agents/{self.id}", f"babd chat with {self.name}, {now()}"))
            if written is not None and on_memory:
                on_memory({"agent": self.id, "op": "write", "entity": f"babd/agents/{self.id}", "fact": fact, "at": now()})
        else:
            reply = self.complete(self.system_prompt(), self.history)
        self.history.append({"role": "assistant", "content": reply})
        return reply


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Team:
    def __init__(self, cfg, log=print, brain=None):
        self.cfg = cfg
        self.brain = brain or GBrain(cfg.get("project"))
        self.agents = [Agent(a, self.brain, cfg.get("project")) for a in cfg["agents"]]
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
