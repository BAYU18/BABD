"""API keys survive restarts: .env plus a backup outside the installation, empty variables don't
hide a saved key, `export` lines are read.

Run: python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babd import config  # noqa: E402


class SecretsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env, self.backup = os.path.join(self.tmp, ".env"), os.path.join(self.tmp, "cfg", "babd", "s.env")
        for p in (mock.patch.object(config, "ENV_PATH", self.env), mock.patch.object(config, "SECRETS_BACKUP", self.backup),
                  mock.patch.dict(os.environ, {}, clear=False)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("KEY1", None)

    def restart(self):
        os.environ.pop("KEY1", None)
        return config.load_dotenv()

    def test_key_survives_a_restart(self):
        config.set_env_var("KEY1", "sk-1")
        self.assertEqual(oct(os.stat(self.backup).st_mode & 0o777), "0o600")
        self.assertEqual(self.restart(), ["KEY1"])
        self.assertEqual(os.environ["KEY1"], "sk-1")

    def test_lost_env_file_is_restored_from_the_backup(self):
        config.set_env_var("KEY1", "sk-2")
        os.remove(self.env)  # a fresh clone / reinstall / git clean -x
        self.restart()
        self.assertEqual(os.environ["KEY1"], "sk-2")
        with open(self.env) as f:
            self.assertIn("KEY1=sk-2", f.read())

    def test_empty_environment_variable_does_not_hide_the_key(self):
        config.set_env_var("KEY1", "sk-3")
        os.environ["KEY1"] = ""  # e.g. Environment=KEY1= in a systemd unit, or `export KEY1=` in a profile
        config.load_dotenv()
        self.assertEqual(os.environ["KEY1"], "sk-3")

    def test_export_lines_and_removal(self):
        with open(self.env, "w") as f:
            f.write('export KEY1="sk-4"\n# note\n')
        self.restart()
        self.assertEqual(os.environ["KEY1"], "sk-4")
        config.set_env_var("KEY1", "sk-5")
        with open(self.env) as f:
            self.assertEqual(f.read().count("KEY1="), 1)
        config.set_env_var("KEY1", "")
        self.restart()
        self.assertNotIn("KEY1", os.environ)

    def test_missing_keys(self):
        cfg = {"agents": [{"id": "lead", "llm": {"api_key_env": "KEY1"}}, {"id": "qa", "llm": {"api_key_env": "KEY1"}},
                          {"id": "dev", "llm": {"api_key": "inline", "api_key_env": "X"}}]}
        self.assertEqual(config.missing_keys(cfg), {"KEY1": ["lead", "qa"]})


if __name__ == "__main__":
    unittest.main()
