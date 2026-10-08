"""Each agent's activity log: what it was asked, what it did, how long it took, what went wrong.

One JSON line per event in logs/agents/<agent id>.jsonl (next to runs/), written from the run's
events, so it covers dashboard, Telegram and command-line tasks alike:

    step      queued / started / finished / failed, with the task, the time and the tokens
    message   what the agent received from the Team Lead and what it sent back (content kept, cut)
    memory    GBrain read / write
    skills    skills applied or skipped
    retry     a temporary LLM error retried, or the fallback model
    files     files written for an agent without file tools
    package   a work package started / finished
    route     the Team Lead's decision who works on the task

GET /api/agents/<id>/log?limit=200&before=<seq>&q=<words>&type=<type>  (dashboard: Agent logs)
"""
import json
import os
import threading

from . import flow

MAX_DETAIL = 6000
KEEP_BYTES = 8_000_000  # a log file over this is cut to its newer half
_lock = threading.Lock()
_seq = {}


def log_dir():
    return os.path.join(os.path.dirname(flow.RUNS_DIR), "logs", "agents")


def path_of(agent_id):
    return os.path.join(log_dir(), f"{os.path.basename(agent_id)}.jsonl")


def _cut(text, n=MAX_DETAIL):
    text = str(text or "")
    return text if len(text) <= n else text[:n] + f"\n[… {len(text) - n} more characters]"


def _short(text, n=90):
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def entries_for(kind, data, names=None):
    """[(agent id, entry)] for one run event."""
    names = names or {}
    who = lambda i: names.get(i, "CEO" if i == "ceo" else i)  # noqa: E731
    d = data if isinstance(data, dict) else {}
    out = []
    if kind == "step" and d.get("agent"):
        status = d.get("status")
        took = f" in {d['seconds']} s" if d.get("seconds") is not None else ""
        u = d.get("usage") or {}
        tok = f" · {u.get('input', 0) + u.get('output', 0):,} tokens" if u.get("input") or u.get("output") else ""
        text = {"queued": f"waiting for a free slot: {d.get('task')}",
                "working": f"started {d.get('kind')}: {d.get('task')}",
                "done": f"finished {d.get('kind')}{took}{tok}",
                "failed": f"failed {d.get('kind')}{took}" + (f": {d['last_error']}" if d.get("last_error") else "")}.get(
                    status, f"{d.get('kind')}: {status}")
        out.append((d["agent"], {"type": "step", "status": status, "kind": d.get("kind"), "text": text,
                                 "seconds": d.get("seconds"), "step": d.get("n")}))
    elif kind == "message":
        content = d.get("content")
        size = f" ({len(str(content or '')):,} characters)"
        if d.get("to") not in (None, "ceo"):
            out.append((d["to"], {"type": "message", "dir": "in", "kind": d.get("kind"),
                                  "text": f"from {who(d.get('from'))}: {d.get('kind')}{size}", "detail": _cut(content)}))
        if d.get("from") not in (None, "ceo"):
            out.append((d["from"], {"type": "message", "dir": "out", "kind": d.get("kind"),
                                    "text": f"to {who(d.get('to'))}: {d.get('kind')}{size}", "detail": _cut(content)}))
    elif kind == "memory" and d.get("agent"):
        text = (f"read GBrain: {d.get('facts', 0)} fact(s), {d.get('pages', 0)} page(s)" if d.get("op") == "read"
                else f"wrote GBrain page {d.get('page')}")
        out.append((d["agent"], {"type": "memory", "text": text,
                                 "detail": "\n".join(str(x) for x in d.get("items") or []) or d.get("fact")}))
    elif kind == "skills" and d.get("agent"):
        miss = d.get("missing") or []
        out.append((d["agent"], {"type": "skills", "status": "failed" if miss else "done",
                                 "text": ("skipped skills: " + ", ".join(miss)) if miss else
                                 ("applied skills: " + ", ".join(d.get("skills") or []))}))
    elif kind == "retry" and d.get("agent"):
        text = (f"trying the fallback model {d['fallback']}" if d.get("fallback") else
                f"LLM error, retry {d.get('attempt')}/{d.get('of')} in {d.get('wait')} s")
        out.append((d["agent"], {"type": "retry", "status": "failed", "text": text, "detail": d.get("error")}))
    elif kind == "files" and d.get("agent"):
        out.append((d["agent"], {"type": "files", "text": f"wrote {len(d.get('paths') or [])} file(s)",
                                 "detail": "\n".join(d.get("paths") or [])}))
    elif kind == "package" and d.get("agent"):
        out.append((d["agent"], {"type": "package", "status": d.get("status"),
                                 "text": f"work package {d.get('id')} {d.get('title')}: {d.get('status')}"}))
    elif kind == "question" and d.get("agent"):
        out.append((d["agent"], {"type": "question", "status": "waiting", "text": f"asks the CEO: {d.get('question')}",
                                 "detail": " | ".join(d.get("options") or [])}))
    elif kind == "answered" and d.get("agent"):
        out.append((d["agent"], {"type": "question", "text": f"the CEO answered: {d.get('answer') or '(no answer)'}"}))
    elif kind == "route":
        target = d.get("agent") if d.get("route") == "direct" else None
        text = {"answer": "answers the CEO directly", "direct": f"gives the task straight to {who(target)}",
                "team": "team: " + ", ".join(who(a) for a in d.get("agents") or [])}.get(d.get("route"), d.get("route"))
        out.append(("lead", {"type": "route", "text": f"triage: {text}", "detail": d.get("reason")}))
    return out


def record(run_id, goal, kind, data, names=None, at=None):
    """Append the log entries of one run event. Never raises (logging must not break a task)."""
    try:
        items = entries_for(kind, data, names)
        if not items:
            return []
        os.makedirs(log_dir(), exist_ok=True)
        written = []
        with _lock:
            for agent_id, e in items:
                p = path_of(agent_id)
                if p not in _seq:
                    _seq[p] = _last_seq(p)
                _seq[p] += 1
                e = {"seq": _seq[p], "at": at or flow.now(), "agent": agent_id, "run": run_id,
                     "goal": _short(goal), **{k: v for k, v in e.items() if v not in (None, "")}}
                with open(p, "a") as f:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
                if os.path.getsize(p) > KEEP_BYTES:
                    _trim(p)
                written.append(e)
        return written
    except Exception:  # noqa: BLE001
        return []


def _last_seq(p):
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        return int(json.loads(lines[-1])["seq"]) if lines else 0
    except (OSError, ValueError, KeyError, IndexError):
        return 0


def _trim(p):
    with open(p) as f:
        lines = f.readlines()
    with open(p, "w") as f:
        f.writelines(lines[len(lines) // 2:])


def read(agent_id, limit=200, before=None, q="", type_=""):
    """Newest first: up to `limit` entries with seq < before, matching all words of q and the type."""
    p = path_of(agent_id)
    if not os.path.exists(p):
        return []
    words = [w.lower() for w in (q or "").split()]
    out = []
    with open(p) as f:
        lines = f.readlines()
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if before and e.get("seq", 0) >= before:
            continue
        if type_ and e.get("type") != type_:
            continue
        if words:
            hay = " ".join(str(e.get(k) or "") for k in ("text", "goal", "run", "detail", "kind")).lower()
            if not all(w in hay for w in words):
                continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


def summary(agent_ids):
    """{agent: {"entries", "last_at", "last_text"}} for the agent list."""
    out = {}
    for a in agent_ids:
        last = read(a, limit=1)
        out[a] = {"last_at": last[0]["at"] if last else None, "last_text": last[0]["text"] if last else None,
                  "seq": last[0]["seq"] if last else 0}
    return out
