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
import secrets
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import flow
from ..config import ROOT, load_config, resolve_api_key, save_config, set_env_var
from .. import superpowers
from ..gbrain import BrainError, GBrain
from ..harness import HARNESS_OPTIONS, HARNESSES, create_harness, harness_config, select_harness
from ..log import add_listener, log
from ..team import Agent, Team, apply_run_to_config

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
EDITABLE_AGENT_FIELDS = ("name", "short_name", "status", "main_task", "sub_tasks", "skills", "telegram", "superpowers")
LLM_FIELDS = ("provider", "api", "base_url", "model", "api_key_env", "effort", "max_tokens", "refusal_fallback")


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
        self.run = None            # the active flow.Run
        self.run_thread = None
        self.approval = None       # (threading.Event, result dict) while the run waits for the CEO
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
            "superpowers": {"catalog": superpowers.catalog(), "steps": superpowers.STEP_SKILLS,
                            "defaults": superpowers.DEFAULT_ASSIGNMENT,
                            "enabled": superpowers.enabled(cfg["project"])},
            "workflow": cfg.get("workflow", []),
            "agents": [public_agent(a) for a in cfg["agents"]],
            "harnesses": {k: {"label": c.label, "doc": (c.__doc__ or "").strip().splitlines()[0],
                              "defaults": c.defaults, "options": [list(o) for o in HARNESS_OPTIONS.get(k, [])]}
                          for k, c in HARNESSES.items()},
            "flow": {"stages": [{"key": k, "label": l, "owner": o} for k, l, o, _ in flow.STAGES],
                     "routes": sorted(list(r) for r in flow.ROUTES)},
            "run": self.run_summary(),
            "runs": self.history(),
            "jobs": sorted(self.jobs.values(), key=lambda j: j["started"], reverse=True)[:30],
        }

    def update_agent(self, agent_id, body):
        with self.cfg_lock:
            cfg = self.load()
            a = self.agent_cfg(cfg, agent_id)
            if "superpowers" in body:
                known = set(superpowers.skill_names())
                unknown = [n for n in body["superpowers"] if n not in known]
                if unknown:
                    raise ApiError(400, f"unknown superpowers skill: {', '.join(unknown)}")
            for k in EDITABLE_AGENT_FIELDS:
                if k in body:
                    a[k] = body[k]
            if "llm" in body:
                for k in LLM_FIELDS:
                    if k in body["llm"]:
                        v = body["llm"][k]
                        if v in ("", None):
                            a["llm"].pop(k, None)
                        else:
                            a["llm"][k] = v
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
            if "superpowers" in body:
                sp = p.setdefault("superpowers", {})
                for k in ("enabled", "enforce"):
                    if k in body["superpowers"]:
                        sp[k] = bool(body["superpowers"][k])
            if "gbrain" in body:
                g = p.setdefault("gbrain", {})
                for k in ("enabled", "strict", "allow_cloud"):
                    if k in body["gbrain"]:
                        g[k] = bool(body["gbrain"][k])
            if "max_fix_rounds" in body:
                p["max_fix_rounds"] = max(0, min(5, int(body["max_fix_rounds"])))
            self.save(cfg)
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

    # -- team runs ---------------------------------------------------------------------------

    def run_summary(self):
        if not self.run:
            return None
        s = self.run.state
        return {k: s[k] for k in ("id", "goal", "status", "stage", "progress", "started_at", "finished_at",
                                  "error", "agents", "stages", "qa_rounds", "verdict", "approval", "deployed",
                                  "blockers", "report", "memory", "skills")} | {"messages": s["messages"]}

    def history(self):
        out = []
        if os.path.isdir(flow.RUNS_DIR):
            for rid in sorted(os.listdir(flow.RUNS_DIR), reverse=True)[:20]:
                p = os.path.join(flow.RUNS_DIR, rid, "state.json")
                if os.path.exists(p):
                    try:
                        with open(p) as f:
                            s = json.load(f)
                        out.append({k: s.get(k) for k in ("id", "goal", "status", "started_at", "finished_at",
                                                          "verdict", "deployed")})
                    except (OSError, json.JSONDecodeError):
                        continue
        return out

    def load_run(self, run_id):
        if self.run and self.run.id == run_id:
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
        return s

    def start_run(self, goal, auto_approve=False, update_dashboard=True):
        goal = (goal or "").strip()
        if not goal:
            raise ApiError(400, "goal is empty")
        if self.run_thread and self.run_thread.is_alive():
            raise ApiError(409, "a team run is already in progress")
        team = Team(self.load(), log=lambda m: None)

        def approver(request):
            if auto_approve:
                return True, "auto-approved from the dashboard"
            ev, result = threading.Event(), {}
            self.approval = (ev, result)
            self.hub.publish("approval", {"run": run.id, **request})
            while not ev.wait(1):
                if run.cancelled.is_set():
                    return False, "run cancelled"
            self.approval = None
            return result.get("approved", False), result.get("note", "")

        def on_event(kind, data):
            self.hub.publish("run", {"event": kind, "data": data, "summary": self.run_summary()})

        run = flow.Run(team, goal, approver=approver, on_event=on_event)
        self.run = run

        def work():
            state = run.execute()
            if update_dashboard and state.get("report"):
                with self.cfg_lock:
                    self.save(apply_run_to_config(self.load(), state))

        self.run_thread = threading.Thread(target=work, daemon=True, name="team-run")
        self.run_thread.start()
        return self.run_summary()

    def resolve_approval(self, run_id, approved, note=""):
        if not self.run or self.run.id != run_id or not self.approval:
            raise ApiError(409, "this run is not waiting for approval")
        ev, result = self.approval
        result.update(approved=bool(approved), note=str(note or "")[:300])
        ev.set()
        return {"ok": True}

    def cancel_run(self, run_id):
        if not self.run or self.run.id != run_id:
            raise ApiError(404, "no such active run")
        self.run.cancelled.set()
        if self.approval:
            self.approval[0].set()
        return {"ok": True, "note": "the run stops after the current agent step"}


def make_handler(dash, token, allowed_hosts):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BABD-Dashboard"

        def log_message(self, *a):
            pass

        # -- helpers -------------------------------------------------------------------------

        def send_json(self, status, body):
            data = json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
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
            if path.endswith(".html"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self'; img-src 'self' data:; "
                                 "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                                 "font-src https://fonts.gstatic.com; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                raise ApiError(413, "request too large")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise ApiError(400, "invalid JSON")
            if not isinstance(data, dict):
                raise ApiError(400, "expected a JSON object")
            return data

        def authorized(self, query):
            host = (self.headers.get("Host") or "").lower()
            if allowed_hosts and host not in allowed_hosts:
                return False
            given = self.headers.get("X-BABD-Token") or (query.get("token") or [""])[0]
            return secrets.compare_digest(given, token)

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
                return self.send_json(401, {"error": "missing or wrong dashboard token"})
            try:
                if method == "GET" and path == "/api/events":
                    return self.events()
                result = self.api(method, path.split("/")[2:])
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
            if parts[:1] == ["runs"]:
                if method == "POST" and len(parts) == 1:
                    b = self.body()
                    return d.start_run(b.get("goal"), bool(b.get("auto_approve")), b.get("update_dashboard", True))
                if method == "GET" and len(parts) == 2:
                    return d.load_run(parts[1])
                if method == "POST" and parts[2:] == ["approve"]:
                    b = self.body()
                    return d.resolve_approval(parts[1], b.get("approved"), b.get("note", ""))
                if method == "POST" and parts[2:] == ["cancel"]:
                    return d.cancel_run(parts[1])
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


def serve(host="127.0.0.1", port=8800, open_browser=True, token=None, cfg_path=None):
    token = token or secrets.token_urlsafe(24)
    dash = Dashboard(cfg_path)
    local = host in ("127.0.0.1", "localhost", "::1")
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} if local else None
    server = ThreadingHTTPServer((host, port), make_handler(dash, token, allowed))
    server.daemon_threads = True
    url = f"http://{'127.0.0.1' if local else host}:{server.server_port}/?token={token}"
    print(f"BABD dashboard: {url}\n(keep this URL private: the token gives full control of the agents)", flush=True)
    if not local:
        print("warning: listening on a non-local address; anyone who gets the URL controls the agents.", flush=True)
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
