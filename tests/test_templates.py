"""Task templates: the shipped ones, the API, saving your own.

Run: python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_dashboard as td  # noqa: E402
from babd import taskdocs, templates  # noqa: E402


class TemplatesTest(unittest.TestCase):
    def test_shipped_templates(self):
        ts = {t["id"]: t for t in templates.list_templates()}
        self.assertTrue({"feature", "bugfix", "refactor", "research", "api-endpoint"} <= set(ts))
        for t in ts.values():
            self.assertTrue(t["title"] and t["description"] and t["body"].startswith("# "), t["id"])
            self.assertNotIn("---", t["body"].splitlines()[0])
            # a filled-in template is a valid task document named by its heading
            self.assertTrue(taskdocs.make(f"{t['id']}.md", t["body"], "upload")["title"])


class TemplatesApiTest(unittest.TestCase):
    setUp_dash = td.DashboardTest.setUp
    call = td.DashboardTest.call

    def setUp(self):
        self.setUp_dash()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(templates.TEMPLATES_DIR, os.path.join(tmp, "t"))
        p = mock.patch.object(templates, "TEMPLATES_DIR", os.path.join(tmp, "t"))
        p.start()
        self.addCleanup(p.stop)

    def test_list_and_save(self):
        ids = [t["id"] for t in self.call("GET", "/api/templates")[1]["templates"]]
        self.assertIn("bugfix", ids)
        status, t = self.call("POST", "/api/templates", {"id": "my-ui-tweak", "title": "UI tweak\nx", "body": "# UI tweak\n\n- what"})
        self.assertEqual((status, t["id"], t["title"]), (200, "my-ui-tweak", "UI tweak x"))
        self.assertIn("my-ui-tweak", [t["id"] for t in self.call("GET", "/api/templates")[1]["templates"]])
        self.assertEqual(self.call("POST", "/api/templates", {"id": "../evil", "body": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/templates", {"id": "ok", "body": " "})[0], 400)


if __name__ == "__main__":
    unittest.main()
