"""Telegram bots against a fake Bot API server: tasks from messages, .md files and links, approvals
with buttons, notifications, /status, the allow list, and agent chat bots.

Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import telegram  # noqa: E402
from babd.team import Agent  # noqa: E402

CEO_TOKEN, DEV_TOKEN = "111:ceo", "222:dev"
SPEC = "# Export reports as CSV\n\nAdd a CSV button.\n"


class FakeTelegram:
    """Just enough of the Bot API: updates are pushed by the test, sent messages are recorded."""

    def __init__(self):
        self.lock = threading.Lock()
        self.updates = {}   # token -> [update]
        self.sent = []      # (token, method, params)
        self.next_id = 1
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, result, ok=True, code=200):
                body = json.dumps({"ok": ok, "result": result} if ok else {"ok": False, "description": result}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # file download
                if self.path.startswith("/file/bot"):
                    body = SPEC.encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def do_POST(self):
                _, bot, method = self.path.split("/", 2)
                token = bot[3:]
                params = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if token not in (CEO_TOKEN, DEV_TOKEN):
                    return self.reply("Unauthorized", ok=False, code=401)
                if method == "getMe":
                    return self.reply({"username": "ceo_bot" if token == CEO_TOKEN else "dev_bot"})
                if method == "getUpdates":
                    end = time.time() + 0.3
                    while time.time() < end:
                        with fake.lock:
                            ups = [u for u in fake.updates.get(token, []) if u["update_id"] >= (params.get("offset") or 0)]
                        if ups:
                            return self.reply(ups)
                        time.sleep(0.03)
                    return self.reply([])
                if method == "getFile":
                    return self.reply({"file_path": "docs/spec.md", "file_size": len(SPEC)})
                with fake.lock:
                    fake.sent.append((token, method, params))
                if method == "sendMessage":
                    return self.reply({"message_id": len(fake.sent), "chat": {"id": params["chat_id"]}, "text": params["text"]})
                return self.reply(True)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def push(self, token, **update):
        with self.lock:
            update["update_id"] = self.next_id
            self.next_id += 1
            self.updates.setdefault(token, []).append(update)

    def message(self, token, text=None, user_id=7, username="boss", **extra):
        msg = {"message_id": 1, "chat": {"id": 1000 + user_id}, "from": {"id": user_id, "username": username}, **extra}
        if text is not None:
            msg["text"] = text
        self.push(token, message=msg)

    def texts(self, token=CEO_TOKEN):
        with self.lock:
            return [p.get("text", "") for t, m, p in self.sent if t == token and m in ("sendMessage", "editMessageText")]

    def calls(self, method):
        with self.lock:
            return [p for t, m, p in self.sent if m == method]


class TelegramTest(unittest.TestCase):
    setUp_dash = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait
    waiting = td.DashboardTest.waiting

    def setUp(self):
        self.setUp_dash()
        self.fake = FakeTelegram()
        self.addCleanup(self.fake.server.shutdown)
        p = mock.patch.object(telegram, "STATE_PATH", os.path.join(self.tmp, "telegram.json"))
        p.start()
        self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"TELEGRAM_CEO_BOT_TOKEN": CEO_TOKEN, "TELEGRAM_DEV_BOT_TOKEN": DEV_TOKEN})
        env.start()
        self.addCleanup(env.stop)
        ask = mock.patch.object(Agent, "ask", td.scripted_ask)
        ask.start()
        self.addCleanup(ask.stop)
        self.call("PUT", "/api/telegram", {"enabled": True, "allowed_users": "7, @friend", "notify": list(telegram.NOTIFY)})
        cfg = json.loads(td.read(self.cfg_path))
        for a in cfg["agents"]:
            a["telegram"] = {"enabled": a["id"] == "developer", "bot_username": "@x", "token_env": "TELEGRAM_DEV_BOT_TOKEN"}
        with open(self.cfg_path, "w") as f:
            json.dump(cfg, f)
        self.manager = telegram.Manager(self.dash, base=self.fake.url)
        self.addCleanup(self.manager.stop)
        self.manager.reconcile()
        self.wait(lambda: all(s.get("ok") for s in self.manager.status().values()) and len(self.manager.status()) == 2)

    def idle(self):
        with self.dash.tasks_lock:
            return not self.dash.active and not self.dash.queue

    def test_status_and_allow_list(self):
        self.assertEqual(self.manager.status()["ceo"]["detail"], "connected as @ceo_bot")
        self.fake.message(CEO_TOKEN, "Build login", user_id=99, username="stranger")
        self.wait(lambda: any("Your Telegram user id is 99" in t for t in self.fake.texts()))
        self.assertFalse(self.dash.active or self.dash.queue)  # no task from a stranger
        self.fake.message(CEO_TOKEN, "/status", user_id=55, username="friend")  # allowed by @username
        self.wait(lambda: any(t.startswith("Running") for t in self.fake.texts()))

    def test_message_becomes_a_task_with_approval_buttons(self):
        self.fake.message(CEO_TOKEN, "Build a login page")
        self.wait(lambda: any(t.startswith("Task started: Build a login page") for t in self.fake.texts()))
        run_id = [t for t in self.fake.texts() if t.startswith("Task started")][0].split("id: ")[1]
        self.wait(lambda: self.waiting(run_id), timeout=20)
        msg = self.wait(lambda: [p for p in self.fake.calls("sendMessage") if p.get("reply_markup")])
        buttons = msg[0]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([b["callback_data"] for b in buttons], [f"approve:{run_id}", f"reject:{run_id}"])
        self.fake.push(CEO_TOKEN, callback_query={"id": "cb1", "from": {"id": 7, "username": "boss"}, "data": buttons[0]["callback_data"],
                                                  "message": {"message_id": 5, "chat": {"id": 1007}, "text": "Approval needed"}})
        self.wait(self.idle, timeout=20)
        self.wait(lambda: any(t.startswith("✅ Task done: Build a login page") for t in self.fake.texts()))
        self.assertEqual(self.fake.calls("answerCallbackQuery")[0]["text"], "Deploy approved")
        _, run = self.call("GET", f"/api/runs/{run_id}")
        self.assertEqual((run["status"], run["deployed"]), ("done", True))
        self.assertIn("approved on Telegram by @boss", run["approval"]["note"])

    def test_markdown_file_becomes_a_task(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.fake.message(CEO_TOKEN, document={"file_id": "f1", "file_name": "spec.md"})
        self.wait(lambda: any(t.startswith("Task started: Export reports as CSV") for t in self.fake.texts()))
        self.fake.message(CEO_TOKEN, document={"file_id": "f2", "file_name": "photo.jpg"})
        self.wait(lambda: any("send a Markdown or text file" in t for t in self.fake.texts()))
        self.wait(self.idle, timeout=20)

    def test_filled_template_message_becomes_a_task_document(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.fake.message(CEO_TOKEN, "/templates")
        self.wait(lambda: any(t.startswith("Templates") for t in self.fake.texts()))
        self.fake.message(CEO_TOKEN, "# Bug: login button does nothing\n\n## What happens\nNothing.")
        self.wait(lambda: any(t.startswith("Task started: Bug: login button does nothing") for t in self.fake.texts()))
        self.wait(self.idle, timeout=20)

    def test_stranger_cannot_press_buttons(self):
        self.fake.push(CEO_TOKEN, callback_query={"id": "cb9", "from": {"id": 99}, "data": "approve:x"})
        self.wait(lambda: self.fake.calls("answerCallbackQuery"))
        self.assertEqual(self.fake.calls("answerCallbackQuery")[0]["text"], "Not allowed")

    def test_agent_bot_chats_with_its_agent(self):
        with mock.patch.object(Agent, "chat", lambda self, m, **kw: f"{self.id} says hi to: {m}"):
            self.fake.message(DEV_TOKEN, "how is the build?")
            self.wait(lambda: any(t == "developer says hi to: how is the build?" for t in self.fake.texts(DEV_TOKEN)))

    def test_settings_api(self):
        _, state = self.call("GET", "/api/state")
        tg = state["telegram"]
        self.assertTrue(tg["ceo"]["token_set"])
        self.assertEqual(tg["ceo"]["allowed_users"], ["7", "@friend"])
        self.assertNotIn(CEO_TOKEN, json.dumps(state))  # the token never reaches the browser
        status, out = self.call("PUT", "/api/telegram", {"token": "333:new", "notify": ["Approvals", "Bogus"]})
        self.assertEqual(out["ceo"]["notify"], ["Approvals"])
        self.assertIn("TELEGRAM_CEO_BOT_TOKEN=333:new", td.read(os.path.join(self.tmp, ".env")))


class TelegramFeaturesTest(TelegramTest):
    """Initialize, command menus, progress cards, live logs and agent notifications."""

    def bot(self, key):
        return self.manager.bots[key][1]

    def html_msgs(self, token=CEO_TOKEN):
        with self.fake.lock:
            return [p for t, m, p in self.fake.sent if t == token and p.get("parse_mode") == "HTML"]

    def test_bots_use_a_reply_keyboard_not_the_command_menu(self):
        with self.fake.lock:
            cleared = {t for t, m, p in self.fake.sent if m == "deleteMyCommands"}
            self.assertFalse([p for t, m, p in self.fake.sent if m == "setMyCommands"])
        self.assertEqual(cleared, {CEO_TOKEN, DEV_TOKEN})
        self.fake.message(CEO_TOKEN, "/start")
        msg = self.wait(lambda: [p for p in self.fake.calls("sendMessage") if (p.get("reply_markup") or {}).get("keyboard")])
        kb = msg[0]["reply_markup"]
        self.assertTrue(kb["is_persistent"] and kb["resize_keyboard"])
        labels = [b["text"] for row in kb["keyboard"] for b in row]
        self.assertEqual(labels, [label for row in telegram.CEO_KEYBOARD for label, _ in row])
        self.assertIn("📜 Live log - Live log of an agent", msg[0]["text"])
        self.fake.message(DEV_TOKEN, "/start")
        self.wait(lambda: [p for t, m, p in self.fake.sent if t == DEV_TOKEN and m == "sendMessage"
                           and [b["text"] for row in (p.get("reply_markup") or {}).get("keyboard", []) for b in row]
                           == [label for row in telegram.AGENT_KEYBOARD for label, _ in row]])

    def test_keyboard_buttons_do_the_commands(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.fake.message(CEO_TOKEN, "📊 Status")
        self.wait(lambda: any(t.startswith("Running") for t in self.fake.texts()))
        self.fake.message(CEO_TOKEN, "🤖 Agents")
        self.wait(lambda: any("<b>Agents</b>" in p["text"] for p in self.html_msgs()))
        # Quick task: the next message is the goal
        self.fake.message(CEO_TOKEN, "⚡ Quick task")
        self.wait(lambda: any("Send the goal as your next message" in t for t in self.fake.texts()))
        self.fake.message(CEO_TOKEN, "Print hello")
        self.wait(lambda: any(t.startswith("Task started: Print hello") for t in self.fake.texts()))
        run_id = [t for t in self.fake.texts() if t.startswith("Task started: Print hello")][0].split("id: ")[1]
        self.wait(self.idle, timeout=20)
        _, r = self.call("GET", f"/api/runs/{run_id}")
        self.assertEqual(r["task_options"]["mode"], "quick")
        # Report: pick the task from buttons
        self.fake.message(CEO_TOKEN, "📄 Report")
        pick = self.wait(lambda: [p for p in self.fake.calls("sendMessage") if p.get("text") == "Which task's report?"])
        datas = [b["callback_data"] for row in pick[0]["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn(f"do:report:{run_id}", datas)
        self.fake.push(CEO_TOKEN, callback_query={"id": "cb7", "from": {"id": 7, "username": "boss"}, "data": f"do:report:{run_id}",
                                                  "message": {"message_id": 3, "chat": {"id": 1007}}})
        self.wait(lambda: any("<b>Report</b>" in p["text"] and run_id in p["text"] for p in self.html_msgs()))
        # nothing to pause: a clear answer, not an error
        self.fake.message(CEO_TOKEN, "⏸ Pause")
        self.wait(lambda: any(t.startswith("No task to pick") for t in self.fake.texts()))
        # Project: pick from buttons
        self.fake.message(CEO_TOKEN, "📁 Project")
        self.wait(lambda: any(t.startswith("New tasks from this chat go to") for t in self.fake.texts()))
        self.fake.message(DEV_TOKEN, "📊 Status")
        self.wait(lambda: any("Idle" in t or "slots busy" in t for t in self.fake.texts(DEV_TOKEN)))

    def test_initialize_a_bot(self):
        self.dash.telegram = self.manager  # the dashboard's own manager, on the fake Bot API
        status, out = self.call("POST", "/api/telegram/init", {"target": "ceo", "chat_id": "5555", "token": CEO_TOKEN})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["username"], out["welcome_sent"]), ("ceo_bot", True))
        welcome = [p for t, m, p in self.fake.sent if m == "sendMessage" and p.get("chat_id") == 5555]
        self.assertIn("BABD CEO bot is ready", welcome[0]["text"])
        self.assertEqual(welcome[0]["reply_markup"]["keyboard"][0][0]["text"], "📊 Status")
        self.assertEqual(out["buttons"], sum(len(r) for r in telegram.CEO_KEYBOARD))
        ceo = json.loads(td.read(self.cfg_path))["project"]["ceo_telegram"]
        self.assertIn("5555", ceo["allowed_users"])
        self.assertIn("Progress", ceo["notify"])
        self.assertEqual(ceo["bot_username"], "@ceo_bot")
        self.assertIn(f"TELEGRAM_CEO_BOT_TOKEN={CEO_TOKEN}", td.read(os.path.join(self.tmp, ".env")))
        self.assertNotIn(CEO_TOKEN, json.dumps(out))
        self.assertIn("5555", json.load(open(telegram.STATE_PATH))["ceo_chats"])
        # an agent's own bot
        status, out = self.call("POST", "/api/telegram/init", {"target": "developer", "chat_id": "5555", "token": DEV_TOKEN})
        self.assertEqual(status, 200, out)
        self.assertIn("5555", json.load(open(telegram.STATE_PATH))["agent_chats"]["developer"])
        # refusals
        self.assertEqual(self.call("POST", "/api/telegram/init", {"chat_id": "abc", "token": CEO_TOKEN})[0], 400)
        self.assertEqual(self.call("POST", "/api/telegram/init", {"chat_id": "1", "token": "not a token"})[0], 400)
        status, out = self.call("POST", "/api/telegram/init", {"chat_id": "1", "token": "999:wrong"})
        self.assertEqual(status, 400)
        self.assertIn("Telegram refused", out["error"])

    def test_progress_card_follows_the_task(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.call("PUT", "/api/telegram", {"notify": list(telegram.NOTIFY)})
        self.manager.reconcile()
        self.wait(lambda: "ceo" in self.manager.bots and self.bot("ceo").status.get("ok"))
        self.bot("ceo").card_every = 0
        self.fake.message(CEO_TOKEN, "/help")  # this chat gets notifications
        self.wait(lambda: any("All commands" in t for t in self.fake.texts()))
        self.fake.message(CEO_TOKEN, "Build a login page")
        self.wait(self.idle, timeout=20)
        self.wait(lambda: any("✅ Task done" in t for t in self.fake.texts()))
        cards = [p for p in self.html_msgs() if "Build a login page" in p.get("text", "")]
        self.assertTrue(cards)
        self.wait(lambda: any("✅" in p["text"] and "<b>Done</b>" in p["text"] for p in self.fake.calls("editMessageText")
                              if p.get("parse_mode") == "HTML"))
        final = [p for p in self.fake.calls("editMessageText") if p.get("parse_mode") == "HTML"][-1]["text"]
        self.assertIn("✅REPORT", final)

    def test_live_log_in_a_code_block(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.manager.reconcile()
        self.wait(lambda: "ceo" in self.manager.bots and self.bot("ceo").status.get("ok"))
        self.bot("ceo").log_every = 0.2
        self.fake.message(CEO_TOKEN, "/log developer")
        self.wait(lambda: any("<pre>" in p["text"] and "Developer" in p["text"] for p in self.html_msgs()))
        first = [p for p in self.html_msgs() if "<pre>" in p["text"]][0]
        self.assertEqual(first["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "logstop")
        self.fake.message(CEO_TOKEN, "Build a login page")  # the log fills as the developer works
        self.wait(self.idle, timeout=20)
        self.wait(lambda: any("started code" in p["text"] for p in self.fake.calls("editMessageText") if p.get("parse_mode")))
        self.fake.push(CEO_TOKEN, callback_query={"id": "cb5", "from": {"id": 7, "username": "boss"}, "data": "logstop",
                                                  "message": {"message_id": 9, "chat": {"id": 1007}}})
        self.wait(lambda: any("stopped" in p["text"] for p in self.fake.calls("editMessageText") if p.get("parse_mode")))
        self.fake.message(CEO_TOKEN, "/log")  # without a name: buttons to pick the agent
        self.wait(lambda: any(p.get("reply_markup") and any(b["callback_data"] == "log:developer" for row in p["reply_markup"]["inline_keyboard"] for b in row)
                              for p in self.fake.calls("sendMessage")))

    def test_agent_bot_status_log_and_notifications(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.fake.message(DEV_TOKEN, "/status")
        self.wait(lambda: any("Idle" in t or "slots busy" in t for t in self.fake.texts(DEV_TOKEN)))
        self.fake.message(CEO_TOKEN, "Build a login page")
        self.wait(self.idle, timeout=20)
        self.wait(lambda: any(t.startswith("🔨 Starting: started code") for t in self.fake.texts(DEV_TOKEN)))
        self.wait(lambda: any(t.startswith("✅ Done: finished code") for t in self.fake.texts(DEV_TOKEN)))
        self.fake.message(DEV_TOKEN, "/tasks")
        self.wait(lambda: any("Build a login page" in t and "finished code" in t for t in self.fake.texts(DEV_TOKEN)))

    def test_questions_are_answered_from_telegram(self):
        import test_questions as tq
        self.call("PUT", "/api/project", {"require_approval": False})
        with mock.patch.object(Agent, "ask", tq.asking_ask):
            self.fake.message(CEO_TOKEN, "Build an app")
            msg = self.wait(lambda: [p for p in self.fake.calls("sendMessage") if "asks:" in p.get("text", "")], timeout=20)
            buttons = [b for row in msg[0]["reply_markup"]["inline_keyboard"] for b in row]
            self.assertEqual([b["text"] for b in buttons], ["8080", "3000", "✍️ Type an answer"])
            self.fake.message(CEO_TOKEN, "💬 Questions")  # the keyboard button lists open questions
            self.wait(lambda: len([p for p in self.fake.calls("sendMessage") if "asks:" in p.get("text", "")]) >= 2)
            # type the answer instead of a button
            self.fake.push(CEO_TOKEN, callback_query={"id": "q1", "from": {"id": 7, "username": "boss"},
                                                      "data": buttons[2]["callback_data"],
                                                      "message": {"message_id": 4, "chat": {"id": 1007}, "text": "asks"}})
            self.wait(lambda: any(t == "Send your answer as your next message." for t in self.fake.texts()))
            self.fake.message(CEO_TOKEN, "4000")
            self.wait(lambda: any(t.startswith("✅ Answer sent") for t in self.fake.texts()))
            self.wait(self.idle, timeout=20)
        runs = self.dash.search("Build an app")
        r = self.dash.load_run(runs[0]["id"])
        self.assertEqual(r["questions"][0]["answer"], "4000")

    def test_servers_button(self):
        import test_servers as ts
        ts.use_tmp(self)
        self.fake.message(CEO_TOKEN, "🖥 Servers")
        self.wait(lambda: any(t.startswith("No servers yet") for t in self.fake.texts()))
        self.call("PUT", "/api/servers", {"servers": [{"id": "lpnotif", "name": "Server lpnotif", "host": "203.0.113.7"}]})
        self.fake.message(CEO_TOKEN, "🖥 Servers")
        msg = self.wait(lambda: [p for p in self.html_msgs() if "lpnotif" in p["text"]])
        datas = [b["callback_data"] for row in msg[0]["reply_markup"]["inline_keyboard"] for b in row]
        self.assertEqual(datas, ["srvtest:lpnotif", "srvkey:lpnotif"])

    def test_pull_requests_button(self):
        self.fake.message(CEO_TOKEN, "🔀 Pull requests")
        self.wait(lambda: any(t == "No open pull requests." for t in self.fake.texts()))
        rid = "20260101-000000"
        os.makedirs(os.path.join(td.flow.RUNS_DIR, rid))
        with open(os.path.join(td.flow.RUNS_DIR, rid, "state.json"), "w") as f:
            json.dump({"id": rid, "goal": "Add a cart", "status": "done", "workspace": {"result": {"pr": {
                "number": 7, "url": "https://github.com/acme/shop/pull/7", "state": "open", "checks": "success"}}}}, f)
        self.fake.message(CEO_TOKEN, "🔀 Pull requests")
        msg = self.wait(lambda: [p for p in self.html_msgs() if "PR #7" in p["text"]])
        self.assertIn("CI green", msg[0]["text"])
        self.assertEqual(msg[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], f"prmerge:{rid}")

    def test_schedules_button(self):
        self.fake.message(CEO_TOKEN, "⏰ Schedules")
        msg = self.wait(lambda: [p for p in self.html_msgs() if "Scheduled tasks" in p["text"]])
        self.assertEqual(msg[0]["reply_markup"]["inline_keyboard"][-1][0]["callback_data"], "schnew")
        self.fake.push(CEO_TOKEN, callback_query={"id": "s1", "from": {"id": 7, "username": "boss"}, "data": "schnew",
                                                  "message": {"message_id": 2, "chat": {"id": 1007}}})
        self.wait(lambda: any(t.startswith("Send the new schedule") for t in self.fake.texts()))
        self.fake.message(CEO_TOKEN, "daily 07:00 | cek disk server lpnotif")
        self.wait(lambda: any(t.startswith("⏰ Scheduled: cek disk server lpnotif") for t in self.fake.texts()))
        self.assertEqual(json.loads(td.read(self.cfg_path))["schedules"][0]["cron"], "0 7 * * *")
        self.fake.message(CEO_TOKEN, "⏰ Schedules")
        msg = self.wait(lambda: [p for p in self.html_msgs() if "cek disk server lpnotif" in p["text"] and "every day at 07:00" in p["text"]])
        self.assertEqual(msg[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"], "schrun:cek-disk-server-lpnotif")

    def test_agents_and_report_commands(self):
        self.call("PUT", "/api/project", {"require_approval": False})
        self.fake.message(CEO_TOKEN, "/agents")
        self.wait(lambda: any("<b>Agents</b>" in p["text"] for p in self.html_msgs()))
        self.fake.message(CEO_TOKEN, "Build a login page")
        self.wait(lambda: any(t.startswith("Task started") for t in self.fake.texts()))
        run_id = [t for t in self.fake.texts() if t.startswith("Task started")][0].split("id: ")[1]
        self.wait(self.idle, timeout=20)
        self.fake.message(CEO_TOKEN, f"/report {run_id}")
        self.wait(lambda: any("<b>Report</b>" in p["text"] and run_id in p["text"] for p in self.html_msgs()))


if __name__ == "__main__":
    unittest.main()
