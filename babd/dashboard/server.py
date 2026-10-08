"""BABD dashboard: a local web panel to configure, set up, command and watch the agents.

Python standard library only. Listens on 127.0.0.1 by default; every /api call needs the token
printed at start-up (sent as the X-BABD-Token header, or ?token= for the event stream), and the
Host header must be the dashboard's own address, so other web pages can't drive it.
"""
import copy
import json
import mimetypes
import os
import queue
import re
import secrets
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import flow
from ..config import ROOT, load_config, resolve_api_key, resolve_env, save_config, set_env_var
from .. import permissions, projects, skillpacks, taskdocs, telegram
from .auth import Security, verify_password
from ..gbrain import BrainError, GBrain
from ..harness import HARNESS_OPTIONS, HARNESSES, create_harness, harness_config, select_harness
from ..log import add_listener, log
from ..team import Agent, Team, apply_run_to_config

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
EDITABLE_AGENT_FIELDS = ("name", "short_name", "status", "main_task", "sub_tasks", "skills", "telegram")
DEFAULT_PARALLEL_TASKS = 3
TASK_FIELDS = ("id", "goal", "status", "stage", "stages", "progress", "started_at", "finished_at", "error", "verdict",
               "deployed", "qa_rounds", "blockers", "approval", "agents", "steps", "documents", "workspace", "usage",
               "evidence", "task_options", "route", "paused", "packages", "question", "questions")
LLM_FIELDS = ("provider", "api", "base_url", "model", "api_key_env", "effort", "max_tokens", "refusal_fallback", "fallback")
FALLBACK_FIELDS = ("model", "base_url", "api", "api_key_env", "provider")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class EventHub:
    """Fan-out of server events to every open /api/events stream."""

    def __init__(self):
        self.clients = set()
        self.lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)

    def publish(self, kind, data):
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait((kind, data))
            except queue.Full:  # a stalled browser tab must not block the team
                pass


def public_agent(a):
    """Agent config for the browser: never includes key values."""
    a = copy.deepcopy(a)
    llm = a.get("llm", {})
    llm["api_key_set"] = bool(resolve_api_key(llm))
    llm["api_key_inline"] = bool(llm.pop("api_key", None))
    h = harness_config(a)
    a["harness"] = h
    try:
        a["harness_summary"] = create_harness(a).describe()
    except Exception as e:  # show the problem on the card instead of failing the whole page
        a["harness_summary"] = f"error: {e}"
    for sp in skillpacks.packs():  # the lists in effect (the role's recommended ones when none is set)
        a[sp.key] = sp.assigned(a)
    a["skill_status"] = skillpacks.recommendation_status(a)
    try:
        a["permissions"], a["sandbox"] = permissions.profile_of(a), permissions.sandbox_of(a)
    except permissions.PermissionsError:
        pass
    return a


class Dashboard:
    def __init__(self, cfg_path=None, regenerate_image=True):
        self.cfg_path = cfg_path
        self.regenerate_image = regenerate_image
        self.hub = EventHub()
        self.cfg_lock = threading.RLock()
        self.jobs = {}
        self.chats = {}            # agent id -> (config fingerprint, Agent) for multi-turn chat
        self.chat_locks = {}
        self.slots = flow.AgentSlots(self.load())  # how many steps each agent works on at once, all tasks
        self.tasks_lock = threading.RLock()
        self.active = {}           # run id -> {"run": flow.Run, "approval": (Event, result) | None, "options": {...}}
        self.queue = []            # tasks waiting for a free task slot (project.max_parallel_tasks)
        self.failed_starts = []    # queued tasks that could not start (e.g. a config error)
        self.last_run = None       # the run started last (the dashboard's "current run")
        self.telegram = telegram.Manager(self)
        self.telegram_on = False   # serve() turns the bots on; tests and scripts don't
        self.recover()
        add_listener(lambda source, msg: self.hub.publish("log", {"source": source, "msg": msg, "at": time.time()}))

    # -- config ------------------------------------------------------------------------------

    def load(self):
        return load_config(self.cfg_path) if self.cfg_path else load_config()

    def save(self, cfg):
        if self.cfg_path:
            save_config(cfg, self.cfg_path)
        else:
            save_config(cfg)
        if self.regenerate_image:
            try:
                sys.path.insert(0, ROOT)
                import generate_workspace
                generate_workspace.main()
            except Exception as e:  # the image is a nice-to-have; a config save must still succeed
                log(f"could not redraw workspace.svg: {e}", "dashboard")
        self.hub.publish("config", {"at": time.time()})
        if self.telegram_on:
            threading.Thread(target=self.telegram.reconcile, daemon=True).start()

    def agent_cfg(self, cfg, agent_id):
        for a in cfg["agents"]:
            if a["id"] == agent_id:
                return a
        raise ApiError(404, f"no agent {agent_id!r}")

    def state(self):
        cfg = self.load()
        return {
            "project": cfg["project"],
            "brain": GBrain(cfg["project"]).status(),
            "skillpacks": [{"key": sp.key, "title": sp.title, "source": sp.source, "url": sp.url,
                            "catalog": sp.catalog(), "steps": sp.steps, "recommended": sp.recommended,
                            "enabled": sp.enabled(cfg["project"]), "enforce": sp.enforce(cfg["project"])}
                           for sp in skillpacks.packs()],
            "general_skills": skillpacks.GENERAL_RECOMMENDED,
            "telegram": self.telegram_state(cfg),
            "projects": projects.projects(cfg),
            "permissions": {"profiles": permissions.PROFILES, "sandboxes": list(permissions.SANDBOXES),
                            "defaults": permissions.DEFAULT_PROFILE},
            "default_project": cfg["project"].get("default_project") or projects.DEFAULT_ID,
            "workflow": cfg.get("workflow", []),
            "agents": [public_agent(a) for a in cfg["agents"]],
            "harnesses": {k: {"label": c.label, "doc": (c.__doc__ or "").strip().splitlines()[0],
                              "defaults": c.defaults, "options": [list(o) for o in HARNESS_OPTIONS.get(k, [])]}
                          for k, c in HARNESSES.items()},
            "flow": {"stages": [{"key": k, "label": l, "owner": o} for k, l, o, _ in flow.STAGES],
                     "routes": sorted(list(r) for r in flow.ROUTES)},
            "run": self.run_summary(),
            "active_runs": [self.summary(ctx["run"]) for ctx in self.active_list()],
            "queue": self.queued(),
            "slots": self.slots.load(),
            "runs": self.history(),
            "jobs": sorted(self.jobs.values(), key=lambda j: j["started"], reverse=True)[:30],
        }

    def update_agent(self, agent_id, body):
        with self.cfg_lock:
            cfg = self.load()
            a = self.agent_cfg(cfg, agent_id)
            for sp in skillpacks.packs():
                if sp.key in body:
                    names = body[sp.key]
                    if not isinstance(names, list):
                        raise ApiError(400, f"{sp.key} must be a list of skill names")
                    unknown = [n for n in names if n not in sp.skill_names()]
                    if unknown:
                        raise ApiError(400, f"unknown {sp.key} skill: {', '.join(map(str, unknown))}")
                    a[sp.key] = list(dict.fromkeys(names))
            for k in EDITABLE_AGENT_FIELDS:
                if k in body:
                    a[k] = body[k]
            if "parallel" in body:
                a["parallel"] = max(1, min(8, int(body["parallel"])))
            for k, allowed in (("permissions", permissions.PROFILES), ("sandbox", permissions.SANDBOXES)):
                if k in body:
                    if body[k] not in allowed:
                        raise ApiError(400, f"{k} must be one of {', '.join(allowed)}")
                    a[k] = body[k]
            fb = (body.get("llm") or {}).get("fallback")
            if fb not in (None, ""):
                if not isinstance(fb, dict) or not str(fb.get("model") or "").strip():
                    raise ApiError(400, "llm.fallback needs at least a model")
                if fb.get("api") not in (None, "", "anthropic", "openai"):
                    raise ApiError(400, "llm.fallback.api must be anthropic or openai")
                body["llm"]["fallback"] = {k: str(fb[k]).strip() for k in FALLBACK_FIELDS if str(fb.get(k) or "").strip()}
            if "llm" in body:
                for k in LLM_FIELDS:
                    if k in body["llm"]:
                        v = body["llm"][k]
                        if v in ("", None):
                            a["llm"].pop(k, None)
                        else:
                            a["llm"][k] = v
            if body.get("telegram_token"):  # bot tokens go to .env, like API keys
                tg = a.setdefault("telegram", {})
                tg.setdefault("token_env", f"TELEGRAM_{agent_id.upper()}_BOT_TOKEN")
                set_env_var(tg["token_env"], str(body["telegram_token"]).strip())
            if body.get("api_key") is not None:
                # Keys go to .env under the agent's api_key_env name, never into agents.json.
                env_name = a["llm"].get("api_key_env") or f"{agent_id.upper()}_LLM_API_KEY"
                a["llm"]["api_key_env"] = env_name
                a["llm"].pop("api_key", None)
                set_env_var(env_name, body["api_key"].strip())
            if "harness" in body:
                h = dict(body["harness"])
                current = harness_config(a).get("type")
                kind = h.pop("type", current)
                opts = {k: v for k, v in h.items() if v not in ("", None, [])}
                if kind != current and not opts:
                    select_harness(a, kind)  # switching type: start from that harness's defaults
                else:
                    if kind not in HARNESSES:
                        raise ApiError(400, f"unknown harness {kind!r}")
                    a["harness"] = {"type": kind, **opts}
            create_harness(a)  # validate before saving
            self.save(cfg)
            self.slots.configure(cfg)
            self.chats.pop(agent_id, None)
            return public_agent(a)

    def update_project(self, body):
        with self.cfg_lock:
            cfg = self.load()
            p = cfg["project"]
            if "name" in body:
                p["name"] = str(body["name"])[:60]
            if "require_approval" in body:
                p["require_approval"] = ["deploy"] if body["require_approval"] else []
            for pack in skillpacks.packs():
                if isinstance(body.get(pack.key), dict):
                    sp = p.setdefault(pack.key, {})
                    for k in ("enabled", "enforce"):
                        if k in body[pack.key]:
                            sp[k] = bool(body[pack.key][k])
            if "gbrain" in body:
                g = p.setdefault("gbrain", {})
                for k in ("enabled", "strict", "allow_cloud"):
                    if k in body["gbrain"]:
                        g[k] = bool(body["gbrain"][k])
            if "max_fix_rounds" in body:
                p["max_fix_rounds"] = max(0, min(5, int(body["max_fix_rounds"])))
            if isinstance(body.get("retry"), dict):
                r = p.setdefault("retry", {})
                for k, lo, hi in (("attempts", 1, 10), ("base_delay", 0, 300), ("max_delay", 0, 3600)):
                    if k in body["retry"]:
                        r[k] = max(lo, min(hi, float(body["retry"][k]) if k != "attempts" else int(body["retry"][k])))
            if isinstance(body.get("budget"), dict):
                bd = p.setdefault("budget", {})
                for k in ("tokens_per_task", "cost_per_task", "tokens_per_day", "cost_per_day"):
                    if k in body["budget"]:
                        bd[k] = max(0.0, float(body["budget"][k] or 0))
            if "require_evidence" in body:
                p["require_evidence"] = bool(body["require_evidence"])
            if body.get("skills_mode") in ("full", "lean"):
                p["skills_mode"] = body["skills_mode"]
            if "max_parallel_tasks" in body:
                p["max_parallel_tasks"] = max(1, min(10, int(body["max_parallel_tasks"])))
            if "parallel_prep" in body:
                p["parallel_prep"] = bool(body["parallel_prep"])
            if "fast_lane" in body:
                p["fast_lane"] = bool(body["fast_lane"])
            self.save(cfg)
            self._pump()
            return p

    # -- background jobs (setup, check, chat) -------------------------------------------------

    def job(self, kind, fn, agent=None):
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "kind": kind, "agent": agent, "status": "running", "started": time.time(),
               "finished": None, "result": None, "error": None}
        self.jobs[jid] = job
        self.hub.publish("job", job)

        def work():
            try:
                job["result"] = fn()
                job["status"] = "done"
            except Exception as e:
                job["status"] = "failed"
                job["error"] = str(e) or type(e).__name__
                traceback.print_exc()
            job["finished"] = time.time()
            self.hub.publish("job", job)

        threading.Thread(target=work, daemon=True, name=f"job-{kind}").start()
        return job

    def setup_agents(self, agent_ids=None):
        cfg = self.load()
        results = {}
        if not agent_ids:  # the team brain first: every agent reads and writes it
            try:
                results["gbrain"] = {"ok": True, "summary": GBrain(cfg["project"]).setup()}
            except (BrainError, OSError) as e:
                results["gbrain"] = {"ok": False, "summary": str(e)}
            log(f"gbrain: {'OK' if results['gbrain']['ok'] else 'FAIL'} {results['gbrain']['summary']}", "setup")
        for a in cfg["agents"]:
            if agent_ids and a["id"] not in agent_ids:
                continue
            try:
                results[a["id"]] = {"ok": True, "summary": create_harness(a, cfg["project"]).setup()}
            except Exception as e:
                results[a["id"]] = {"ok": False, "summary": str(e)}
            log(f"{a['id']}: {'OK' if results[a['id']]['ok'] else 'FAIL'} {results[a['id']]['summary']}", "setup")
        return results

    def check(self):
        team = Team(self.load(), log=lambda m: None)
        return {k: {"ok": ok, "summary": msg.strip()[:300]} for k, (ok, msg) in team.check().items()}

    def chat(self, agent_id, message):
        cfg = self.load()
        a = self.agent_cfg(cfg, agent_id)
        fingerprint = json.dumps(a, sort_keys=True)
        lock = self.chat_locks.setdefault(agent_id, threading.Lock())
        with lock:
            cached = self.chats.get(agent_id)
            if not cached or cached[0] != fingerprint:
                cached = (fingerprint, Agent(a, GBrain(cfg["project"])))
                self.chats[agent_id] = cached
            agent = cached[1]
            reply = agent.chat(message, on_memory=lambda e: self.hub.publish("memory", e))
            return {"reply": reply, "history": agent.history}

    # -- team runs: many tasks at once ---------------------------------------------------------

    # -- surviving restarts: the queue is on disk, interrupted runs are picked up again -------------

    @property
    def queue_path(self):
        return os.path.join(flow.RUNS_DIR, "_queue.json")

    def save_queue(self):
        with self.tasks_lock:
            data = json.dumps(self.queue, ensure_ascii=False)
        os.makedirs(flow.RUNS_DIR, exist_ok=True)
        tmp = self.queue_path + ".tmp"
        with open(tmp, "w") as f:
            f.write(data)
        os.replace(tmp, self.queue_path)

    def recover(self):
        """At start-up: reload the queue, and mark runs that were running when BABD stopped as
        "interrupted" (project.auto_resume, on by default, queues them again to continue)."""
        try:
            with open(self.queue_path) as f:
                self.queue = [q for q in json.load(f) if isinstance(q, dict) and q.get("id")]
        except (OSError, ValueError):
            self.queue = []
        auto = self.load()["project"].get("auto_resume", True)
        resumed = []
        for s in self.saved_states(200):
            if s.get("status") not in LIVE_STATUSES:
                continue
            was_paused = s.get("status") == "paused" or s.get("paused")
            pid = s.get("pid")
            if pid and pid != os.getpid() and _alive(pid):
                continue  # still running in another BABD process (e.g. `babd run`)
            s.update(status="interrupted", error="BABD stopped while this task was running", finished_at=flow.now())
            settle(s)
            try:
                with open(os.path.join(flow.RUNS_DIR, s["id"], "state.json"), "w") as f:
                    json.dump(s, f, indent=2, ensure_ascii=False)
            except OSError:
                continue
            if auto and not was_paused and not any(q["id"] == s["id"] for q in self.queue):
                resumed.append(self.resume_entry(s))
        if resumed:
            log(f"resuming {len(resumed)} interrupted task(s)", "dashboard")
            self.queue = resumed + self.queue
        if self.queue:
            self.save_queue()
            self._pump()

    def resume_entry(self, s):
        opts = s.get("options") or {}
        return {"id": s["id"], "goal": s["goal"], "status": "queued", "queued_at": flow.now(), "resume": True,
                "auto_approve": bool(opts.get("auto_approve")), "update_dashboard": opts.get("update_dashboard", True),
                "docs": [], "documents": s.get("documents") or [], "project": (s.get("workspace") or {}).get("project"),
                "options": s.get("task_options") or {}}

    def resume_run(self, run_id):
        """Continue a paused task, or a failed, stopped or interrupted one from its last finished step."""
        run_id = os.path.basename(run_id)
        with self.tasks_lock:
            ctx = self.active.get(run_id)
        if ctx and ctx["run"].paused.is_set():
            self.pause_run(run_id, False)
            return self.summary(ctx["run"])
        with self.tasks_lock:
            if run_id in self.active or any(q["id"] == run_id for q in self.queue):
                raise ApiError(409, "this task is already running or queued")
        path = os.path.join(flow.RUNS_DIR, run_id, "state.json")
        if not os.path.exists(path):
            raise ApiError(404, f"no run {run_id!r}")
        with open(path) as f:
            s = json.load(f)
        if s.get("status") not in ("failed", "cancelled", "interrupted"):
            raise ApiError(409, f"only a failed, stopped or interrupted task can be resumed (this one is {s.get('status')})")
        with self.tasks_lock:
            entry = self.resume_entry(s)
            self.queue.insert(0, entry)
        self.save_queue()
        self._pump()
        with self.tasks_lock:
            ctx = self.active.get(run_id)
        return self.summary(ctx["run"]) if ctx else {**{k: v for k, v in entry.items() if k != "docs"}, "position": 1}

    def max_parallel_tasks(self):
        try:
            return max(1, int(self.load()["project"].get("max_parallel_tasks", DEFAULT_PARALLEL_TASKS)))
        except (TypeError, ValueError):
            return DEFAULT_PARALLEL_TASKS

    def active_list(self):
        with self.tasks_lock:
            return sorted(self.active.values(), key=lambda c: c["run"].state["started_at"])

    def queued(self):
        with self.tasks_lock:
            return [{**{k: v for k, v in q.items() if k != "docs"}, "position": i + 1} for i, q in enumerate(self.queue)] \
                + [{k: v for k, v in f.items() if k != "docs"} for f in self.failed_starts]

    def summary(self, run):
        s = run.snapshot()
        return {k: s.get(k) for k in ("id", "goal", "status", "stage", "progress", "started_at", "finished_at",
                                  "error", "agents", "stages", "qa_rounds", "verdict", "approval", "deployed",
                                  "blockers", "report", "memory", "skills", "steps", "documents", "workspace",
                                  "usage", "evidence", "tests", "task_options", "route", "paused", "packages", "question", "questions", "messages")}

    def run_summary(self):
        return self.summary(self.last_run) if self.last_run else None

    def history(self, limit=20):
        return [{k: s.get(k) for k in ("id", "goal", "status", "started_at", "finished_at", "verdict", "deployed")}
                for s in self.saved_states(limit)]

    def saved_states(self, limit=20):
        out = []
        if os.path.isdir(flow.RUNS_DIR):
            for rid in sorted(os.listdir(flow.RUNS_DIR), reverse=True):
                if len(out) >= limit:
                    break
                p = os.path.join(flow.RUNS_DIR, rid, "state.json")
                if os.path.exists(p):
                    try:
                        with open(p) as f:
                            out.append(json.load(f))
                    except (OSError, json.JSONDecodeError):
                        continue
        return out

    def load_run(self, run_id):
        with self.tasks_lock:
            ctx = self.active.get(run_id)
        if ctx:
            return self.summary(ctx["run"])
        if self.last_run and self.last_run.id == run_id:
            return self.run_summary()
        d = os.path.join(flow.RUNS_DIR, os.path.basename(run_id))
        if not os.path.exists(os.path.join(d, "state.json")):
            raise ApiError(404, f"no run {run_id!r}")
        with open(os.path.join(d, "state.json")) as f:
            s = json.load(f)
        msgs = []
        mp = os.path.join(d, "messages.jsonl")
        if os.path.exists(mp):
            with open(mp) as f:
                msgs = [json.loads(line) for line in f if line.strip()]
        s["messages"] = msgs
        return settle(s)

    def new_run_id(self):
        base = time.strftime("%Y%m%d-%H%M%S")
        taken = set(self.active) | {q["id"] for q in self.queue}
        rid, n = base, 1
        while rid in taken or os.path.exists(os.path.join(flow.RUNS_DIR, rid)):
            n += 1
            rid = f"{base}-{n}"
        return rid

    @staticmethod
    def read_documents(documents=None, links=None):
        """Task documents from uploads ([{name, content}]) and links ([url]), in that order."""
        docs = []
        try:
            for d in documents or []:
                if not isinstance(d, dict):
                    raise ApiError(400, "each document needs a name and its content")
                docs.append(taskdocs.from_upload(d.get("name"), d.get("content")))
            for url in links or []:
                if str(url).strip():
                    docs.append(taskdocs.from_url(str(url)))
        except taskdocs.TaskDocError as e:
            raise ApiError(400, str(e))
        if len(docs) > 20:
            raise ApiError(400, "at most 20 documents at once")
        return docs

    def telegram_state(self, cfg):
        ceo = cfg["project"].get("ceo_telegram") or {}
        return {"running": self.telegram_on, "bots": self.telegram.status(),
                "ceo": {k: ceo.get(k) for k in ("enabled", "bot_username", "token_env", "allowed_users", "notify",
                                               "daily_report_hour", "allow_groups")} | {"token_set": bool(resolve_env(ceo.get("token_env")))},
                "agents": {a["id"]: bool(resolve_env((a.get("telegram") or {}).get("token_env"))) for a in cfg["agents"]},
                "notify_options": list(telegram.NOTIFY)}

    def update_telegram(self, body):
        with self.cfg_lock:
            cfg = self.load()
            ceo = cfg["project"].setdefault("ceo_telegram", {})
            if "enabled" in body:
                ceo["enabled"] = bool(body["enabled"])
            if "bot_username" in body:
                ceo["bot_username"] = str(body["bot_username"])[:64]
            if "allowed_users" in body:
                users = body["allowed_users"]
                if isinstance(users, str):
                    users = users.replace(",", " ").split()
                ceo["allowed_users"] = [str(u).strip() for u in users if str(u).strip()][:50]
            if "notify" in body:
                ceo["notify"] = [n for n in body["notify"] if n in telegram.NOTIFY]
            if "allow_groups" in body:
                ceo["allow_groups"] = bool(body["allow_groups"])
            if "daily_report_hour" in body:
                ceo["daily_report_hour"] = max(0, min(23, int(body["daily_report_hour"])))
            if body.get("token"):
                ceo.setdefault("token_env", "TELEGRAM_CEO_BOT_TOKEN")
                set_env_var(ceo["token_env"], str(body["token"]).strip())
            self.save(cfg)
            return self.telegram_state(cfg)

    def init_telegram(self, body):
        """Initialize a bot from its token and a chat id: check the token, save it to .env, set the bot's
        command menu and description, allow and greet the chat, turn the bot on and start it.
        target "ceo" = the CEO bot, else an agent id = that agent's own bot."""
        target = str(body.get("target") or "ceo")
        chat = str(body.get("chat_id") or "").strip()
        if not re.fullmatch(r"-?\d{1,20}", chat):
            raise ApiError(400, "chat id must be a number: your Telegram user id (message @userinfobot), "
                                "or a group id starting with -")
        with self.cfg_lock:
            cfg = self.load()
            if target == "ceo":
                block, default_env, name = (cfg["project"].get("ceo_telegram") or {}), "TELEGRAM_CEO_BOT_TOKEN", "CEO"
            else:
                a = self.agent_cfg(cfg, target)
                block, default_env = (a.get("telegram") or {}), f"TELEGRAM_{target.upper()}_BOT_TOKEN"
                name = a.get("short_name") or a["name"]
            env_name = block.get("token_env") or default_env
            token = str(body.get("token") or "").strip() or resolve_env(env_name) or ""
        if not token:
            raise ApiError(400, "paste the bot token from @BotFather")
        if not re.fullmatch(r"\d{3,20}:[A-Za-z0-9_-]{3,100}", token):
            raise ApiError(400, "that is not a bot token (it looks like 123456789:AAF...)")
        if target == "ceo":
            keyboard = telegram.CEO_KEYBOARD
            about = "BABD CEO bot: give the AI team tasks, follow their progress, approve deploys, read the agents' logs."
            welcome = ("✅ BABD CEO bot is ready.\n\nSend a goal as a message, a .md file or a link: it becomes a task. "
                       "You get a live progress card for every task (who works on what, what comes next, what is "
                       "done), approvals with buttons, and reports.\n\nThe buttons below:\n"
                       + telegram.keyboard_help(keyboard, telegram.CEO_COMMANDS))
        else:
            keyboard = telegram.AGENT_KEYBOARD
            about = f"BABD {name}: chat with {name}, follow its live log, get told when it starts and finishes work."
            welcome = (f"✅ {name} bot is ready.\n\nWrite to chat with {name}. You get a message when {name} starts and "
                       f"finishes a step.\n\nThe buttons below:\n" + telegram.keyboard_help(keyboard, telegram.agent_commands(name)))
        try:
            result = telegram.initialize(token, int(chat), keyboard, about, welcome, base=self.telegram.base)
        except telegram.TelegramError as e:
            raise ApiError(400, f"Telegram refused: {e}")
        with self.cfg_lock:
            cfg = self.load()
            set_env_var(env_name, token)
            ceo = cfg["project"].setdefault("ceo_telegram", {})
            if target == "ceo":
                block = ceo
                block["notify"] = list(dict.fromkeys(list(block.get("notify") or telegram.NOTIFY) + ["Progress"]))
            else:
                block = self.agent_cfg(cfg, target).setdefault("telegram", {})
            block.update(enabled=True, token_env=env_name, bot_username="@" + (result.get("username") or ""))
            users = [str(u) for u in ceo.get("allowed_users") or []]
            if int(chat) > 0 and chat not in users:
                ceo["allowed_users"] = users + [chat]  # a private chat's id is the user's id
            if int(chat) < 0:
                ceo["allow_groups"] = True  # a group was given on purpose
            self.save(cfg)
        self.telegram.add_chat(target, chat)
        if self.telegram_on:
            self.telegram.reconcile()
        log(f"telegram {target}: initialized as @{result.get('username')}", "telegram")
        return {**result, "target": target, "buttons": sum(len(r) for r in keyboard),
                "telegram": self.telegram_state(self.load())}

    def update_projects(self, body):
        """Replace the project list (and the default project)."""
        with self.cfg_lock:
            cfg = self.load()
            if "projects" in body:
                if not isinstance(body["projects"], list):
                    raise ApiError(400, "projects must be a list")
                seen, out = set(), []
                for p in body["projects"]:
                    if not isinstance(p, dict):
                        raise ApiError(400, "each project needs at least a name")
                    clean = {k: p[k] for k in ("id", "name", "path", "repo", "branch", "merge", "push", "test_command")
                             if p.get(k) not in (None, "")}
                    try:
                        n = projects.normalize(clean)
                    except projects.ProjectError as e:
                        raise ApiError(400, str(e))
                    if projects.inside_babd(n["path"]):
                        raise ApiError(400, f"project {n['id']}: {n['path']} is inside the BABD installation")
                    if n["id"] in seen:
                        raise ApiError(400, f"two projects with the id {n['id']!r}")
                    seen.add(n["id"])
                    out.append({**clean, "id": n["id"]})
                cfg["projects"] = out
            if "default_project" in body:
                cfg["project"]["default_project"] = str(body["default_project"])
            try:
                projects.get(cfg)
            except projects.ProjectError as e:
                raise ApiError(400, str(e))
            self.save(cfg)
            return {"projects": projects.projects(cfg), "default_project": cfg["project"].get("default_project")}

    def start_run(self, goal, auto_approve=False, update_dashboard=True, docs=None, project=None, options=None):
        """Add a task. It starts now when a task slot is free, else it waits in the queue. With task
        documents, the goal may be empty: the first document's title names the task."""
        docs = list(docs or [])
        goal = (goal or "").strip() or (docs[0]["title"] if docs else "")
        if not goal:
            raise ApiError(400, "goal is empty")
        if len(goal) > 20000:
            raise ApiError(400, "goal is too long")
        cfg = self.load()
        Team(cfg, log=lambda m: None)  # a broken config fails here, not later in the queue
        try:
            project = projects.get(cfg, project)["id"] if cfg["project"].get("use_projects", True) else None
            options = flow.task_options(options, {a["id"] for a in cfg["agents"]})
        except (projects.ProjectError, flow.FlowError) as e:
            raise ApiError(400, str(e))
        with self.tasks_lock:
            entry = {"id": self.new_run_id(), "goal": goal, "status": "queued", "queued_at": flow.now(),
                     "auto_approve": bool(auto_approve), "update_dashboard": bool(update_dashboard),
                     "docs": docs, "documents": [taskdocs.summary(d) for d in docs], "project": project,
                     "options": options}
            self.queue.append(entry)
        self.save_queue()
        self.hub.publish("tasks", {"event": "queued", "task": {k: v for k, v in entry.items() if k != "docs"}})
        self._pump()
        with self.tasks_lock:
            ctx = self.active.get(entry["id"])
        if ctx:
            return self.summary(ctx["run"])
        return {**{k: v for k, v in entry.items() if k != "docs"}, "position": self.queued_position(entry["id"])}

    def start_tasks(self, goals, auto_approve=False, update_dashboard=True, docs=None, project=None, options=None):
        """Several tasks: one per goal line and one per document."""
        goals = [g.strip() for g in goals if isinstance(g, str) and g.strip()]
        docs = list(docs or [])
        if not goals and not docs:
            raise ApiError(400, "no tasks given")
        if len(goals) + len(docs) > 50:
            raise ApiError(400, "at most 50 tasks at once")
        return {"tasks": [self.start_run(g, auto_approve, update_dashboard, project=project, options=options) for g in goals]
                + [self.start_run("", auto_approve, update_dashboard, [d], project, options) for d in docs]}

    def queued_position(self, run_id):
        with self.tasks_lock:
            for i, q in enumerate(self.queue):
                if q["id"] == run_id:
                    return i + 1
        return None

    def usage_today(self):
        """Tokens and cost of every task started today (from the runs' saved state)."""
        today = time.strftime("%Y%m%d")
        total = {"input": 0, "output": 0, "cost": 0.0, "tasks": 0}
        if not os.path.isdir(flow.RUNS_DIR):
            return total
        for rid in sorted(os.listdir(flow.RUNS_DIR), reverse=True):
            if not rid.startswith(today):
                if rid[:8].isdigit() and rid[:8] < today:
                    break
                continue
            try:
                with open(os.path.join(flow.RUNS_DIR, rid, "state.json")) as f:
                    u = json.load(f).get("usage") or {}
            except (OSError, ValueError):
                continue
            total["tasks"] += 1
            total["input"] += u.get("input", 0)
            total["output"] += u.get("output", 0)
            total["cost"] = round(total["cost"] + (u.get("cost") or 0), 6)
            if u.get("estimated"):
                total["estimated"] = True
            if u.get("cost_unknown"):
                total["cost_unknown"] = True
        return total

    def budget_block(self):
        """Why no new task may start today (project.budget.*_per_day), or None."""
        b = flow.budget_of(self.load()["project"])
        if not (b["tokens_per_day"] or b["cost_per_day"]):
            return None
        reason = flow.over_budget(self.usage_today(), b["tokens_per_day"], b["cost_per_day"])
        return f"daily budget reached: {reason}; queued tasks wait until tomorrow or a higher budget" if reason else None

    def _pump(self):
        """Start queued tasks while fewer than max_parallel_tasks are busy. A task waiting for the CEO's
        approval does not hold a slot: the agents are free for other tasks meanwhile."""
        limit = self.max_parallel_tasks()
        started = []
        blocked = self.budget_block() if self.queue else None
        if blocked:
            if getattr(self, "_last_block", None) != blocked:
                self._last_block = blocked
                log(blocked, "budget")
                self.hub.publish("tasks", {"event": "budget", "reason": blocked})
            return
        self._last_block = None
        with self.tasks_lock:
            while self.queue:
                busy = sum(1 for c in self.active.values() if c["run"].state["status"] == "running")
                if busy >= limit:
                    break
                entry = self.queue.pop(0)
                try:
                    started.append(self._launch(entry))
                except Exception as e:  # e.g. agents.json broke while the task waited
                    self.failed_starts.append({**entry, "status": "failed", "error": f"{type(e).__name__}: {e}"})
                    self.failed_starts = self.failed_starts[-20:]
        if started or self.failed_starts:
            self.save_queue()
        for run in started:
            self.hub.publish("tasks", {"event": "started", "task": {"id": run.id, "goal": run.goal}})

    def _launch(self, entry):
        opts = entry.get("options") or {}
        team = Team(flow.apply_models(self.load(), opts.get("models") or {}), log=lambda m: None)
        ctx = {"approval": None, "question": None, "options": entry}

        def asker(request):
            ev, result = threading.Event(), {}
            ctx["question"] = (ev, result, request)
            self.hub.publish("question", request)
            self._pump()  # waiting for the CEO: the slot goes to the next task
            while not ev.wait(1):
                if run.cancelled.is_set():
                    ctx["question"] = None
                    return None
            ctx["question"] = None
            return result.get("answer")

        def approver(request):
            if entry["auto_approve"]:
                return True, "auto-approved from the dashboard"
            ev, result = threading.Event(), {}
            ctx["approval"] = (ev, result)
            self.hub.publish("approval", {"run": run.id, "goal": run.goal, **request})
            self._pump()  # this task now waits for the CEO: its slot goes to the next task
            while not ev.wait(1):
                if run.cancelled.is_set():
                    return False, "run cancelled"
            ctx["approval"] = None
            return result.get("approved", False), result.get("note", "")

        def on_event(kind, data):
            if kind == "agentlog":  # one agent's activity line: the Agent logs page appends it live
                self.hub.publish("agentlog", data)
                return
            self.hub.publish("run", {"event": kind, "data": data, "summary": self.summary(run)})

        run = flow.Run(team, entry["goal"], approver=approver, on_event=on_event, run_id=entry["id"], slots=self.slots,
                       docs=entry.get("docs"), project_id=entry.get("project"), resume=entry.get("resume", False),
                       options=None if entry.get("resume") else opts, asker=asker)
        run.state["options"] = {"auto_approve": entry["auto_approve"], "update_dashboard": entry["update_dashboard"]}
        ctx["run"] = run
        self.active[run.id] = ctx
        self.last_run = run

        def work():
            try:
                state = run.execute()
                if entry["update_dashboard"] and state.get("report"):
                    with self.cfg_lock:
                        self.save(apply_run_to_config(self.load(), state))
            finally:
                with self.tasks_lock:
                    self.active.pop(run.id, None)
                self._pump()
                self.hub.publish("tasks", {"event": "finished", "task": {"id": run.id, "status": run.state["status"]}})

        threading.Thread(target=work, daemon=True, name=f"team-run-{run.id}").start()
        return run

    def resolve_approval(self, run_id, approved, note=""):
        with self.tasks_lock:
            ctx = self.active.get(run_id)
        if not ctx or not ctx["approval"]:
            raise ApiError(409, "this run is not waiting for approval")
        ev, result = ctx["approval"]
        result.update(approved=bool(approved), note=str(note or "")[:300])
        ev.set()
        return {"ok": True}

    def answer_question(self, run_id, answer):
        """The CEO's answer to the question an agent of this task is waiting on."""
        answer = str(answer or "").strip()
        if not answer:
            raise ApiError(400, "the answer is empty")
        with self.tasks_lock:
            ctx = self.active.get(os.path.basename(run_id))
        if not ctx or not ctx.get("question"):
            raise ApiError(409, "this task is not waiting for an answer")
        ev, result, request = ctx["question"]
        result["answer"] = answer[:2000]
        ev.set()
        return {"ok": True, "question": request.get("question")}

    def open_questions(self):
        with self.tasks_lock:
            return [{**c["question"][2]} for c in self.active.values() if c.get("question")]

    def cancel_run(self, run_id):
        with self.tasks_lock:
            for i, q in enumerate(self.queue):
                if q["id"] == run_id:
                    self.queue.pop(i)
                    self.save_queue()
                    self.hub.publish("tasks", {"event": "removed", "task": {k: v for k, v in q.items() if k != "docs"}})
                    return {"ok": True, "note": "removed from the queue"}
            self.failed_starts = [f for f in self.failed_starts if f["id"] != run_id]
            ctx = self.active.get(run_id)
        if not ctx:
            raise ApiError(404, "no such active or queued task")
        ctx["run"].cancelled.set()
        ctx["run"].paused.clear()
        if ctx["approval"]:
            ctx["approval"][0].set()
        if ctx.get("question"):
            ctx["question"][0].set()
        return {"ok": True, "note": "stopping: the agent's running program is stopped now"}

    def pause_run(self, run_id, paused=True):
        """Pause a running task (agents finish the step they are on, the next steps wait) or continue it."""
        with self.tasks_lock:
            ctx = self.active.get(os.path.basename(run_id))
        if not ctx:
            raise ApiError(404, "no such running task (only a running task can be paused)")
        run = ctx["run"]
        if run.cancelled.is_set():
            raise ApiError(409, "this task is stopping")
        run.pause(paused)
        self.hub.publish("tasks", {"event": "paused" if paused else "unpaused", "task": {"id": run.id}})
        return {"ok": True, "paused": bool(paused),
                "note": ("paused: the steps already working finish, the next ones wait" if paused else "continuing")}

    # -- task board ------------------------------------------------------------------------------

    def search(self, q="", status="", project="", limit=100):
        """Saved tasks matching words in the goal, id, documents, report or project (all words must match)."""
        words = [w.lower() for w in (q or "").split() if w.strip()]
        out = []
        for s in self.saved_states(2000):
            if status and s.get("status") != status:
                continue
            if project and (s.get("workspace") or {}).get("project") != project:
                continue
            hay = " ".join([s.get("goal") or "", s.get("id") or "", json.dumps(s.get("documents") or []),
                            ((s.get("report") or {}).get("summary") or ""), json.dumps(s.get("workspace") or {})]).lower()
            if all(w in hay for w in words):
                with self.tasks_lock:
                    settle(s, set(self.active))
                out.append({k: s.get(k) for k in TASK_FIELDS} | {"steps": s.get("steps") or []})
                if len(out) >= limit:
                    break
        return out

    def report_md(self, run_id):
        from .. import reports
        d = os.path.join(flow.RUNS_DIR, os.path.basename(run_id))
        if not os.path.exists(os.path.join(d, "state.json")):
            raise ApiError(404, f"no run {run_id!r}")
        state, messages = reports.load(d)
        names = {a["id"]: a.get("short_name") or a["name"] for a in self.load()["agents"]}
        return reports.markdown(state, messages, names)

    def board(self, history=30, q=None):
        """Every task (queued, running, recent) and what each agent is doing, for the task board."""
        cfg = self.load()
        tasks = [{**q, "progress": 0, "stages": {}, "steps": [], "agents": {}} for q in self.queued()]
        seen = set()
        for ctx in self.active_list():
            s = ctx["run"].snapshot()
            seen.add(s["id"])
            tasks.append({k: s.get(k) for k in TASK_FIELDS} | {"waiting_ceo": bool(ctx["approval"]), "waiting_answer": bool(ctx.get("question"))})
        for s in self.saved_states(history):
            if s.get("id") not in seen:
                seen.add(s.get("id"))
                settle(s)
                tasks.append({k: s.get(k) for k in TASK_FIELDS} | {"steps": s.get("steps") or []})
        load = self.slots.load()
        agents = []
        for a in cfg["agents"]:
            steps = [{**st, "run": t["id"], "goal": t["goal"]} for t in tasks for st in (t.get("steps") or [])
                     if st.get("agent") == a["id"]]
            done = [st for st in steps if st.get("status") == "done"]
            secs = [st["seconds"] for st in done if isinstance(st.get("seconds"), (int, float))]
            agents.append({
                "id": a["id"], "name": a.get("short_name") or a["name"], "color": a.get("color"),
                "capacity": load.get(a["id"], {}).get("capacity", flow.parallel_of(a)),
                "active": load.get(a["id"], {}).get("active", 0),
                "working": [st for st in steps if st.get("status") == "working"],
                "queued": [st for st in steps if st.get("status") == "queued"],
                "done": len(done), "failed": sum(1 for st in steps if st.get("status") == "failed"),
                "busy_seconds": round(sum(secs), 1), "avg_seconds": round(sum(secs) / len(secs), 1) if secs else None,
                "usage": usage_sum(st.get("usage") for st in steps),
            })
        counts = {}
        for t in tasks:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        return {"now": flow.now(), "tasks": tasks, "agents": agents, "counts": counts,
                "usage_today": self.usage_today(), "budget": flow.budget_of(cfg["project"]),
                "budget_block": self.budget_block(),
                "limits": {"max_parallel_tasks": self.max_parallel_tasks(),
                           "parallel_prep": bool(cfg["project"].get("parallel_prep", True)),
                           "fast_lane": bool(cfg["project"].get("fast_lane", True))},
                "stages": [{"key": k, "label": l, "owner": o} for k, l, o, _ in flow.STAGES]}


LIVE_STATUSES = ("running", "waiting_approval", "waiting_answer", "paused")


def settle(s, active=()):
    """A saved task that no process runs any more (BABD stopped mid-step): show it as interrupted, and
    its unfinished steps as interrupted at the time the task ended, never as still running."""
    running_here = s.get("id") in active
    running_elsewhere = bool(s.get("pid")) and s["pid"] != os.getpid() and _alive(s["pid"])
    if s.get("status") in LIVE_STATUSES and not (running_here or running_elsewhere):
        s["status"] = "interrupted"
    if s.get("status") in LIVE_STATUSES:
        return s
    for st in s.get("steps") or []:
        if st.get("status") in ("working", "queued"):
            st["status"] = "interrupted"
        if st.get("status") == "interrupted" and not st.get("finished_at"):
            st["finished_at"] = s.get("finished_at") or st.get("started_at") or st.get("queued_at")
    return s


_SENT = object()  # the handler already wrote the response


def usage_sum(items):
    total = {"input": 0, "output": 0, "cost": 0.0}
    for u in items:
        if not u:
            continue
        total["input"] += u.get("input", 0)
        total["output"] += u.get("output", 0)
        total["cost"] = round(total["cost"] + (u.get("cost") or 0), 6)
        for k in ("estimated", "cost_unknown"):
            if u.get(k):
                total[k] = True
    return total


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def make_handler(dash, token, allowed_hosts, security=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BABD-Dashboard"

        def log_message(self, *a):
            pass

        # -- helpers -------------------------------------------------------------------------

        def send_text(self, text, ctype, filename):
            data = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.common_headers()
            self.end_headers()
            self.wfile.write(data)
            return _SENT

        def common_headers(self):
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            if security and security.is_https(self):
                self.send_header("Strict-Transport-Security", "max-age=31536000")

        def send_json(self, status, body, headers=()):
            data = json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.common_headers()
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path):
            if not os.path.isfile(path):
                return self.send_json(404, {"error": "not found"})
            with open(path, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.common_headers()
            if path.endswith(".html"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self'; img-src 'self' data:; "
                                 "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                 "font-src https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ApiError(400, "bad Content-Length")
            if n < 0:
                raise ApiError(400, "bad Content-Length")
            if n > 12_000_000:  # task documents can be uploaded (up to 20 x 500 KB)
                raise ApiError(413, "request too large")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "invalid JSON")
            if not isinstance(data, dict):
                raise ApiError(400, "expected a JSON object")
            return data

        def host_ok(self):
            host = (self.headers.get("Host") or "").lower()
            return not allowed_hosts or host in allowed_hosts

        def authorized(self, query):
            if not self.host_ok():
                return False
            given = self.headers.get("X-BABD-Token") or (query.get("token") or [""])[0]
            if given and secrets.compare_digest(given, token):
                return True
            return bool(security and security.login_enabled and security.sessions.valid(security.session_of(self)))

        def same_origin(self):
            """Writes with a session cookie must come from this site (SameSite=Strict, plus Origin)."""
            origin = self.headers.get("Origin")
            if not origin:
                return True
            return urlparse(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

        def auth_api(self, method, path):
            """/api/auth, /api/login, /api/logout: the only API calls without a token or session."""
            if path == "/api/auth" and method == "GET":
                return self.send_json(200, {"login": bool(security and security.login_enabled),
                                            "authenticated": self.authorized({})})
            if not (security and security.login_enabled):
                return self.send_json(404, {"error": "password login is not enabled (babd set-password)"})
            if not self.host_ok() or not self.same_origin():
                return self.send_json(403, {"error": "wrong site"})
            ip = security.client_ip(self)
            if path == "/api/login" and method == "POST":
                wait = security.limiter.blocked_for(ip)
                if wait:
                    return self.send_json(429, {"error": f"too many wrong passwords; try again in {wait} s"},
                                          [("Retry-After", str(wait))])
                try:
                    password = str(self.body().get("password") or "")
                except ApiError as e:
                    return self.send_json(e.status, {"error": str(e)})
                if not verify_password(password, security.password_hash):
                    security.limiter.fail(ip)
                    log(f"wrong dashboard password from {ip}", "dashboard")
                    return self.send_json(401, {"error": "wrong password"})
                security.limiter.reset(ip)
                sid = security.sessions.create()
                return self.send_json(200, {"ok": True}, [("Set-Cookie", security.cookie(self, sid))])
            if path == "/api/logout" and method == "POST":
                security.sessions.drop(security.session_of(self))
                return self.send_json(200, {"ok": True}, [("Set-Cookie", security.cookie(self, "", 0))])
            return self.send_json(404, {"error": "not found"})

        # -- routing -------------------------------------------------------------------------

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PUT(self):
            self.route("PUT")

        def route(self, method):
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)
            if security and not security.ip_allowed(security.client_ip(self)):
                return self.send_json(403, {"error": "this address may not use the dashboard"})
            if path in ("/api/auth", "/api/login", "/api/logout"):
                return self.auth_api(method, path)
            if method == "GET" and not path.startswith("/api/"):
                if path in ("/", "/index.html"):
                    return self.send_file(os.path.join(STATIC, "index.html"))
                if path == "/workspace.svg":
                    return self.send_file(os.path.join(ROOT, "workspace.svg"))
                if path.startswith("/static/"):
                    name = os.path.basename(path)
                    return self.send_file(os.path.join(STATIC, name))
                return self.send_json(404, {"error": "not found"})
            if not self.authorized(query):
                return self.send_json(401, {"error": "missing or wrong dashboard token",
                                            "login": bool(security and security.login_enabled)})
            if method != "GET" and not self.same_origin():
                return self.send_json(403, {"error": "request from another site"})
            try:
                if method == "GET" and path == "/api/events":
                    return self.events()
                result = self.api(method, path.split("/")[2:])
                if result is not _SENT:
                    self.send_json(200, result)
            except ApiError as e:
                self.send_json(e.status, {"error": str(e)})
            except (ValueError, KeyError, TypeError) as e:
                self.send_json(400, {"error": str(e)})
            except Exception as e:
                traceback.print_exc()
                self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

        def api(self, method, parts):
            d = dash
            if method == "GET" and parts == ["state"]:
                return d.state()
            if method == "PUT" and parts == ["project"]:
                return d.update_project(self.body())
            if method == "GET" and parts == ["brain", "recall"]:
                words = (parse_qs(urlparse(self.path).query).get("q") or [""])[0]
                if not words.strip():
                    raise ApiError(400, "type some words to recall")
                try:
                    return GBrain(d.load()["project"]).recall(words, budget_tokens=2000)
                except BrainError as e:
                    raise ApiError(503, str(e))
            if method == "POST" and parts == ["setup"]:
                return d.job("setup", d.setup_agents)
            if method == "POST" and parts == ["check"]:
                return d.job("check", d.check)
            if parts[:1] == ["agents"] and len(parts) >= 2:
                agent_id = parts[1]
                d.agent_cfg(d.load(), agent_id)
                if method == "PUT" and len(parts) == 2:
                    return d.update_agent(agent_id, self.body())
                if method == "POST" and parts[2:] == ["setup"]:
                    return d.job("setup", lambda: d.setup_agents([agent_id]), agent_id)
                if method == "POST" and parts[2:] == ["chat"]:
                    msg = str(self.body().get("message") or "").strip()
                    if not msg:
                        raise ApiError(400, "message is empty")
                    return d.job("chat", lambda: d.chat(agent_id, msg), agent_id)
                if method == "POST" and parts[2:] == ["chat", "reset"]:
                    d.chats.pop(agent_id, None)
                    return {"ok": True}
            if method == "GET" and parts == ["board"]:
                qs = parse_qs(urlparse(self.path).query)
                return d.board(history=max(1, min(500, int((qs.get("history") or ["30"])[0]))))
            if parts == ["templates"]:
                from .. import templates
                if method == "GET":
                    return {"templates": templates.list_templates()}
                if method == "POST":
                    b = self.body()
                    try:
                        return templates.save(b.get("id"), b.get("title"), b.get("body"), b.get("description", ""))
                    except templates.TemplateError as e:
                        raise ApiError(400, str(e))
            if method == "GET" and parts == ["agentlogs"]:
                from .. import agentlog
                return {"agents": agentlog.summary([a["id"] for a in d.load()["agents"]])}
            if method == "GET" and len(parts) == 3 and parts[0] == "agents" and parts[2] == "log":
                from .. import agentlog
                if parts[1] not in {a["id"] for a in d.load()["agents"]}:
                    raise ApiError(404, f"no agent {parts[1]!r}")
                qs = parse_qs(urlparse(self.path).query)
                one = lambda k: (qs.get(k) or [""])[0]  # noqa: E731
                return {"agent": parts[1], "entries": agentlog.read(
                    parts[1], max(1, min(1000, int(one("limit") or 200))), int(one("before") or 0) or None,
                    one("q"), one("type"))}
            if method == "GET" and parts == ["search"]:
                qs = parse_qs(urlparse(self.path).query)
                one = lambda k: (qs.get(k) or [""])[0]  # noqa: E731
                return {"tasks": d.search(one("q"), one("status"), one("project"), max(1, min(500, int(one("limit") or 100))))}
            if method == "POST" and parts == ["tasks"]:
                b = self.body()
                goals = b.get("goals", [])
                if not isinstance(goals, list):
                    raise ApiError(400, "goals must be a list of task descriptions")
                docs = d.read_documents(b.get("documents"), b.get("links"))
                return d.start_tasks(goals, bool(b.get("auto_approve")), b.get("update_dashboard", True), docs,
                                     b.get("project"), b.get("options"))
            if method == "PUT" and parts == ["telegram"]:
                return d.update_telegram(self.body())
            if method == "POST" and parts == ["telegram", "init"]:
                return d.init_telegram(self.body())
            if method == "PUT" and parts == ["projects"]:
                return d.update_projects(self.body())
            if parts[:1] == ["runs"]:
                if method == "POST" and len(parts) == 1:
                    b = self.body()
                    docs = d.read_documents(b.get("documents"), b.get("links"))
                    return d.start_run(b.get("goal"), bool(b.get("auto_approve")), b.get("update_dashboard", True), docs,
                                       b.get("project"), b.get("options"))
                if method == "GET" and len(parts) == 2:
                    return d.load_run(parts[1])
                if method == "GET" and parts[2:] == ["report.md"]:
                    return self.send_text(d.report_md(parts[1]), "text/markdown",
                                          f"babd-{os.path.basename(parts[1])}.md")
                if method == "GET" and parts[2:] == ["document"]:
                    path = os.path.join(flow.RUNS_DIR, os.path.basename(parts[1]), "00-task.md")
                    if not os.path.isfile(path):
                        raise ApiError(404, "this task has no task document")
                    with open(path, encoding="utf-8") as f:
                        return {"text": f.read()}
                if method == "POST" and parts[2:] == ["approve"]:
                    b = self.body()
                    return d.resolve_approval(parts[1], b.get("approved"), b.get("note", ""))
                if method == "POST" and parts[2:] == ["cancel"]:
                    return d.cancel_run(parts[1])
                if method == "POST" and parts[2:] == ["answer"]:
                    return d.answer_question(parts[1], self.body().get("answer"))
                if method == "POST" and parts[2:] == ["pause"]:
                    return d.pause_run(parts[1], True)
                if method == "POST" and parts[2:] == ["resume"]:
                    return d.resume_run(parts[1])
            raise ApiError(404, "unknown API call")

        def events(self):
            q = dash.hub.subscribe()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        kind, data = q.get(timeout=15)
                        payload = json.dumps(data, ensure_ascii=False, default=str)
                        self.wfile.write(f"event: {kind}\ndata: {payload}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                dash.hub.unsubscribe(q)

    return Handler


def serve(host="127.0.0.1", port=8800, open_browser=True, token=None, cfg_path=None, public_url=None,
          allow_ip=None, trust_proxy=False):
    token = token or secrets.token_urlsafe(24)
    security = Security(allow=allow_ip, trust_proxy=trust_proxy, https=(public_url or "").startswith("https://"))
    dash = Dashboard(cfg_path)
    dash.telegram_on = True
    dash.telegram.reconcile()  # Telegram bots whose token is set start now

    def tick():  # a queue held back (e.g. by the daily budget) is checked again every minute
        while True:
            time.sleep(60)
            try:
                dash._pump()
            except Exception as e:
                log(f"queue check failed: {e}", "dashboard")
    threading.Thread(target=tick, daemon=True, name="queue-tick").start()
    local = host in ("127.0.0.1", "localhost", "::1")
    if public_url:
        allowed = {urlparse(public_url).netloc.lower()}
        if local:  # the reverse proxy forwards to us; the terminal URL keeps working too
            allowed |= {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    else:
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} if local else None
    server = ThreadingHTTPServer((host, port), make_handler(dash, token, allowed, security))
    server.daemon_threads = True
    url = f"http://{'127.0.0.1' if local else host}:{server.server_port}/?token={token}"
    print(f"BABD dashboard: {url}\n(keep this URL private: the token gives full control of the agents)", flush=True)
    from ..config import ENV_PATH, SECRETS_BACKUP, missing_keys
    for var, ids in missing_keys(dash.load()).items():
        print(f"warning: API key {var} (agents: {', '.join(ids)}) has no value: set it in Configure -> LLM, "
              f"or in {ENV_PATH} (a copy of keys set from the dashboard is kept in {SECRETS_BACKUP})", flush=True)
    if public_url:
        print(f"public address: {public_url} ({'password login' if security.login_enabled else 'NO password set: run babd set-password'})",
              flush=True)
    if not local and not public_url:
        print("warning: listening on a non-local address without --public-url; anyone who gets the URL controls the agents.",
              flush=True)
    if not local and not security.login_enabled:
        print("warning: no dashboard password (babd set-password); remote users need the token URL.", flush=True)
    behind_https = bool(public_url and public_url.startswith("https://"))
    if not local and not behind_https:
        print("warning: not behind HTTPS: put a reverse proxy with TLS in front (see README: Remote access).", flush=True)
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
