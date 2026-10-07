"""Task documents: a main task given as a Markdown file, an upload or a link, read into the brief
every agent of the run gets (flow, dashboard API and command line).

Run: python -m unittest discover -s tests
"""
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, taskdocs  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")
SPEC = "# Login page with lockout\n\n- email + password\n- lock the account after 5 failed attempts\n"


class Pages(BaseHTTPRequestHandler):
    """Serves /spec.md (Markdown), /page (an HTML page) and 404 for anything else."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.endswith("/spec.md"):
            body, ctype = SPEC.encode(), "text/markdown; charset=utf-8"
        elif self.path == "/page":
            body, ctype = b"<html><body>hi</body></html>", "text/html"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_pages(test):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test.addCleanup(srv.server_close)
    test.addCleanup(srv.shutdown)
    return f"http://127.0.0.1:{srv.server_port}"


class TaskDocsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return path

    def test_title(self):
        self.assertEqual(taskdocs.title_of(SPEC), "Login page with lockout")
        self.assertEqual(taskdocs.title_of("---\ntitle: 'From front matter'\n---\n# Heading"), "From front matter")
        self.assertEqual(taskdocs.title_of("\n\nFirst line of text\nmore"), "First line of text")
        self.assertEqual(taskdocs.title_of("## **Bold heading**"), "Bold heading")
        self.assertEqual(len(taskdocs.title_of("# " + "x" * 300)), 120)

    def test_file(self):
        doc = taskdocs.from_file(self.write("login.md", SPEC))
        self.assertEqual((doc["name"], doc["source"], doc["title"]), ("login.md", "file", "Login page with lockout"))
        self.assertEqual(taskdocs.from_file(self.write("bom.md", b"\xef\xbb\xbf# BOM title\n"))["title"], "BOM title")
        self.assertEqual(taskdocs.from_file(self.write("u16.md", "# Wide\n".encode("utf-16")))["title"], "Wide")
        for name, data, err in [("bin.md", b"\x00\x01\x02", "not a text file"), ("empty.md", b"  \n", "empty"),
                                ("big.md", b"a" * (taskdocs.MAX_BYTES + 1), "larger than")]:
            with self.assertRaisesRegex(taskdocs.TaskDocError, err):
                taskdocs.from_file(self.write(name, data))
        with self.assertRaisesRegex(taskdocs.TaskDocError, "no such file"):
            taskdocs.from_file(os.path.join(self.tmp, "missing.md"))

    def test_upload(self):
        doc = taskdocs.from_upload("../../etc/spec.md", SPEC)
        self.assertEqual((doc["name"], doc["source"]), ("spec.md", "upload"))  # no path from the browser
        with self.assertRaisesRegex(taskdocs.TaskDocError, "Markdown or text"):
            taskdocs.from_upload("run.sh", "echo hi")

    def test_raw_links(self):
        self.assertEqual(taskdocs.raw_url("https://github.com/o/r/blob/main/docs/spec.md"),
                         "https://raw.githubusercontent.com/o/r/main/docs/spec.md")
        self.assertEqual(taskdocs.raw_url("https://gitlab.example.com/g/p/-/blob/dev/a.md"),
                         "https://gitlab.example.com/g/p/-/raw/dev/a.md")
        self.assertEqual(taskdocs.raw_url("https://gist.github.com/me/abc123"),
                         "https://gist.githubusercontent.com/me/abc123/raw")
        self.assertEqual(taskdocs.raw_url("https://example.com/x.md"), "https://example.com/x.md")

    def test_link(self):
        base = serve_pages(self)
        doc = taskdocs.from_url(base + "/docs/spec.md")
        self.assertEqual((doc["name"], doc["source"], doc["title"], doc["url"]),
                         ("spec.md", "link", "Login page with lockout", base + "/docs/spec.md"))
        with self.assertRaisesRegex(taskdocs.TaskDocError, "web page"):
            taskdocs.from_url(base + "/page")
        with self.assertRaisesRegex(taskdocs.TaskDocError, "HTTP 404"):
            taskdocs.from_url(base + "/nope.md")
        with self.assertRaisesRegex(taskdocs.TaskDocError, "only http"):
            taskdocs.from_url("file:///etc/passwd")

    def test_command_line_arguments(self):
        from babd import __main__ as cli
        path = self.write("login.md", SPEC)
        tasks = cli.tasks_from_args(["Plain goal", path], [])
        self.assertEqual([(g, [d["name"] for d in docs]) for g, docs in tasks],
                         [("Plain goal", []), ("Login page with lockout", ["login.md"])])
        tasks = cli.tasks_from_args(["Build what the spec says"], [path])
        self.assertEqual(tasks[0][0], "Build what the spec says")
        self.assertEqual(tasks[0][1][0]["text"], SPEC.strip())
        self.assertEqual(cli.tasks_from_args([], [path])[0][0], "Login page with lockout")
        self.assertEqual(cli.tasks_from_args(["notes.md"], [])[0], ("notes.md", []))  # not a file: plain text


class RunWithDocumentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(self.tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        self.cfg = copy.deepcopy(load_config(FIXTURE))
        self.cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False},
                                   mattpocock={"enabled": False}, parallel_prep=True)
        for a in self.cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"

    def test_every_agent_gets_the_document(self):
        prompts = []

        def ask(agent, prompt, **kw):
            prompts.append((agent.id, prompt))
            return td.scripted_ask(agent, prompt, **kw)

        doc = taskdocs.from_upload("login.md", SPEC)
        with mock.patch.object(Agent, "ask", ask):
            state = flow.Run(Team(self.cfg, log=lambda m: None), "Build it", docs=[doc],
                             approver=lambda r: (True, "")).execute()
        self.assertEqual(state["status"], "done", state["error"])
        self.assertEqual({a for a, _ in prompts}, {"lead", "architect", "developer", "qa", "devops"})
        for agent_id, prompt in prompts:
            self.assertIn("lock the account after 5 failed attempts", prompt, agent_id)
            self.assertIn("## Task document: login.md", prompt)
        self.assertEqual(state["documents"], [{"name": "login.md", "source": "upload", "title": "Login page with lockout",
                                               "chars": len(SPEC.strip())}])
        with open(os.path.join(state["dir"], "00-task.md")) as f:
            self.assertIn("5 failed attempts", f.read())


class DocumentApiTest(unittest.TestCase):
    setUp = td.DashboardTest.setUp
    call = td.DashboardTest.call
    wait = td.DashboardTest.wait

    def idle(self):
        with self.dash.tasks_lock:
            return not self.dash.active and not self.dash.queue

    def test_goal_from_upload_and_link(self):
        base = serve_pages(self)
        self.call("PUT", "/api/project", {"require_approval": False})
        with mock.patch.object(Agent, "ask", td.scripted_ask):
            status, run = self.call("POST", "/api/runs", {"goal": "", "documents": [{"name": "login.md", "content": SPEC}]})
            self.assertEqual(status, 200, run)
            self.assertEqual(run["goal"], "Login page with lockout")
            self.assertEqual(run["documents"][0]["name"], "login.md")
            status, out = self.call("POST", "/api/tasks", {"goals": ["Plain task"], "links": [base + "/spec.md"],
                                                          "documents": [{"name": "b.md", "content": "# Second spec\nbody"}]})
            self.assertEqual(status, 200, out)
            self.assertEqual([t["goal"] for t in out["tasks"]], ["Plain task", "Second spec", "Login page with lockout"])
            self.wait(self.idle, timeout=20)
        status, doc = self.call("GET", f"/api/runs/{run['id']}/document")
        self.assertEqual(status, 200)
        self.assertIn("5 failed attempts", doc["text"])
        _, board = self.call("GET", "/api/board")
        linked = [t for t in board["tasks"] if t["documents"] and t["documents"][0]["source"] == "link"][0]
        self.assertEqual(linked["documents"][0]["url"], base + "/spec.md")
        self.assertEqual(self.call("GET", f"/api/runs/{out['tasks'][0]['id']}/document")[0], 404)

    def test_bad_documents(self):
        base = serve_pages(self)
        for body, err in [({"documents": [{"name": "x.exe", "content": "MZ"}]}, "Markdown or text"),
                          ({"links": [base + "/page"]}, "web page"),
                          ({"links": [base + "/missing.md"]}, "HTTP 404"),
                          ({"goal": "", "documents": []}, "goal is empty")]:
            status, out = self.call("POST", "/api/runs", body)
            self.assertEqual(status, 400, body)
            self.assertIn(err, out["error"])
        self.assertFalse(self.dash.active or self.dash.queue)


if __name__ == "__main__":
    unittest.main()
