"""Task templates: Markdown starting points for a task document (templates/tasks/<id>.md).

Each file may start with front matter (title, description). Add your own files there, or save one
from the dashboard. A filled-in template is sent as the task's document.
"""
import os
import re

from .config import ROOT

TEMPLATES_DIR = os.path.join(ROOT, "templates", "tasks")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class TemplateError(Exception):
    pass


def _parse(text):
    meta = {}
    m = re.match(r"\A---\n(.*?)\n---\n?", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip("'\"")
        text = text[m.end():]
    return meta, text.lstrip("\n")


def list_templates():
    out = []
    if os.path.isdir(TEMPLATES_DIR):
        for name in sorted(os.listdir(TEMPLATES_DIR)):
            if name.endswith(".md"):
                with open(os.path.join(TEMPLATES_DIR, name), encoding="utf-8") as f:
                    meta, body = _parse(f.read())
                tid = name[:-3]
                out.append({"id": tid, "title": meta.get("title") or tid, "description": meta.get("description", ""),
                            "body": body})
    return out


def get(tid):
    for t in list_templates():
        if t["id"] == tid:
            return t
    raise TemplateError(f"no template {tid!r}")


def save(tid, title, body, description=""):
    tid = (tid or "").strip().lower()
    if not ID_RE.match(tid):
        raise TemplateError("template id: lowercase letters, digits, '-' or '_' (max 48)")
    if not (body or "").strip():
        raise TemplateError("the template is empty")
    if len(body) > 100_000:
        raise TemplateError("the template is too long")
    clean = lambda s: re.sub(r"[\r\n]+", " ", s or "").strip()  # noqa: E731
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    with open(os.path.join(TEMPLATES_DIR, f"{tid}.md"), "w", encoding="utf-8") as f:
        f.write(f"---\ntitle: {clean(title) or tid}\ndescription: {clean(description)}\n---\n\n{body.strip()}\n")
    return get(tid)
