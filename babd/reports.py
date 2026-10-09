"""A run as a Markdown report: what was asked, what happened, what it cost, and every agent's work.

    GET /api/runs/<id>/report.md        (dashboard: "Export report")
    babd report <run id> [-o file.md]   (command line)
"""
import datetime
import json
import os


def _dt(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _dur(a, b):
    a, b = _dt(a), _dt(b)
    if not a or not b:
        return "—"
    sec = int((b - a).total_seconds())
    return f"{sec // 3600}h {sec // 60 % 60:02d}m" if sec >= 3600 else f"{sec // 60}m {sec % 60:02d}s"


def _tok(u):
    if not u or not (u.get("input") or u.get("output")):
        return "—"
    t = f"{'~' if u.get('estimated') else ''}{u.get('input', 0) + u.get('output', 0):,} tokens"
    return t + (f", ${u['cost']:.4f}{'+' if u.get('cost_unknown') else ''}" if u.get("cost") else "")


def load(run_dir):
    with open(os.path.join(run_dir, "state.json")) as f:
        state = json.load(f)
    messages = []
    mp = os.path.join(run_dir, "messages.jsonl")
    if os.path.exists(mp):
        with open(mp) as f:
            messages = [json.loads(line) for line in f if line.strip()]
    return state, messages


def markdown(state, messages, names=None):
    names = names or {}
    who = lambda i: names.get(i, "CEO" if i == "ceo" else i)  # noqa: E731
    rep = state.get("report") or {}
    ws = state.get("workspace") or {}
    res = ws.get("result") or {}
    ev = state.get("evidence") or {}
    appr = state.get("approval") or {}
    out = [f"# {state.get('goal', 'Tugas')}", "",
           f"Tugas `{state.get('id')}` · **{str(state.get('status', '')).upper()}** · mulai {state.get('started_at') or '—'}"
           f" · durasi {_dur(state.get('started_at'), state.get('finished_at'))}", ""]
    if state.get("error"):
        out += [f"> **Error:** {state['error']}", ""]
    rows = [("Verdict QA", f"{state.get('verdict') or '—'}"
             + (f" setelah {state.get('qa_rounds')} putaran perbaikan" if state.get("qa_rounds") else "")),
            ("Bukti", ("terverifikasi: " if ev.get("verified") else "tidak terverifikasi: ") + (ev.get("note") or "—") if ev else "—"),
            ("Persetujuan CEO", f"{appr.get('result', '—')}" + (f" ({appr['note']})" if appr.get("note") else "") if appr else "belum diminta"),
            ("Di-deploy", "ya" if state.get("deployed") else "tidak"),
            ("Penggunaan", _tok(state.get("usage")))]
    if ws.get("name"):
        rows.append(("Proyek", f"{ws['name']} · branch `{ws.get('branch', '—')}`"
                     + (f" · digabung ke `{ws.get('base')}` ({res.get('commit')})" if res.get("merged") else "")
                     + (f" · {res['note']}" if res.get("note") else "")))
    if state.get("documents"):
        rows.append(("Dokumen tugas", ", ".join(d.get("url") or d["name"] for d in state["documents"])))
    out += ["| | |", "| --- | --- |"] + [f"| {k} | {v} |" for k, v in rows] + [""]
    if rep.get("summary"):
        out += ["## Laporan ke CEO", "", rep["summary"], ""]
    if rep.get("blocker_list"):
        out += ["**Hambatan:**", ""] + [f"- {b}" for b in rep["blocker_list"]] + [""]
    steps = state.get("steps") or []
    if steps:
        out += ["## Langkah", "", "| # | Agen | Langkah | Status | Durasi | Token |", "| --- | --- | --- | --- | --- | --- |"]
        for st in steps:
            took = f"{st['seconds']} s" if st.get("seconds") is not None else "—"
            extra = (f" (↻{st['retries']})" if st.get("retries") else "") + (f" (fallback {st['fallback']})" if st.get("fallback") else "")
            out.append(f"| {st.get('n')} | {who(st.get('agent'))} | {st.get('kind')} | {st.get('status')}{extra} | {took} | {_tok(st.get('usage'))} |")
        out.append("")
    for t in state.get("tests") or []:
        out += [f"### Project tests, round {t.get('round')}: exit {t.get('exit')}", "", f"```\n$ {t.get('command')}\n{t.get('output', '')}\n```", ""]
    if messages:
        out += ["## Percakapan", ""]
        for m in messages:
            out += [f"### {who(m.get('from'))} → {who(m.get('to'))} · {m.get('kind')} · {m.get('at', '')}", "",
                    str(m.get("content") or "").strip(), ""]
    return "\n".join(out).rstrip() + "\n"
