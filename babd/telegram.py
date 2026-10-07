"""Telegram bots, run by the dashboard (long polling: no public URL or webhook needed).

CEO bot (`project.ceo_telegram`): the CEO's line to the team.
  - send a message           -> a new task (a link to a .md file becomes a task document)
  - send a .md / .txt file   -> a new task from that document (the caption, if any, is the goal)
  - /status, /tasks          -> what is running, queued, done
  - /project <id>            -> the project new tasks from this chat go to
  - /cancel <task id>        -> stop a task, or take it out of the queue
  - /resume <task id>        -> continue a failed, stopped or interrupted task
  - approvals arrive with Approve / Reject buttons; finished, failed and blocked tasks are reported
    (`notify`: "Approvals", "Blockers", "Reports", "Daily Report")

Agent bots (`agents[].telegram`): chat with that one agent, like the dashboard's Chat.

Only Telegram users listed in `project.ceo_telegram.allowed_users` (numeric ids or @usernames) are
served; anyone else is told their id so the owner can add it. Bot tokens live in .env, never in
agents.json. Chats that may receive notifications are kept in .babd/telegram.json.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

from .config import ROOT, resolve_env
from .log import log

API_BASE = os.environ.get("BABD_TELEGRAM_API", "https://api.telegram.org")
STATE_PATH = os.path.join(ROOT, ".babd", "telegram.json")
MAX_TEXT = 4000
NOTIFY = ("Approvals", "Blockers", "Reports", "Daily Report")


class TelegramError(Exception):
    pass


class API:
    def __init__(self, token, base=None):
        self.token = token
        self.base = (base or API_BASE).rstrip("/")

    def call(self, method, http_timeout=40, **params):
        data = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(f"{self.base}/bot{self.token}/{method}", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as r:
                body = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read() or b"{}")
            except ValueError:
                body = {}
            raise TelegramError(f"{method}: HTTP {e.code} {body.get('description', '')}".strip()) from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise TelegramError(f"{method}: {getattr(e, 'reason', e)}") from e
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'failed')}")
        return body.get("result")

    def download(self, file_id, max_bytes):
        info = self.call("getFile", file_id=file_id)
        if info.get("file_size") and info["file_size"] > max_bytes:
            raise TelegramError(f"the file is larger than {max_bytes // 1000} KB")
        with urllib.request.urlopen(f"{self.base}/file/bot{self.token}/{info['file_path']}", timeout=60) as r:
            data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise TelegramError(f"the file is larger than {max_bytes // 1000} KB")
        return data

    def send(self, chat_id, text, buttons=None):
        """Send text (split into several messages when long). Returns the last message."""
        text = text or "…"
        msg = None
        for i in range(0, len(text), MAX_TEXT):
            last = i + MAX_TEXT >= len(text)
            msg = self.call("sendMessage", chat_id=chat_id, text=text[i:i + MAX_TEXT], disable_web_page_preview=True,
                            reply_markup={"inline_keyboard": buttons} if (buttons and last) else None)
        return msg


class Bot(threading.Thread):
    """Long-polling loop; subclasses handle updates."""

    def __init__(self, name, token, allowed, base=None):
        super().__init__(daemon=True, name=f"telegram-{name}")
        self.api = API(token, base)
        self.label = name
        self.allowed = {str(a).lstrip("@").lower() for a in allowed or [] if str(a).strip()}
        self.stopping = threading.Event()
        self.status = {"ok": False, "detail": "starting"}
        self.offset = None
        self.poll_timeout = 25  # seconds Telegram holds a getUpdates call open (long polling)

    def is_allowed(self, user):
        if not user:
            return False
        return str(user.get("id")) in self.allowed or (user.get("username") or "").lower() in self.allowed

    def deny(self, chat_id, user):
        self.api.send(chat_id, f"Not allowed yet. Your Telegram user id is {user.get('id')}"
                               f"{' (@' + user['username'] + ')' if user.get('username') else ''}. Ask the owner to add "
                               "it in the BABD dashboard: Team settings → Telegram → Allowed users.")

    def run(self):
        try:
            me = self.api.call("getMe", http_timeout=20)
            self.status = {"ok": True, "detail": f"connected as @{me.get('username')}", "username": me.get("username")}
            log(f"telegram {self.label}: connected as @{me.get('username')}", "telegram")
        except TelegramError as e:
            self.status = {"ok": False, "detail": str(e)}
            log(f"telegram {self.label}: {e}", "telegram")
            return
        backoff = 1
        while not self.stopping.is_set():
            try:
                updates = self.api.call("getUpdates", http_timeout=40, offset=self.offset, timeout=self.poll_timeout,
                                        allowed_updates=["message", "callback_query"])
                backoff = 1
            except TelegramError as e:
                self.status = {"ok": False, "detail": str(e)}
                self.stopping.wait(min(60, backoff))
                backoff *= 2
                continue
            self.status["ok"] = True
            for u in updates or []:
                self.offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception as e:  # one bad message must not stop the bot
                    log(f"telegram {self.label}: {type(e).__name__}: {e}", "telegram")
            self.tick()

    def stop(self):
        self.stopping.set()

    def handle(self, update):
        raise NotImplementedError

    def tick(self):
        pass


def _state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


class CeoBot(Bot):
    def __init__(self, dash, token, cfg, base=None):
        super().__init__("ceo", token, cfg.get("allowed_users"), base)
        self.dash = dash
        self.notify = set(cfg.get("notify") or NOTIFY)
        self.daily_hour = int(cfg.get("daily_report_hour", 18))
        st = _state()
        self.chats = {str(c) for c in st.get("ceo_chats", [])}
        self.chat_project = st.get("chat_project", {})
        self.last_daily = st.get("last_daily", "")
        self.events = dash.hub.subscribe()
        self.notifier = threading.Thread(target=self.notify_loop, daemon=True, name="telegram-ceo-notify")

    def start(self):
        super().start()
        self.notifier.start()

    def stop(self):
        super().stop()
        self.dash.hub.unsubscribe(self.events)

    def remember_chat(self, chat_id):
        if str(chat_id) not in self.chats:
            self.chats.add(str(chat_id))
            self.persist()

    def persist(self):
        st = _state()
        st.update(ceo_chats=sorted(self.chats), chat_project=self.chat_project, last_daily=self.last_daily)
        _save_state(st)

    # -- incoming ------------------------------------------------------------------------------

    def handle(self, update):
        if "callback_query" in update:
            return self.on_button(update["callback_query"])
        msg = update.get("message") or {}
        chat, user = msg.get("chat", {}).get("id"), msg.get("from")
        if chat is None:
            return
        if not self.is_allowed(user):
            return self.deny(chat, user)
        self.remember_chat(chat)
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if msg.get("document"):
            return self.on_document(chat, msg["document"], text)
        if text.startswith("/"):
            return self.on_command(chat, text)
        if text:
            return self.on_goal(chat, text)

    def on_command(self, chat, text):
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()
        if cmd in ("/start", "/help"):
            return self.api.send(chat, "BABD CEO bot.\n\nSend a goal as a message, or a .md file, or a link to one: "
                                       "it becomes a task for the team.\n\n/status - what the team is doing\n"
                                       "/tasks - recent tasks\n/project <id> - where new tasks go\n"
                                       "/cancel <task id> - stop or unqueue a task\n/resume <task id> - continue a failed or interrupted task\n"
                                       "/templates - task templates to fill in\n/quick <goal> - fast lane: the Team Lead answers or one agent does it\n"
                                       "/full <goal> - always the whole team flow\n\n"
                                       "Plain messages: the Team Lead decides who is needed.")
        if cmd == "/status":
            return self.api.send(chat, self.status_text())
        if cmd == "/tasks":
            return self.api.send(chat, self.tasks_text())
        if cmd == "/project":
            from . import projects
            ps = projects.projects(self.dash.load())
            if not arg:
                cur = self.chat_project.get(str(chat)) or "(default)"
                return self.api.send(chat, f"New tasks go to: {cur}\nProjects: " + ", ".join(p["id"] for p in ps))
            if arg not in {p["id"] for p in ps}:
                return self.api.send(chat, f"No project {arg}. Projects: " + ", ".join(p["id"] for p in ps))
            self.chat_project[str(chat)] = arg
            self.persist()
            return self.api.send(chat, f"New tasks from this chat go to project {arg}.")
        if cmd in ("/quick", "/full"):
            mode = cmd[1:]
            if not arg:
                return self.api.send(chat, f"Usage: {cmd} <goal>")
            return self.api.send(chat, self.safe(lambda: self.start_task(chat, arg, options={"mode": mode})))
        if cmd in ("/templates", "/template"):
            from . import templates
            ts = templates.list_templates()
            if not arg:
                return self.api.send(chat, "Templates (send /template <id>, fill it in, send it back as a message or a .md file):\n"
                                     + "\n".join(f"• {t['id']} - {t['title']}: {t['description']}" for t in ts))
            return self.api.send(chat, self.safe(lambda: templates.get(arg)["body"]))
        if cmd == "/resume":
            if not arg:
                return self.api.send(chat, "Usage: /resume <task id> (a failed, stopped or interrupted task)")
            return self.api.send(chat, self.safe(lambda: f"Resuming: {self.dash.resume_run(arg)['goal']}"))
        if cmd == "/cancel":
            if not arg:
                return self.api.send(chat, "Usage: /cancel <task id> (see /tasks)")
            return self.api.send(chat, self.safe(lambda: self.dash.cancel_run(arg)["note"]))
        return self.api.send(chat, "Unknown command. /help")

    def safe(self, fn):
        try:
            return fn()
        except Exception as e:
            return f"Could not do that: {e}"

    def start_task(self, chat, goal, docs=(), options=None):
        project = self.chat_project.get(str(chat))
        task = self.dash.start_run(goal, update_dashboard=True, docs=list(docs), project=project, options=options)
        where = "started" if task.get("status") != "queued" else f"queued (#{task.get('position')})"
        return f"Task {where}: {task['goal']}\nid: {task['id']}"

    def on_goal(self, chat, text):
        from . import taskdocs
        words = text.split()
        links = [w for w in words if w.startswith(("http://", "https://"))]
        if "\n" in text and text.lstrip().startswith("#"):  # a filled-in template / Markdown: a task document
            return self.api.send(chat, self.safe(lambda: self.start_task(chat, "", [taskdocs.make("message.md", text, "telegram")])))
        if links and len(words) == len(links):  # only links: each is a task document
            for url in links:
                self.api.send(chat, self.safe(lambda u=url: self.start_task(chat, "", [taskdocs.from_url(u)])))
            return
        self.api.send(chat, self.safe(lambda: self.start_task(chat, text)))

    def on_document(self, chat, doc, caption):
        from . import taskdocs

        def go():
            name = doc.get("file_name") or "task.md"
            if not name.lower().endswith(taskdocs.TEXT_EXTENSIONS):
                return f"{name}: send a Markdown or text file (.md, .txt)"
            data = self.api.download(doc["file_id"], taskdocs.MAX_BYTES)
            d = taskdocs.make(name, taskdocs._decode(data, name), "telegram")
            return self.start_task(chat, caption, [d])
        self.api.send(chat, self.safe(go))

    def on_button(self, q):
        user, data = q.get("from"), q.get("data") or ""
        if not self.is_allowed(user):
            return self.api.call("answerCallbackQuery", callback_query_id=q["id"], text="Not allowed")
        action, _, run_id = data.partition(":")
        if action in ("approve", "reject"):
            ok = action == "approve"
            note = f"{'approved' if ok else 'rejected'} on Telegram by @{user.get('username') or user.get('id')}"
            result = self.safe(lambda: (self.dash.resolve_approval(run_id, ok, note), "done")[1])
            self.api.call("answerCallbackQuery", callback_query_id=q["id"],
                          text="Deploy approved" if ok and result == "done" else "Deploy rejected" if result == "done" else result[:190])
            m = q.get("message") or {}
            if m and result == "done":
                self.safe(lambda: self.api.call("editMessageText", chat_id=m["chat"]["id"], message_id=m["message_id"],
                                                text=(m.get("text") or "") + f"\n\n→ {note}"))

    # -- outgoing ------------------------------------------------------------------------------

    def broadcast(self, text, buttons=None):
        for chat in list(self.chats):
            try:
                self.api.send(chat, text, buttons)
            except TelegramError as e:
                log(f"telegram ceo: could not notify {chat}: {e}", "telegram")

    def notify_loop(self):
        import queue
        while not self.stopping.is_set():
            try:
                kind, data = self.events.get(timeout=5)
            except queue.Empty:
                continue
            try:
                self.on_event(kind, data)
            except Exception as e:
                log(f"telegram ceo: {type(e).__name__}: {e}", "telegram")

    def on_event(self, kind, data):
        if kind == "approval" and "Approvals" in self.notify:
            self.broadcast(f"Approval needed\n{data.get('goal', '')}\n\n{data.get('question', '')}\ntask {data.get('run')}",
                           [[{"text": "✅ Approve deploy", "callback_data": f"approve:{data.get('run')}"},
                             {"text": "❌ Reject", "callback_data": f"reject:{data.get('run')}"}]])
        elif kind == "run" and data.get("event") == "finished":
            s, d = data.get("summary") or {}, data.get("data") or {}
            status, rep = d.get("status"), d.get("report") or {}
            if status == "done" and rep.get("status") != "BLOCKED" and "Reports" in self.notify:
                foot = (f"⚡ fast lane: {rep.get('agent')}" if rep.get("route") in ("direct", "answer") else
                        f"QA {rep.get('qa_verdict', '-')} · deployed {'yes' if rep.get('deployed') else 'no'}")
                self.broadcast(f"✅ Task done: {s.get('goal')}\n{rep.get('summary') or ''}\n{foot}")
            elif "Blockers" in self.notify and (status in ("failed", "cancelled") or rep.get("status") == "BLOCKED"):
                why = d.get("error") or "; ".join(rep.get("blocker_list") or []) or status
                self.broadcast(f"⚠️ Task {status if status != 'done' else 'blocked'}: {s.get('goal')}\n{why}\ntask {s.get('id')}")

    def tick(self):
        if "Daily Report" not in self.notify or not self.chats:
            return
        now = time.localtime()
        today = time.strftime("%Y-%m-%d", now)
        if now.tm_hour >= self.daily_hour and self.last_daily != today:
            self.last_daily = today
            self.persist()
            self.broadcast("📋 Daily report\n" + self.tasks_text(today=today))

    def status_text(self):
        b = self.dash.board(history=10)
        c = b["counts"]
        lines = [f"Running {c.get('running', 0)} · waiting for you {c.get('waiting_approval', 0)} · "
                 f"queued {c.get('queued', 0)} · done {c.get('done', 0)} · failed {c.get('failed', 0)}"]
        for t in b["tasks"]:
            if t["status"] in ("running", "waiting_approval"):
                now = ", ".join(f"{st['agent']} {st['kind']}" for st in (t.get("steps") or []) if st.get("status") == "working")
                lines.append(f"• {t['goal'][:60]} — {t.get('progress', 0)}% {t.get('stage') or ''}"
                             + (f" ({now})" if now else "") + f"\n  {t['id']}")
        busy = [f"{a['name']} {a['active']}/{a['capacity']}" for a in b["agents"] if a["active"]]
        lines.append("Agents busy: " + (", ".join(busy) if busy else "none"))
        return "\n".join(lines)

    def tasks_text(self, today=None):
        b = self.dash.board(history=15)
        rows = []
        for t in b["tasks"]:
            if today and not (t.get("started_at") or t.get("queued_at") or "").startswith(today):
                continue
            rows.append(f"• [{t['status']}] {t['goal'][:60]} ({t['id']})")
        return "\n".join(rows) or "No tasks."


class AgentBot(Bot):
    """Chat with one agent."""

    def __init__(self, dash, agent_id, token, allowed, base=None):
        super().__init__(agent_id, token, allowed, base)
        self.dash, self.agent_id = dash, agent_id

    def handle(self, update):
        msg = update.get("message") or {}
        chat, user, text = msg.get("chat", {}).get("id"), msg.get("from"), (msg.get("text") or "").strip()
        if chat is None or not text:
            return
        if not self.is_allowed(user):
            return self.deny(chat, user)
        if text in ("/start", "/help"):
            return self.api.send(chat, f"Chat with the {self.agent_id} agent. /reset starts a new conversation.")
        if text == "/reset":
            self.dash.chats.pop(self.agent_id, None)
            return self.api.send(chat, "New conversation.")
        try:
            self.api.call("sendChatAction", chat_id=chat, action="typing")
        except TelegramError:
            pass
        try:
            reply = self.dash.chat(self.agent_id, text)["reply"]
        except Exception as e:
            reply = f"Error: {e}"
        self.api.send(chat, reply)


class Manager:
    """Starts, restarts and stops the bots to match the configuration."""

    def __init__(self, dash, base=None):
        self.dash, self.base = dash, base
        self.bots = {}   # key -> (fingerprint, bot)
        self.lock = threading.Lock()

    def desired(self):
        cfg = self.dash.load()
        ceo = cfg["project"].get("ceo_telegram") or {}
        allowed = ceo.get("allowed_users") or []
        want = {}
        if ceo.get("enabled") and resolve_env(ceo.get("token_env")):
            want["ceo"] = (json.dumps([resolve_env(ceo.get("token_env")), ceo], sort_keys=True),
                           lambda: CeoBot(self.dash, resolve_env(ceo["token_env"]), ceo, self.base))
        for a in cfg["agents"]:
            t = a.get("telegram") or {}
            token = resolve_env(t.get("token_env"))
            if t.get("enabled") and token:
                want[a["id"]] = (json.dumps([token, allowed], sort_keys=True),
                                 lambda a=a, token=token: AgentBot(self.dash, a["id"], token, allowed, self.base))
        return want

    def reconcile(self):
        with self.lock:
            want = self.desired()
            for key in list(self.bots):
                if key not in want or want[key][0] != self.bots[key][0]:
                    self.bots.pop(key)[1].stop()
            for key, (fp, make) in want.items():
                if key not in self.bots:
                    bot = make()
                    self.bots[key] = (fp, bot)
                    bot.start()

    def status(self):
        with self.lock:
            return {k: dict(bot.status) for k, (_, bot) in self.bots.items()}

    def stop(self):
        with self.lock:
            for _, bot in self.bots.values():
                bot.stop()
            self.bots.clear()
