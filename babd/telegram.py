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
served; anyone else is told their id so the owner can add it. A @username is tied to the numeric id
of the first account that uses it (usernames can be changed and taken by someone else); after that
only that account is served under it. The bots answer in private chats only, unless
`ceo_telegram.allow_groups` is on (in a group, everyone in it reads the replies and reports). Bot tokens live in .env, never in
agents.json. Chats that may receive notifications are kept in .babd/telegram.json.
"""
import html
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
NOTIFY = ("Progress", "Approvals", "Blockers", "Reports", "Daily Report")
LOG_EVERY = 3          # seconds between live-log updates
LOG_MINUTES = 10       # a live log follows the agent this long, then stops (send /log again)
CARD_EVERY = 3         # seconds between updates of a task's progress card
LOG_LINES = 30

# The bots' command menus (Telegram shows them under the "/" button and the menu button).
CEO_COMMANDS = [
    ("help", "All commands"),
    ("status", "What the team is doing now"),
    ("agents", "Every agent and what it works on"),
    ("log", "Live log of an agent (updates every 3 s)"),
    ("tasks", "Recent tasks"),
    ("report", "Report of a task: /report <task id>"),
    ("quick", "Fast lane: /quick <goal>"),
    ("full", "Whole team: /full <goal>"),
    ("pause", "Pause a task: /pause <task id>"),
    ("resume", "Continue a task: /resume <task id>"),
    ("cancel", "Stop a task: /cancel <task id>"),
    ("project", "Where new tasks go: /project <id>"),
    ("templates", "Task templates to fill in"),
    ("notify", "The notifications this bot sends"),
]


def agent_commands(name):
    return [("help", "All commands"), ("status", f"What {name} is doing now"),
            ("log", f"Live log of {name} (updates every 3 s)"), ("tasks", f"Recent work of {name}"),
            ("reset", "Start a new conversation")]


def initialize(token, chat_id, commands, description, welcome, base=None):
    """Set a bot up: check the token, set its command menu and description, greet the chat.
    Returns {"username", "welcome_sent", "note"}; raises TelegramError for a bad token."""
    api = API(token, base)
    me = api.call("getMe", http_timeout=20)
    api.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])
    for method, key, text in (("setMyDescription", "description", description),
                              ("setMyShortDescription", "short_description", description[:120])):
        try:
            api.call(method, **{key: text})
        except TelegramError:
            pass  # optional
    out = {"username": me.get("username"), "welcome_sent": False, "note": ""}
    try:
        api.send(chat_id, welcome)
        out["welcome_sent"] = True
    except TelegramError as e:
        out["note"] = (f"The menu is set, but the bot could not write to chat {chat_id} ({e}). Open "
                       f"@{me.get('username')} in Telegram, press Start, then Initialize again.")
    return out


def _clip(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _dur(sec):
    sec = int(max(0, sec or 0))
    return f"{sec // 3600}h{sec // 60 % 60:02d}m" if sec >= 3600 else f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 else f"{sec}s"


def _ago(iso):
    import datetime
    try:
        return (datetime.datetime.now() - datetime.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return 0


def log_text(agent_id, name, live=True, limit=LOG_LINES):
    """An agent's recent activity as Telegram HTML: a header and the lines in a code block."""
    from . import agentlog
    entries = list(reversed(agentlog.read(agent_id, limit=limit)))
    lines = []
    for e in entries:
        t = (e.get("at") or "")[11:19]
        kind = {"retry": "error"}.get(e.get("type"), e.get("type") or "")
        lines.append(f"{t} {kind[:7]:<7} {_clip(e.get('text'), 70)}")
        if e.get("type") == "step" and e.get("status") == "working":
            lines.append(f"{'':16}task: {_clip(e.get('goal'), 54)}")
    body = "\n".join(lines) or "(nothing logged yet)"
    while len(body) > 3300 and "\n" in body:  # Telegram messages hold 4096 characters
        body = body.split("\n", 1)[1]
    state = (f"live · updates every {LOG_EVERY} s · stops after {LOG_MINUTES} min" if live else "stopped · /log to follow again")
    changed = (entries[-1].get("at") or "")[11:19] if entries else "-"
    return (f"<b>📜 {html.escape(name)} · log</b>\n<pre>{html.escape(body)}</pre>\n"
            f"<i>{state} · last change {changed}</i>")


def card_text(s, names):
    """A task's progress card: what is being done, what comes next, what is done (Telegram HTML)."""
    from . import flow
    esc = html.escape
    who = lambda a: names.get(a, "CEO" if a == "ceo" else a)  # noqa: E731
    status = s.get("status") or "?"
    icon = {"done": "✅", "failed": "❌", "cancelled": "⏹", "paused": "⏸", "waiting_approval": "🟡"}.get(status, "🛠")
    lines = [f"{icon} <b>{esc(_clip(s.get('goal'), 120))}</b>",
             f"<code>{esc(s.get('id') or '')}</code> · {esc(status.replace('_', ' '))} · {s.get('progress') or 0}%"]
    r = s.get("route") or {}
    if r:
        team = (who("lead") if r.get("route") == "answer" else who(r.get("agent")) if r.get("route") == "direct"
                else ", ".join(who(a) for a in r.get("agents") or []))
        lines.append(f"{'⚡' if r.get('route') != 'team' else '👥'} {esc(team)}" + (f" — {esc(_clip(r.get('reason'), 80))}" if r.get("reason") else ""))
    st = s.get("stages") or {}
    mark = {"done": "✅", "active": "▶️", "failed": "❌", "skipped": "➖", "rejected": "⛔"}
    lines.append(" ".join(f"{mark.get(st.get(k), '⬜')}{label}" for k, label, _, _ in flow.STAGES))
    steps = s.get("steps") or []
    working = [x for x in steps if x.get("status") in ("working", "queued")]
    if working:
        lines.append("\n<b>Working now</b>")
        for x in working:
            wait = " (waiting for a free slot)" if x.get("status") == "queued" else f" · {_dur(_ago(x.get('started_at')))}"
            lines.append(f"🔄 {esc(who(x.get('agent')))} · {esc(x.get('kind'))}: {esc(_clip(x.get('task'), 70))}{wait}")
    nxt = [f"⏳ {esc(p['id'])} {esc(_clip(p.get('title'), 50))} · {esc(who(p.get('agent')))}"
           + (f" (after {esc(', '.join(p.get('depends_on') or []))})" if p.get("depends_on") else "")
           for p in s.get("packages") or [] if p.get("status") == "todo"]
    if status in ("running", "paused"):
        nxt += [f"⏳ {label} · {esc(who(owner))}" for k, label, owner, _ in flow.STAGES
                if st.get(k, "todo") == "todo" and k not in ("plan",)][:4]
    if nxt:
        lines.append("\n<b>Next</b>")
        lines += nxt[:8]
    done = [x for x in steps if x.get("status") in ("done", "failed", "interrupted")][-6:]
    if done:
        lines.append("\n<b>Done</b>")
        for x in done:
            ok = {"done": "✅", "failed": "❌"}.get(x.get("status"), "⏹")
            took = f" · {_dur(x.get('seconds'))}" if x.get("seconds") is not None else ""
            lines.append(f"{ok} {esc(who(x.get('agent')))} · {esc(x.get('kind'))}: {esc(_clip(x.get('task'), 60))}{took}")
    if s.get("error"):
        lines.append(f"\n⚠️ {esc(_clip(s['error'], 300))}")
    text = "\n".join(lines)
    return text if len(text) < 4000 else text[:3990] + "…"



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

    def send_html(self, chat_id, text, buttons=None):
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True,
                         reply_markup={"inline_keyboard": buttons} if buttons else None)

    def edit_html(self, chat_id, message_id, text, buttons=None):
        try:
            return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
                             disable_web_page_preview=True, reply_markup={"inline_keyboard": buttons} if buttons else None)
        except TelegramError as e:
            if "not modified" in str(e):
                return None
            raise


class Bot(threading.Thread):
    """Long-polling loop; subclasses handle updates."""

    def __init__(self, name, token, allowed, base=None, allow_groups=False):
        super().__init__(daemon=True, name=f"telegram-{name}")
        self.allow_groups = bool(allow_groups)
        self.api = API(token, base)
        self.label = name
        self.allowed = {str(a).lstrip("@").lower() for a in allowed or [] if str(a).strip()}
        self.stopping = threading.Event()
        self.status = {"ok": False, "detail": "starting"}
        self.offset = None
        self.poll_timeout = 25  # seconds Telegram holds a getUpdates call open (long polling)
        self.live_logs = {}     # chat -> Event that stops its live log
        self.log_every = LOG_EVERY

    def commands(self):
        return []

    def set_commands(self):
        """The command menu is set again at every start, so it always matches this version."""
        cmds = self.commands()
        if cmds:
            try:
                self.api.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in cmds])
            except TelegramError as e:
                log(f"telegram {self.label}: could not set the command menu: {e}", "telegram")

    # -- live log: an agent's activity in a code block, updated every few seconds -------------------

    def start_live_log(self, chat, agent_id, name):
        old = self.live_logs.pop(str(chat), None)
        if old:
            old.set()
        stop = threading.Event()
        self.live_logs[str(chat)] = stop
        threading.Thread(target=self._live_log, args=(chat, agent_id, name, stop), daemon=True,
                         name=f"telegram-log-{agent_id}").start()

    def stop_live_log(self, chat):
        ev = self.live_logs.pop(str(chat), None)
        if ev:
            ev.set()
        return bool(ev)

    def _live_log(self, chat, agent_id, name, stop):
        stop_btn = [[{"text": "⏹ Stop", "callback_data": "logstop"}]]
        again = [[{"text": "▶ Follow again", "callback_data": f"log:{agent_id}"}]]
        end = time.time() + LOG_MINUTES * 60
        msg, last = None, None
        try:
            while not stop.is_set() and not self.stopping.is_set() and time.time() < end:
                text = log_text(agent_id, name)
                if text != last:
                    if msg is None:
                        msg = self.api.send_html(chat, text, stop_btn)
                    else:
                        self.api.edit_html(chat, msg["message_id"], text, stop_btn)
                    last = text
                stop.wait(self.log_every)
            if msg:
                self.api.edit_html(chat, msg["message_id"], log_text(agent_id, name, live=False), again)
        except TelegramError as e:
            log(f"telegram {self.label}: live log stopped: {e}", "telegram")
        finally:
            if self.live_logs.get(str(chat)) is stop:
                self.live_logs.pop(str(chat), None)

    def is_allowed(self, user):
        if not user or user.get("is_bot"):
            return False
        uid, name = str(user.get("id")), (user.get("username") or "").lower()
        if uid in self.allowed:
            return True
        if not name or name not in self.allowed:
            return False
        with _pins_lock:  # a @username belongs to the first account that used it here
            st = _state()
            pins = st.setdefault("username_ids", {})
            if name not in pins:
                pins[name] = uid
                _save_state(st)
                log(f"telegram: @{name} is now tied to user id {uid}", "telegram")
            elif pins[name] != uid:
                log(f"telegram: refused @{name} from user id {uid} (tied to {pins[name]})", "telegram")
                return False
        return True

    def chat_ok(self, chat):
        return self.allow_groups or (chat or {}).get("type", "private") == "private"

    def deny(self, chat_id, user):
        self.api.send(chat_id, f"Not allowed yet. Your Telegram user id is {user.get('id')}"
                               f"{' (@' + user['username'] + ')' if user.get('username') else ''}. Ask the owner to add "
                               "it in the BABD dashboard: Team settings → Telegram → Allowed users.")

    def run(self):
        try:
            me = self.api.call("getMe", http_timeout=20)
            self.status = {"ok": True, "detail": f"connected as @{me.get('username')}", "username": me.get("username")}
            log(f"telegram {self.label}: connected as @{me.get('username')}", "telegram")
            self.set_commands()
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
        for ev in list(self.live_logs.values()):
            ev.set()

    def handle(self, update):
        raise NotImplementedError

    def tick(self):
        pass


_pins_lock = threading.Lock()


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
        super().__init__("ceo", token, cfg.get("allowed_users"), base, cfg.get("allow_groups"))
        self.dash = dash
        self.notify = set(cfg.get("notify") or NOTIFY)
        self.daily_hour = int(cfg.get("daily_report_hour", 18))
        st = _state()
        self.chats = {str(c) for c in st.get("ceo_chats", [])}
        self.chat_project = st.get("chat_project", {})
        self.last_daily = st.get("last_daily", "")
        self.events = dash.hub.subscribe()
        self.notifier = threading.Thread(target=self.notify_loop, daemon=True, name="telegram-ceo-notify")
        self.cards = {}  # task id -> {"msgs": {chat: message id}, "summary", "dirty", "last"}
        self.card_every = CARD_EVERY

    def commands(self):
        return CEO_COMMANDS

    def names(self):
        try:
            return {a["id"]: a.get("short_name") or a["name"] for a in self.dash.load()["agents"]}
        except Exception:  # noqa: BLE001
            return {}

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
        if not self.chat_ok(msg.get("chat")):
            return self.api.send(chat, "I only work in a private chat (groups are off: ceo_telegram.allow_groups).")
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
                                       "it becomes a task for the team (the Team Lead decides who is needed).\n\n"
                                       + "\n".join(f"/{c} - {d}" for c, d in CEO_COMMANDS))
        if cmd == "/agents":
            return self.api.send_html(chat, self.agents_text(), [
                [{"text": f"📜 {n}", "callback_data": f"log:{a}"} for a, n in list(self.names().items())[i:i + 3]]
                for i in range(0, len(self.names()), 3)])
        if cmd == "/log":
            names = self.names()
            if arg:
                aid = next((a for a, n in names.items() if arg.lower() in (a.lower(), n.lower())), None)
                if not aid:
                    return self.api.send(chat, f"No agent {arg}. Agents: " + ", ".join(names))
                return self.start_live_log(chat, aid, names[aid])
            return self.api.send(chat, "Whose log? (it updates every 3 s)", [
                [{"text": n, "callback_data": f"log:{a}"} for a, n in list(names.items())[i:i + 3]]
                for i in range(0, len(names), 3)])
        if cmd == "/report":
            if not arg:
                return self.api.send(chat, "Usage: /report <task id> (see /tasks)")
            return self.api.send_html(chat, self.safe(lambda: self.report_text(arg)))
        if cmd == "/notify":
            return self.api.send(chat, "This bot sends: " + (", ".join(n for n in NOTIFY if n in self.notify) or "nothing")
                                 + ".\nProgress = a live card per task: who works on what now, what comes next, what is done."
                                 "\nChange it in the dashboard: Team settings → Telegram.")
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
        if cmd == "/pause":
            if not arg:
                return self.api.send(chat, "Usage: /pause <task id> (continue it with /resume <task id>)")
            return self.api.send(chat, self.safe(lambda: self.dash.pause_run(arg, True)["note"]))
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
        chat = ((q.get("message") or {}).get("chat") or {}).get("id")
        if action in ("log", "logstop") and chat is not None:
            if action == "logstop":
                self.stop_live_log(chat)
            else:
                names = self.names()
                if run_id in names:
                    self.start_live_log(chat, run_id, names[run_id])
            return self.api.call("answerCallbackQuery", callback_query_id=q["id"],
                                 text="Stopped" if action == "logstop" else "Following the log")
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
                kind, data = self.events.get(timeout=1)
                try:
                    self.on_event(kind, data)
                except Exception as e:
                    log(f"telegram ceo: {type(e).__name__}: {e}", "telegram")
            except queue.Empty:
                pass
            try:
                self.flush_cards()
            except Exception as e:  # noqa: BLE001
                log(f"telegram ceo: progress card: {type(e).__name__}: {e}", "telegram")

    # -- progress cards: one live message per task --------------------------------------------------

    def track(self, s, final=False):
        """Keep the task's card up to date: created on the task's first event, edited at most every
        few seconds while it runs, and once more when it ends."""
        rid = s.get("id")
        if not rid or "Progress" not in self.notify or not self.chats:
            return
        card = self.cards.get(rid)
        if card is None:
            if final:
                return
            card = self.cards[rid] = {"msgs": {}, "summary": s, "dirty": False, "last": time.time(), "text": ""}
            text = card_text(s, self.names())
            for chat in list(self.chats):
                try:
                    card["msgs"][chat] = self.api.send_html(chat, text)["message_id"]
                except (TelegramError, TypeError, KeyError) as e:
                    log(f"telegram ceo: could not send the progress card to {chat}: {e}", "telegram")
            card["text"] = text
            return
        card["summary"], card["dirty"] = s, True
        if final:
            self.flush_card(rid, card)
            self.cards.pop(rid, None)

    def flush_cards(self):
        for rid, card in list(self.cards.items()):
            if card["dirty"] and time.time() - card["last"] >= self.card_every:
                self.flush_card(rid, card)

    def flush_card(self, rid, card):
        text = card_text(card["summary"], self.names())
        card["dirty"], card["last"] = False, time.time()
        if text == card["text"]:
            return
        card["text"] = text
        for chat, mid in list(card["msgs"].items()):
            try:
                self.api.edit_html(chat, mid, text)
            except TelegramError as e:
                log(f"telegram ceo: could not update the progress card in {chat}: {e}", "telegram")

    def agents_text(self):
        b = self.dash.board(history=5)
        out = ["<b>Agents</b>"]
        for a in b["agents"]:
            now = "; ".join(f"{st.get('kind')}: {_clip(st.get('goal'), 40)}" for st in a.get("working") or [])
            out.append(f"{'🔄' if now else '💤'} <b>{html.escape(a['name'])}</b> {a.get('active', 0)}/{a.get('capacity')} slots"
                       f" · {a.get('done', 0)} done" + (f"\n    {html.escape(now)}" if now else ""))
        return "\n".join(out)

    def report_text(self, run_id):
        r = self.dash.load_run(os.path.basename(run_id.strip()))
        rep = r.get("report") or {}
        text = card_text(r, self.names())
        if rep.get("summary"):
            text += f"\n\n<b>Report</b>\n{html.escape(_clip(rep['summary'], 1500))}"
        ws = (r.get("workspace") or {}).get("result") or {}
        if ws.get("branch"):
            text += f"\n\n🌿 <code>{html.escape(ws['branch'])}</code>" + (" · merged" if ws.get("merged") else "") + (
                f" · {html.escape(ws['note'])}" if ws.get("note") else "")
        return text[:4000]

    def on_event(self, kind, data):
        if kind == "run" and data.get("summary"):
            self.track(data["summary"], final=data.get("event") == "finished")
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
    """One agent's own bot: chat with it, follow its live log, and get a message when it starts and
    finishes a step (in the chats that talked to it or were set up with Initialize)."""

    def __init__(self, dash, agent_id, token, allowed, base=None, allow_groups=False):
        super().__init__(agent_id, token, allowed, base, allow_groups)
        self.dash, self.agent_id = dash, agent_id
        self.chats = set(str(c) for c in (_state().get("agent_chats") or {}).get(agent_id, []))
        self.events = dash.hub.subscribe() if hasattr(dash, "hub") else None
        self.notifier = threading.Thread(target=self.notify_loop, daemon=True, name=f"telegram-{agent_id}-notify")

    @property
    def name(self):
        try:
            a = next(a for a in self.dash.load()["agents"] if a["id"] == self.agent_id)
            return a.get("short_name") or a["name"]
        except (StopIteration, KeyError, OSError, ValueError):
            return self.agent_id

    def commands(self):
        return agent_commands(self.name)

    def start(self):
        super().start()
        if self.events is not None:
            self.notifier.start()

    def stop(self):
        super().stop()
        if self.events is not None:
            self.dash.hub.unsubscribe(self.events)

    def remember_chat(self, chat):
        if str(chat) not in self.chats:
            self.chats.add(str(chat))
            add_chat(self.agent_id, chat)

    def notify_loop(self):
        import queue
        while not self.stopping.is_set():
            try:
                kind, data = self.events.get(timeout=1)
            except queue.Empty:
                continue
            if kind != "agentlog" or data.get("agent") != self.agent_id or data.get("type") != "step":
                continue
            text = {"working": "🔨 Starting", "done": "✅ Done", "failed": "❌ Failed"}.get(data.get("status"))
            if not text:
                continue
            msg = (f"{text}: {data.get('text')}\n📌 {data.get('goal')} ({data.get('run')})")
            for chat in list(self.chats):
                try:
                    self.api.send(chat, msg)
                except TelegramError as e:
                    log(f"telegram {self.agent_id}: could not notify {chat}: {e}", "telegram")

    def status_text(self):
        b = self.dash.board(history=10)
        a = next((x for x in b["agents"] if x["id"] == self.agent_id), None)
        if not a:
            return "No such agent."
        lines = [f"<b>{html.escape(a['name'])}</b> · {a.get('active', 0)}/{a.get('capacity')} slots busy · "
                 f"{a.get('done', 0)} steps done"]
        for st in a.get("working") or []:
            lines.append(f"🔄 {html.escape(st.get('kind') or '')}: {html.escape(_clip(st.get('task'), 80))}\n"
                         f"    📌 {html.escape(_clip(st.get('goal'), 60))} · {_dur(_ago(st.get('started_at')))}")
        for st in a.get("queued") or []:
            lines.append(f"⏳ waiting for a slot: {html.escape(_clip(st.get('task'), 80))}")
        if len(lines) == 1:
            lines.append("💤 Idle: ready for the next step")
        return "\n".join(lines)

    def tasks_text(self):
        from . import agentlog
        done = [e for e in agentlog.read(self.agent_id, limit=200, type_="step") if e.get("status") in ("done", "failed")][:12]
        rows = [f"{'✅' if e.get('status') == 'done' else '❌'} {(e.get('at') or '')[5:16]} {e.get('text')}\n    📌 {e.get('goal')}"
                for e in done]
        return "\n".join(rows) or "No finished steps yet."

    def handle(self, update):
        if "callback_query" in update:
            q = update["callback_query"]
            chat = ((q.get("message") or {}).get("chat") or {}).get("id")
            if not self.is_allowed(q.get("from")) or chat is None:
                return self.api.call("answerCallbackQuery", callback_query_id=q["id"], text="Not allowed")
            if (q.get("data") or "") == "logstop":
                self.stop_live_log(chat)
            elif (q.get("data") or "").startswith("log:"):
                self.start_live_log(chat, self.agent_id, self.name)
            return self.api.call("answerCallbackQuery", callback_query_id=q["id"], text="OK")
        msg = update.get("message") or {}
        chat, user, text = msg.get("chat", {}).get("id"), msg.get("from"), (msg.get("text") or "").strip()
        if chat is None or not text:
            return
        if not self.chat_ok(msg.get("chat")):
            return self.api.send(chat, "I only work in a private chat.")
        if not self.is_allowed(user):
            return self.deny(chat, user)
        self.remember_chat(chat)
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if cmd in ("/start", "/help"):
            return self.api.send(chat, f"{self.name} bot. Write to chat with {self.name}; you also get a message when "
                                       f"{self.name} starts and finishes work.\n\n"
                                       + "\n".join(f"/{c} - {d}" for c, d in self.commands()))
        if cmd == "/reset":
            self.dash.chats.pop(self.agent_id, None)
            return self.api.send(chat, "New conversation.")
        if cmd == "/status":
            return self.api.send_html(chat, self.status_text())
        if cmd == "/log":
            return self.start_live_log(chat, self.agent_id, self.name)
        if cmd == "/tasks":
            return self.api.send(chat, self.tasks_text())
        threading.Thread(target=self.reply, args=(chat, text), daemon=True,
                         name=f"telegram-{self.agent_id}-chat").start()  # a long answer never blocks the buttons

    def reply(self, chat, text):
        try:
            self.api.call("sendChatAction", chat_id=chat, action="typing")
        except TelegramError:
            pass
        try:
            reply = self.dash.chat(self.agent_id, text)["reply"]
        except Exception as e:
            reply = f"Error: {e}"
        try:
            self.api.send(chat, reply)
        except TelegramError as e:
            log(f"telegram {self.agent_id}: {e}", "telegram")


def add_chat(target, chat):
    """Remember a chat that gets this bot's notifications ("ceo" or an agent id)."""
    with _pins_lock:
        st = _state()
        if target == "ceo":
            chats = set(st.get("ceo_chats") or [])
            chats.add(str(chat))
            st["ceo_chats"] = sorted(chats)
        else:
            per = st.setdefault("agent_chats", {})
            per[target] = sorted(set(per.get(target) or []) | {str(chat)})
        _save_state(st)


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
                want[a["id"]] = (json.dumps([token, allowed, bool(ceo.get("allow_groups"))], sort_keys=True),
                                 lambda a=a, token=token: AgentBot(self.dash, a["id"], token, allowed, self.base,
                                                                   ceo.get("allow_groups")))
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

    def add_chat(self, target, chat):
        add_chat(target, chat)
        with self.lock:
            bot = self.bots.get(target, (None, None))[1]
        if bot is not None:
            bot.remember_chat(chat)

    def stop(self):
        with self.lock:
            for _, bot in self.bots.values():
                bot.stop()
            self.bots.clear()
