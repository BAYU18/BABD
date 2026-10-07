"""Security fixes: git options can't be smuggled in through a project's repo or branch, agents never
see BABD's secrets in their environment, Telegram @usernames can't be taken over, groups are off by
default, bad request sizes are refused, BABD's data folders are private.

Run: python -m unittest discover -s tests
"""
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import config, projects, telegram  # noqa: E402
from babd.harness import create_harness  # noqa: E402


class GitInjectionTest(unittest.TestCase):
    def test_repo_and_branch_cannot_be_options(self):
        for repo in ("--upload-pack=touch /tmp/pwned", "-u x", "ext::sh -c id", "foo bar", "ext::x"):
            with self.assertRaises(projects.ProjectError, msg=repo):
                projects.normalize({"id": "p", "repo": repo})
        for branch in ("--force", "-x", "a..b", "a b", "x@{1}"):
            with self.assertRaises(projects.ProjectError, msg=branch):
                projects.normalize({"id": "p", "branch": branch})
        for repo in ("https://github.com/a/b.git", "git@github.com:a/b.git", "ssh://git@host/x.git", "/srv/git/x"):
            self.assertEqual(projects.normalize({"id": "p", "repo": repo})["repo"], repo)
        self.assertEqual(projects.normalize({"id": "p", "branch": "feature/login-2"})["branch"], "feature/login-2")

    def test_dashboard_refuses_them(self):
        t = td.DashboardTest("setUp")
        t.setUp()
        self.addCleanup(t.doCleanups)
        status, out = t.call("PUT", "/api/projects", {"projects": [{"name": "x", "repo": "--upload-pack=id"}]})
        self.assertEqual(status, 400, out)


class SecretEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env_path = os.path.join(self.tmp, ".env")
        with open(env_path, "w") as f:
            f.write("KEY1=sk-team\nTELEGRAM_CEO_BOT_TOKEN=123:abc\n")  # everything in .env counts as a secret
        for p in (mock.patch.object(config, "ENV_PATH", env_path),
                  mock.patch.object(config, "SECRETS_BACKUP", os.path.join(self.tmp, "b.env")),
                  mock.patch.object(config, "load_config", lambda path=None: {"agents": [
                      {"id": "qa", "llm": {"api_key_env": "QA_KEY"}}]}),
                  mock.patch.dict(os.environ, {"KEY1": "sk-team", "TELEGRAM_CEO_BOT_TOKEN": "123:abc", "QA_KEY": "sk-qa",
                                               "BABD_DASHBOARD_PASSWORD_HASH": "pbkdf2$x", "MY_TOOL_SETTING": "fine",
                                               "TELEGRAM_DEV_BOT_TOKEN": "456:def"})):
            p.start()
            self.addCleanup(p.stop)

    def test_agents_do_not_inherit_babd_secrets(self):
        h = create_harness({"id": "dev", "llm": {"model": "m", "api_key_env": "KEY1"},
                            "harness": {"type": "process", "command": "env"}})
        env = h.child_env({"BABD_AGENT_ID": "dev"})
        for name in ("KEY1", "TELEGRAM_CEO_BOT_TOKEN", "QA_KEY", "BABD_DASHBOARD_PASSWORD_HASH", "TELEGRAM_DEV_BOT_TOKEN"):
            self.assertNotIn(name, env)
        self.assertEqual(env["MY_TOOL_SETTING"], "fine")  # not a secret: still there
        self.assertIn("PATH", env)

    def test_routing_adds_back_only_the_agents_own_key(self):
        h = create_harness({"id": "dev", "llm": {"model": "m", "api": "openai", "base_url": "http://x/v1", "api_key_env": "KEY1"},
                            "harness": {"type": "process", "command": "env"}})
        out = h.run_process(["sh", "-c", 'echo "[$BABD_LLM_API_KEY][$KEY1][$QA_KEY][$TELEGRAM_CEO_BOT_TOKEN]"'], h_routing(h))
        self.assertEqual(out.strip(), "[sk-team][][][]")  # its own key, only through the routing variables

    def test_pass_env_keeps_a_variable_on_purpose(self):
        h = create_harness({"id": "devops", "llm": {"model": "m"},
                            "harness": {"type": "process", "command": "env", "pass_env": ["TELEGRAM_DEV_BOT_TOKEN"]}})
        self.assertEqual(h.child_env({})["TELEGRAM_DEV_BOT_TOKEN"], "456:def")

    def test_project_tests_do_not_see_secrets(self):
        out = projects.run_tests('echo "[$MY_TOOL_SETTING][$KEY1][$TELEGRAM_CEO_BOT_TOKEN]"', self.tmp)["output"]
        self.assertEqual(out.strip(), "[fine][][]")


def h_routing(h):
    from babd.harness.routing import generic_routing
    return generic_routing(h.llm)


class TelegramIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.object(telegram, "STATE_PATH", os.path.join(self.tmp, "telegram.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_a_username_is_tied_to_the_first_account(self):
        bot = telegram.Bot("ceo", "t", ["@boss", "42"])
        self.assertTrue(bot.is_allowed({"id": 7, "username": "Boss"}))
        self.assertTrue(bot.is_allowed({"id": 7, "username": "boss"}))
        self.assertFalse(bot.is_allowed({"id": 8, "username": "boss"}))  # someone who took the name later
        self.assertTrue(bot.is_allowed({"id": 42}))
        self.assertFalse(bot.is_allowed({"id": 9, "username": "boss", "is_bot": True}))
        self.assertFalse(bot.is_allowed(None))

    def test_private_chats_only_by_default(self):
        self.assertTrue(telegram.Bot("ceo", "t", []).chat_ok({"type": "private"}))
        self.assertFalse(telegram.Bot("ceo", "t", []).chat_ok({"type": "group"}))
        self.assertFalse(telegram.Bot("ceo", "t", []).chat_ok({"type": "supergroup"}))
        self.assertTrue(telegram.Bot("ceo", "t", [], allow_groups=True).chat_ok({"type": "group"}))


class RequestAndFilesTest(unittest.TestCase):
    def test_negative_content_length_is_refused(self):
        import http.client
        t = td.DashboardTest("setUp")
        t.setUp()
        self.addCleanup(t.doCleanups)
        host, port = t.base.split("//")[1].split(":")
        c = http.client.HTTPConnection(host, int(port), timeout=5)
        c.putrequest("PUT", "/api/project")
        c.putheader("X-BABD-Token", td.TOKEN)
        c.putheader("Content-Length", "-1")
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)

    def test_data_folders_are_private(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "runs"), mode=0o755)
        os.chmod(os.path.join(tmp, "runs"), 0o755)
        config.secure_dirs(tmp)
        for name in config.PRIVATE_DIRS:
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(tmp, name)).st_mode), 0o700, name)


if __name__ == "__main__":
    unittest.main()
