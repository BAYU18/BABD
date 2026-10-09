"""Teks baris memory live run: helper murni di app.js + ketiga titik render memakainya.

Helper JS diuji lewat `node` bila tersedia (repo tidak punya harness JS);
assertion teks pada app.js selalu berjalan.

Run: python -m unittest discover -s tests
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "babd", "dashboard", "static", "app.js")
NODE = shutil.which("node")


def app_js():
    with open(APP_JS) as f:
        return f.read()


def helper_block():
    src = app_js()
    m = re.search(r"// ---- memory text helpers.*?// ---- end memory text helpers ----", src, re.S)
    assert m, "blok helper memory tidak ditemukan di app.js"
    return m.group(0)


def js_eval(cases):
    """Jalankan helper blok di node, kembalikan list hasil per kasus."""
    script = helper_block() + "\nconst cases = " + json.dumps(cases) + ";\n" + \
        "console.log(JSON.stringify(cases.map((c) => eval(c))));"
    out = subprocess.run([NODE, "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


@unittest.skipUnless(NODE, "node tidak ada: helper JS tidak diuji langsung")
class MemoryHelperTest(unittest.TestCase):
    def test_keywords_split_on_or(self):
        got = js_eval([
            "memoryKeywords('a or b or c')",
            "memoryKeywords('')",
            "memoryKeywords('researcher')",
            "memoryKeywords('cats or dogs')",
        ])
        self.assertEqual(got, [["a", "b", "c"], [], ["researcher"], ["cats", "dogs"]])

    def test_keywords_capped_at_six(self):
        got = js_eval(["memoryKeywords('a or b or c or d or e or f or g or h').join(',')"])[0]
        self.assertTrue(got.startswith("a,b,c,d,e,f"), got)
        self.assertTrue(got.endswith("…"), got)

    def test_count_line_singular_plural(self):
        got = js_eval([
            "memoryCountLine(3, 1)",
            "memoryCountLine(1, 0)",
            "memoryCountLine(0, 0)",
            "memoryCountLine(undefined, 'x')",
            "memoryCountLine('x', 2)",
        ])
        # (0,0) dan nilai non-numerik -> baris jumlah kosong (spec D2); tidak pernah 'NaN'
        self.assertEqual(got, ["3 catatan, 1 halaman", "1 catatan, 0 halaman", "", "", "0 catatan, 2 halaman"])

    def test_headline_read_empty_and_write(self):
        got = js_eval([
            "JSON.stringify(memoryHeadline({op:'read',facts:3,pages:1,query:'a or b',items:['f1','p1']}))",
            "JSON.stringify(memoryHeadline({op:'read',facts:0,pages:0,query:'x',items:[]}))",
            "JSON.stringify(memoryHeadline({op:'write',page:'some/slug'}))",
            "JSON.parse(JSON.stringify(memoryHeadline({op:'read',facts:2,pages:0,query:'q'}))).detail.length",
        ])
        first = json.loads(got[0])
        self.assertEqual(first["label"], "Membaca memori tim")
        self.assertEqual(first["count"], "3 catatan, 1 halaman")
        self.assertEqual(first["keywords"], ["a", "b"])
        self.assertEqual(first["detail"], ["f1", "p1"])
        self.assertFalse(first["empty"])
        self.assertTrue(json.loads(got[1])["empty"])
        self.assertEqual(json.loads(got[2])["label"], "Menyimpan ke memori tim")
        self.assertEqual(got[3], 0)  # items hilang -> detail array kosong, bukan undefined

    def test_log_text_hides_raw_or(self):
        got = js_eval([
            "memoryLogText('QA', {op:'read',facts:3,pages:1,query:'tambah or agent or repo'})",
            "memoryLogText('QA', {op:'read',facts:0,pages:0,query:'x'})",
        ])
        self.assertIn("Membaca memori tim", got[0])
        self.assertIn("3 catatan, 1 halaman", got[0])
        self.assertIn("kata kunci: tambah, agent, repo", got[0])
        self.assertNotIn(" or ", got[0])
        self.assertIn("tidak ada memori terkait", got[1])


class RenderSitesTest(unittest.TestCase):
    """Ketiga titik render di app.js memakai helper, bukan 'fact(s)' / query mentah."""

    def test_memory_item_uses_helper(self):
        src = app_js()
        self.assertIn("memoryHeadline(", src)
        self.assertNotRegex(src, r"read gbrain · \$\{m\.facts\} fact\(s\)")
        self.assertNotRegex(src, r"\$\{m\.facts\} fact\(s\)")

    def test_event_lines_use_helper(self):
        src = app_js()
        self.assertNotIn("read gbrain", src)
        self.assertIn("Membaca memori tim", src)
        self.assertIn("Menyimpan ke memori tim", src)


if __name__ == "__main__":
    unittest.main()
