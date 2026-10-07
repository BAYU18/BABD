"""Tests for index.html — encodes the Architect's QA acceptance criteria.

These tests verify behavior through the public seam: the file `index.html` as
parsed by a standard HTML5 parser. They assert exactly what the Architect's
spec requires, nothing about implementation details.

Run: python -m pytest test_index_html.py -v
  or: python -m unittest test_index_html
"""

import os
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
        self._in_h1 = False
        self.h1_texts: list[str] = []
        self.title_texts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self.tags.append(tag_lower)
        attr_dict = dict(attrs)
        self.attrs_by_tag.setdefault(tag_lower, []).append(attr_dict)
        if tag_lower == "h1":
            self._in_h1 = True
            self._current_text = []
        if tag_lower == "title":
            self._in_title = True
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "h1":
            self._in_h1 = False
            self.h1_texts.append("".join(self._current_text))
        if tag_lower == "title":
            self._in_title = False
            self.title_texts.append("".join(self._current_text))

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._in_h1 or self._in_title:
            self._current_text.append(data)

    def handle_decl(self, decl: str) -> None:
        # Capture <!DOCTYPE html> — stored as a pseudo-tag for checking
        self.tags.append(f"!{decl.strip().lower()}")


class TestIndexHtmlWellFormed(unittest.TestCase):
    """The file must parse as well-formed HTML5 and have the required structure."""

    def setUp(self) -> None:
        self.assertTrue(INDEX_HTML.exists(), f"index.html not found at {INDEX_HTML}")
        self.raw = INDEX_HTML.read_text(encoding="utf-8")
        self.parser = _HTMLStructureExtractor()
        self.parser.feed(self.raw)

    def test_file_exists_and_is_non_empty(self) -> None:
        self.assertTrue(self.raw.strip(), "index.html is empty")

    def test_begins_with_doctype_html(self) -> None:
        # The very first tag-like construct must be <!DOCTYPE html>
        doctype_tags = [t for t in self.parser.tags if t.startswith("!doctype")]
        self.assertTrue(
            len(doctype_tags) >= 1,
            "No <!DOCTYPE html> declaration found",
        )
        self.assertIn(
            "doctype html",
            doctype_tags[0],
            f"Expected '!doctype html', got '{doctype_tags[0]}'",
        )

    def test_has_html_root_element(self) -> None:
        self.assertIn("html", self.parser.tags, "No <html> root element found")

    def test_has_head_element(self) -> None:
        self.assertIn("head", self.parser.tags, "No <head> element found")

    def test_has_body_element(self) -> None:
        self.assertIn("body", self.parser.tags, "No <body> element found")

    def test_head_contains_title_hello_world(self) -> None:
        self.assertTrue(
            len(self.parser.title_texts) >= 1,
            "No <title> element found",
        )
        self.assertEqual(
            self.parser.title_texts[0].strip(),
            "Hello World",
            f"Expected <title>Hello World</title>, got '{self.parser.title_texts[0]}'",
        )

    def test_head_contains_utf8_charset_meta(self) -> None:
        meta_attrs_list = self.parser.attrs_by_tag.get("meta", [])
        found_charset = any(
            (charset := attrs.get("charset")) is not None
            and charset.upper() == "UTF-8"
            for attrs in meta_attrs_list
        )
        self.assertTrue(
            found_charset,
            f"No <meta charset='UTF-8'> found in <head>; metas: {meta_attrs_list}",
        )

    def test_body_contains_exactly_one_h1(self) -> None:
        h1_count = self.parser.tags.count("h1")
        self.assertEqual(
            h1_count,
            1,
            f"Expected exactly one <h1> in <body>, found {h1_count}",
        )

    def test_h1_text_content_is_hello_world(self) -> None:
        self.assertTrue(
            len(self.parser.h1_texts) >= 1,
            "No <h1> text content found",
        )
        self.assertEqual(
            self.parser.h1_texts[0].strip(),
            "Hello World",
            f"Expected <h1>Hello World</h1>, got '{self.parser.h1_texts[0]}'",
        )

    def test_no_external_resources(self) -> None:
        # No <link>, <script>, or <style> tags — no external CSS/JS/assets
        forbidden = {"link", "script", "style"}
        found_forbidden = forbidden.intersection(set(self.parser.tags))
        self.assertFalse(
            found_forbidden,
            f"Found forbidden external-resource tags: {found_forbidden}",
        )


if __name__ == "__main__":
    unittest.main()
