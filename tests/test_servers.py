"""Servers the agents can reach: validation (nothing can be smuggled into the SSH config), the SSH
config, which agents see which server, key generation, the connection test, the dashboard API.

Run: python -m unittest discover -s tests
"""
import copy
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import flow, servers  # noqa: E402
from babd.config import load_config  # noqa: E402
from babd.team import Agent, Team  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "agents.json")


def use_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    p = mock.patch.object(servers, "ssh_dir", lambda: os.path.join(tmp, "ssh"))
    p.start()
    test.addCleanup(p.stop)
    return tmp


class ServersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = use_tmp(self)
        self.cfg = {"agents": [], "servers": [{"id": "lpnotif", "name": "Server lpnotif", "host": "203.0.113.7",
                                               "key": os.path.join(self.tmp, "keys", "lp"), "notes": "nginx"}]}

    def test_nothing_can_be_smuggled_in(self):
        for bad in ({"id": "x", "host": "-oProxyCommand=touch /tmp/p"}, {"id": "x", "host": "a b"},
                    {"id": "x", "host": "h\nProxyCommand x"}, {"id": "x", "host": "h", "user": "-x"},
                    {"id": "x", "host": "h", "port": 70000}, {"id": "x", "host": "h", "key": "~/.ssh/a key"},
                    {"id": "x", "host": "h", "key": "$(id)"}, {"id": "X Y", "host": "h"}):
            with self.assertRaises(servers.ServerError, msg=bad):
                servers.normalize(bad)
        n = servers.normalize({"name": "Server lpnotif", "host": "lp.example.com"})
        self.assertEqual((n["id"], n["user"], n["port"], n["key"], n["agents"]),
                         ("server-lpnotif", "root", 22, "~/.ssh/babd_server-lpnotif", ["devops"]))

    def test_ssh_config_and_prompts(self):
        path = servers.write_config(self.cfg)
        text = open(path).read()
        self.assertIn("Host lpnotif\n  HostName 203.0.113.7\n  User root\n  Port 22", text)
        self.assertIn("IdentitiesOnly yes", text)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        block = servers.prompt_block(self.cfg, "devops")
        self.assertIn(f"ssh -F {path} <server id>", block)
        self.assertIn("lpnotif: Server lpnotif (root@203.0.113.7:22) — nginx", block)
        self.assertEqual(servers.prompt_block(self.cfg, "developer"), "")

    @unittest.skipUnless(shutil.which("ssh-keygen") and shutil.which("ssh"), "needs openssh-client")
    def test_keygen_and_test(self):
        s = servers.get(self.cfg, "lpnotif")
        pub = servers.keygen(s)
        self.assertTrue(pub.startswith("ssh-ed25519 ") and pub.endswith("babd Server lpnotif"))
        self.assertEqual(servers.keygen(s), pub)  # the same key next time
        cfg = {"servers": [{"id": "dead", "host": "127.0.0.1", "port": 1, "key": s["key"]}]}
        r = servers.test(cfg, "dead", timeout=20)
        self.assertFalse(r["ok"])


class ServersInFlowTest(unittest.TestCase):
    def test_only_the_listed_agents_get_the_servers(self):
        tmp = use_tmp(self)
        p = mock.patch.object(flow, "RUNS_DIR", os.path.join(tmp, "runs"))
        p.start()
        self.addCleanup(p.stop)
        cfg = copy.deepcopy(load_config(FIXTURE))
        cfg["project"].update(gbrain={"enabled": False}, superpowers={"enabled": False}, mattpocock={"enabled": False},
                              parallel_prep=False, require_approval=[], fast_lane=True)
        cfg["servers"] = [{"id": "lpnotif", "host": "203.0.113.7"}]
        for a in cfg["agents"]:
            a["harness"] = {"type": "direct"}
            a["llm"]["api_key"] = "test"
        prompts = []

        def ask(agent, prompt, **kw):
            prompts.append((agent.id, prompt))
            if "Decide who is needed" in prompt:
                return '{"route": "direct", "agent": "devops", "task": "check disk on lpnotif"}'
            return "df: 40% used"
        with mock.patch.object(Agent, "ask", ask):
            state = flow.Run(Team(cfg, log=lambda m: None), "cek disk server lpnotif").execute()
        self.assertEqual(state["status"], "done", state["error"])
        self.assertIn("Servers the team can reach over SSH", prompts[0][1])  # the Team Lead knows
        self.assertIn("ssh -F", prompts[1][1])  # DevOps can connect
        self.assertTrue(os.path.exists(servers.config_path()))


class ServersApiTest(unittest.TestCase):
    setUp_dash = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def setUp(self):
        self.setUp_dash()
        self.keys = use_tmp(self)

    @unittest.skipUnless(shutil.which("ssh-keygen") and shutil.which("ssh"), "needs openssh-client")
    def test_save_keygen_test(self):
        key = os.path.join(self.keys, "k")
        status, out = self.call("PUT", "/api/servers", {"servers": [{"id": "lpnotif", "host": "127.0.0.1", "port": 1, "key": key}]})
        self.assertEqual(status, 200, out)
        self.assertFalse(out["servers"][0]["key_exists"])
        _, state = self.call("GET", "/api/state")
        self.assertEqual(state["servers"][0]["id"], "lpnotif")
        status, out = self.call("POST", "/api/servers/lpnotif/keygen")
        self.assertEqual(status, 200, out)
        self.assertTrue(out["public_key"].startswith("ssh-ed25519"))
        self.assertNotIn("PRIVATE", str(out))
        status, out = self.call("POST", "/api/servers/lpnotif/test")
        self.assertEqual((status, out["ok"]), (200, False))
        self.assertEqual(self.call("PUT", "/api/servers", {"servers": [{"id": "x", "host": "h", "agents": ["nobody"]}]})[0], 400)
        self.assertEqual(self.call("PUT", "/api/servers", {"servers": [{"id": "x", "host": "-oProxyCommand=id"}]})[0], 400)
        self.assertEqual(self.call("POST", "/api/servers/nope/test")[0], 400)


if __name__ == "__main__":
    unittest.main()
