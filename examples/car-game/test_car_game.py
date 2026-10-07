"""Tests for index.html — encodes the Architect's QA acceptance criteria for the
2D car game (endless lane-dodger).

These tests verify behavior through the public seam: the file `index.html` as
parsed by a standard HTML5 parser + source-text inspection. They assert exactly
what the Architect's spec requires (docs/superpowers/specs/2026-10-07-2d-car-game-design.md),
nothing about implementation details beyond what the spec mandates.

Runtime/behavioral tests that need a live browser (collision, restart, score
increment, no-console-errors) live in workspace/verify-game.mjs (puppeteer).
This file covers the static/source-level criteria; the puppeteer harness covers
the dynamic ones through the window.__GAME__ debug hook.

Run: python -m pytest test_car_game.py -v
  or: python -m unittest test_car_game
"""

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

INDEX_HTML = Path(__file__).parent / "index.html"


class _HTMLStructureExtractor(HTMLParser):
    """Extracts tags, attributes, and text content from an HTML document.

    This is test-only utility code — it lives in the test file, not in any
    production class, per the writing-good-tests rules.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs_by_tag: dict[str, list[dict[str, str | None]]] = {}
        self.text_parts: list[str] = []
        self._current_text: list[str] = []
        self._in_title = False
        self.title_texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self.tags.append(tag_lower)
        attr_dict = dict(attrs)
        self.attrs_by_tag.setdefault(tag_lower, []).append(attr_dict)
        if tag_lower == "title":
            self._in_title = True
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "title":
            self._in_title = False
            self.title_texts.append("".join(self._current_text))

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._in_title:
            self._current_text.append(data)

    def handle_decl(self, decl: str) -> None:
        self.tags.append(f"!{decl.strip().lower()}")


class TestCarGameHtmlStructure(unittest.TestCase):
    """QA criterion 1: File loads with no external dependencies."""

    def setUp(self) -> None:
        self.assertTrue(INDEX_HTML.exists(), f"index.html not found at {INDEX_HTML}")
        self.raw = INDEX_HTML.read_text(encoding="utf-8")
        self.parser = _HTMLStructureExtractor()
        self.parser.feed(self.raw)

    def test_file_is_non_empty(self) -> None:
        self.assertTrue(self.raw.strip(), "index.html is empty")

    def test_begins_with_doctype_html(self) -> None:
        doctype_tags = [t for t in self.parser.tags if t.startswith("!doctype")]
        self.assertTrue(len(doctype_tags) >= 1, "No <!DOCTYPE html> declaration found")
        self.assertIn("doctype html", doctype_tags[0])

    def test_has_html_root_element(self) -> None:
        self.assertIn("html", self.parser.tags)

    def test_has_head_and_body(self) -> None:
        self.assertIn("head", self.parser.tags)
        self.assertIn("body", self.parser.tags)

    def test_title_is_2d_car_game(self) -> None:
        self.assertTrue(len(self.parser.title_texts) >= 1, "No <title> element found")
        self.assertEqual(
            self.parser.title_texts[0].strip(),
            "2D Car Game",
            f"Expected <title>2D Car Game</title>, got '{self.parser.title_texts[0]}'",
        )

    def test_head_contains_utf8_charset_meta(self) -> None:
        meta_attrs_list = self.parser.attrs_by_tag.get("meta", [])
        found_charset = any(
            (attrs.get("charset") or "").upper() == "UTF-8"
            for attrs in meta_attrs_list
        )
        self.assertTrue(found_charset, f"No <meta charset='UTF-8'> found; metas: {meta_attrs_list}")

    def test_has_exactly_one_canvas_with_id_game(self) -> None:
        canvas_attrs = self.parser.attrs_by_tag.get("canvas", [])
        self.assertEqual(len(canvas_attrs), 1, f"Expected 1 <canvas>, found {len(canvas_attrs)}")
        self.assertEqual(canvas_attrs[0].get("id"), "game", "canvas id must be 'game'")

    def test_canvas_has_400x600_dimensions(self) -> None:
        canvas_attrs = self.parser.attrs_by_tag.get("canvas", [])
        self.assertTrue(len(canvas_attrs) >= 1, "No <canvas> found")
        self.assertEqual(canvas_attrs[0].get("width"), "400", "canvas width must be 400")
        self.assertEqual(canvas_attrs[0].get("height"), "600", "canvas height must be 600")

    def test_no_external_link_tags(self) -> None:
        self.assertNotIn("link", self.parser.tags, "External <link> tag found")

    def test_no_external_script_src(self) -> None:
        script_attrs = self.parser.attrs_by_tag.get("script", [])
        has_external = any(a.get("src") for a in script_attrs)
        self.assertFalse(has_external, "External <script src=...> found")

    def test_no_img_tags(self) -> None:
        self.assertNotIn("img", self.parser.tags, "<img> tag found — no external images allowed")

    def test_no_http_or_https_urls_in_source(self) -> None:
        # The file must run from file:// with no network. No URL strings.
        urls = re.findall(r'https?://[^\s"\'<>]+', self.raw)
        self.assertEqual(urls, [], f"Found http(s) URLs in source: {urls}")

    def test_has_inline_style_block(self) -> None:
        self.assertIn("style", self.parser.tags, "No inline <style> block found")

    def test_has_inline_script_block(self) -> None:
        self.assertIn("script", self.parser.tags, "No inline <script> block found")


class TestCarGameControlsAndModel(unittest.TestCase):
    """QA criteria 2-3: Arrow handlers wired; car moves and is clamped to bounds.

    These are source-level checks. The puppeteer harness (verify-game.mjs)
    does the dynamic verification through window.__GAME__.
    """

    def setUp(self) -> None:
        self.assertTrue(INDEX_HTML.exists(), f"index.html not found at {INDEX_HTML}")
        self.raw = INDEX_HTML.read_text(encoding="utf-8")
        self.lower = self.raw.lower()

    def test_has_keydown_event_listener(self) -> None:
        # Must register a keydown listener on document or window
        self.assertTrue(
            re.search(r'addEventListener\s*\(\s*["\']keydown', self.raw),
            "No keydown event listener found",
        )

    def test_handles_arrow_left_and_right(self) -> None:
        self.assertIn("arrowleft", self.lower, "ArrowLeft not handled")
        self.assertIn("arrowright", self.lower, "ArrowRight not handled")

    def test_calls_prevent_default_on_arrows(self) -> None:
        # preventDefault must be called to stop page scroll on arrows/space
        self.assertIn("preventdefault", self.lower, "preventDefault() not called")

    def test_has_lane_clamping_logic(self) -> None:
        # The spec requires clamping carLane to [0, 3] — look for clamp pattern
        # or explicit min/max bounds. carLane must never exceed 3 or go below 0.
        self.assertTrue(
            re.search(r'(clamp|min|max|carLane\s*[<>=!])', self.raw),
            "No lane-clamping logic found (clamp/min/max/carLane bound check)",
        )

    def test_has_request_animation_frame(self) -> None:
        self.assertIn(
            "requestanimationframe", self.lower,
            "No requestAnimationFrame found — game loop must use rAF",
        )

    def test_has_game_state_machine(self) -> None:
        # States: start, playing, over
        self.assertIn('"playing"', self.raw.lower(), 'state "playing" not found')
        self.assertIn('"over"', self.raw.lower(), 'state "over" not found')

    def test_has_collision_detection(self) -> None:
        # AABB overlap between car and obstacle rects
        self.assertIn("collision", self.lower, "no collision logic found")

    def test_has_scoring(self) -> None:
        self.assertIn("score", self.lower, "no score logic found")

    def test_has_local_storage_high_score(self) -> None:
        self.assertIn("localstorage", self.lower, "localStorage not used for high score")
        self.assertIn("highscore", self.lower, "highScore not found")
        self.assertIn("cargamehighscore", self.lower, 'localStorage key "carGameHighScore" not found')

    def test_local_storage_wrapped_in_try_catch(self) -> None:
        # Spec: all localStorage reads/writes must be try/catch
        # Find localStorage usage and check try/catch nearby
        self.assertIn("try", self.lower, "no try/catch found for localStorage safety")
        self.assertIn("catch", self.lower, "no catch block found for localStorage safety")

    def test_has_window_game_debug_hook(self) -> None:
        # Spec §7: Developer exposes window.__GAME__ with start/step/setKey/snapshot
        self.assertIn("__game__", self.lower, "window.__GAME__ debug hook not found")

    def test_game_hook_has_snapshot_method(self) -> None:
        self.assertIn("snapshot", self.lower, "__GAME__.snapshot() not found")

    def test_game_hook_has_step_method(self) -> None:
        self.assertIn("step", self.lower, "__GAME__.step() not found")

    def test_has_dt_clamping(self) -> None:
        # Spec: dt clamped to max 0.05s to avoid huge jumps after tab-switch
        self.assertIn("0.05", self.raw, "dt clamp to 0.05 not found")

    def test_has_obstacle_spawning(self) -> None:
        self.assertIn("obstacle", self.lower, "no obstacle logic found")
        self.assertIn("spawn", self.lower, "no spawn logic found")

    def test_has_difficulty_ramp(self) -> None:
        # spawnInterval decreases and obstacleSpeed increases with score
        self.assertIn("spawninterval", self.lower, "spawnInterval not found")
        self.assertIn("obstaclespeed", self.lower, "obstacleSpeed not found")

    def test_no_alert_or_confirm(self) -> None:
        self.assertNotIn("alert(", self.lower, "alert() is forbidden — draw on canvas")
        self.assertNotIn("confirm(", self.lower, "confirm() is forbidden")
        self.assertNotIn("prompt(", self.lower, "prompt() is forbidden")


class TestCarGameRestartsAndPersistence(unittest.TestCase):
    """QA criteria 5-6: Restart resets state; high score persists."""

    def setUp(self) -> None:
        self.assertTrue(INDEX_HTML.exists(), f"index.html not found at {INDEX_HTML}")
        self.raw = INDEX_HTML.read_text(encoding="utf-8")
        self.lower = self.raw.lower()

    def test_has_restart_logic(self) -> None:
        # Restart must clear obstacles, reset score, set state to playing
        self.assertTrue(
            re.search(r'(restart|reset|start\s*\()', self.lower),
            "No restart/reset logic found",
        )

    def test_has_window_blur_key_clear(self) -> None:
        # Spec: clear keys on window.blur so stuck keys don't run player off
        self.assertTrue(
            re.search(r'(blur|visibilitychange)', self.lower),
            "No window blur/visibility handler to clear keys",
        )

    def test_has_wasd_aliases(self) -> None:
        # Architect recommended WASD aliases (open question 3, proceeding on recommendation)
        self.assertTrue(
            re.search(r"([\"']a[\"']|[\"']d[\"']|key\s*===\s*['\"]a|wasd)", self.lower),
            "WASD aliases not found (Architect recommended including them)",
        )


if __name__ == "__main__":
    unittest.main()
