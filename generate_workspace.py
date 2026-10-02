#!/usr/bin/env python3
"""Generate the AI development team workspace illustration (workspace.svg).

All agent and project data comes from agents.json: edit the config there
(LLM connection, Telegram bot gateway, skills, tasks, statuses) and re-run.
"""
import json
import os
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))

W, H = 1920, 1460

BG = "#0d1628"
PANEL = "#15223a"
PANEL_2 = "#1b2a45"
STROKE = "#26385a"
TEXT = "#e8eef8"
MUTED = "#8597b4"
DIM = "#5a6c8a"

FONT = "Inter, 'Segoe UI', 'Helvetica Neue', 'Liberation Sans', Arial, sans-serif"

CEO = "#5b8cff"
GOOD = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"
TELEGRAM = "#2aabee"

STATUS_COLORS = {"working": GOOD, "waiting": WARN, "blocked": BAD, "idle": DIM}

out = []


def add(s):
    out.append(s)


def text(x, y, s, size=16, fill=TEXT, weight=400, anchor="start", ls=0, opacity=1):
    add(
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
        f'text-anchor="{anchor}" letter-spacing="{ls}" opacity="{opacity}">{escape(str(s))}</text>'
    )


def rect(x, y, w, h, fill, r=0, stroke=None, sw=1, opacity=1, extra=""):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{st} opacity="{opacity}" {extra}/>')


def pill_width(label, size=12):
    return len(label) * size * 0.68 + 30


def pill(x, y, label, color, w=None, size=12):
    w = w or pill_width(label, size)
    rect(x, y, w, 24, color, r=12, opacity=0.16)
    add(f'<circle cx="{x + 13}" cy="{y + 12}" r="4" fill="{color}"/>')
    text(x + 23, y + 16.5, label, size=size, fill=color, weight=700, ls=0.8)
    return w


def label(x, y, s, fill=MUTED, anchor="start"):
    text(x, y, s, size=11, fill=fill, weight=700, ls=2, anchor=anchor)


def check_item(x, y, name, state, color):
    """state: done | active | todo"""
    if state == "done":
        rect(x, y - 14, 18, 18, color, r=5)
        add(f'<path d="M{x + 4} {y - 5} l4 4 l7 -8" stroke="{BG}" stroke-width="2.4" fill="none" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
        text(x + 30, y, name, size=16, fill=MUTED)
    elif state == "active":
        rect(x + 1, y - 13, 16, 16, "none", r=5, stroke=color, sw=2)
        rect(x + 6, y - 8, 6, 6, color, r=2)
        text(x + 30, y, name, size=16, fill=TEXT, weight=600)
    else:
        rect(x + 1, y - 13, 16, 16, "none", r=5, stroke=DIM, sw=2)
        text(x + 30, y, name, size=16, fill=MUTED)


def robot_station(x, y, color):
    """Robot avatar at a small workstation. (x, y) = top-left of a ~230x110 box."""
    add(f'<g transform="translate({x} {y})">')
    add(f'<ellipse cx="115" cy="104" rx="105" ry="7" fill="{color}" opacity="0.10"/>')
    add(f'<line x1="58" y1="8" x2="58" y2="20" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
    add(f'<circle cx="58" cy="7" r="5" fill="{color}"/>')
    rect(32, 20, 52, 40, "#dfe7f3", r=12)
    rect(39, 29, 38, 20, BG, r=8)
    add(f'<circle cx="51" cy="39" r="4" fill="{color}"/><circle cx="65" cy="39" r="4" fill="{color}"/>')
    rect(27, 33, 6, 14, "#b9c5d8", r=3)
    rect(83, 33, 6, 14, "#b9c5d8", r=3)
    add(f'<path d="M34 98 v-24 a12 12 0 0 1 12 -12 h24 a12 12 0 0 1 12 12 v24 z" fill="{color}"/>')
    rect(50, 72, 16, 8, BG, r=3, opacity=0.35)
    add(f'<path d="M80 80 q14 2 26 4" stroke="{color}" stroke-width="7" stroke-linecap="round" fill="none"/>')
    rect(18, 92, 196, 8, "#2f4266", r=4)
    rect(122, 26, 88, 56, "#2a3c5e", r=7)
    rect(128, 32, 76, 44, BG, r=4)
    rect(135, 40, 34, 4, color, r=2)
    rect(135, 49, 54, 4, "#3a5078", r=2)
    rect(135, 58, 44, 4, "#3a5078", r=2)
    rect(135, 67, 24, 4, color, r=2, opacity=0.6)
    rect(160, 82, 12, 10, "#2a3c5e")
    rect(102, 86, 36, 6, "#3a5078", r=3)
    add("</g>")


# --- config widgets ------------------------------------------------------------

def gear_icon(cx, cy, color):
    add(f'<circle cx="{cx}" cy="{cy}" r="6.5" fill="none" stroke="{color}" stroke-width="4" '
        f'stroke-dasharray="2.6 2.5"/>')
    add(f'<circle cx="{cx}" cy="{cy}" r="5" fill="{color}"/>')
    add(f'<circle cx="{cx}" cy="{cy}" r="2.2" fill="{PANEL}"/>')


def llm_icon(cx, cy, color):
    for d in (-4, 0, 4):
        add(f'<line x1="{cx + d}" y1="{cy - 10}" x2="{cx + d}" y2="{cy + 10}" stroke="{color}" stroke-width="1.6"/>')
        add(f'<line x1="{cx - 10}" y1="{cy + d}" x2="{cx + 10}" y2="{cy + d}" stroke="{color}" stroke-width="1.6"/>')
    rect(cx - 7, cy - 7, 14, 14, PANEL_2, r=3, stroke=color, sw=2)
    rect(cx - 3, cy - 3, 6, 6, color, r=1)


def telegram_icon(cx, cy, on=True):
    add(f'<circle cx="{cx}" cy="{cy}" r="10" fill="{TELEGRAM if on else DIM}"/>')
    add(f'<path d="M{cx - 5.5} {cy - 0.5} L{cx + 5.5} {cy - 5} L{cx + 3.5} {cy + 5.5} L{cx + 0.5} {cy + 2.5} '
        f'L{cx - 1.5} {cy + 4.5} L{cx - 1.5} {cy + 1.5} Z" fill="#ffffff"/>')


def config_row(x, y, w, kind, agent):
    """One config row (LLM connection or Telegram gateway). Height 44."""
    color = agent["color"]
    rect(x, y, w, 44, PANEL_2, r=10)
    if kind == "llm":
        llm = agent["llm"]
        llm_icon(x + 20, y + 22, color)
        text(x + 40, y + 18, f"LLM · {llm['provider'].upper()}", size=10, fill=MUTED, weight=700, ls=1.4)
        text(x + 40, y + 35, llm["label"], size=14, fill=TEXT, weight=700)
        on = bool(llm.get("model"))
    else:
        tg = agent["telegram"]
        on = tg.get("enabled", False)
        telegram_icon(x + 20, y + 22, on)
        text(x + 40, y + 18, "TELEGRAM GATEWAY", size=10, fill=MUTED, weight=700, ls=1.4)
        text(x + 40, y + 35, tg["bot_username"], size=14, fill=TEXT if on else MUTED, weight=700)
    dot = GOOD if on else DIM
    add(f'<circle cx="{x + w - 16}" cy="{y + 22}" r="5" fill="{dot}"/>')
    if on:
        add(f'<circle cx="{x + w - 16}" cy="{y + 22}" r="9" fill="{dot}" opacity="0.2"/>')


def chip_width(s):
    return len(s) * 7.0 + 22


def skill_chips(x, y, w, skills, color):
    """Wrapping skill chips + an "Add Skill" chip. Returns the bottom y."""
    cx, cy = x, y
    items = [(s, False) for s in skills] + [("+ Add Skill", True)]
    for s, is_add in items:
        cw = chip_width(s)
        if cx + cw > x + w and cx > x:
            cx, cy = x, cy + 32
        if is_add:
            rect(cx, cy, cw, 26, "none", r=13, stroke=MUTED, sw=1.4, extra='stroke-dasharray="4 3"')
            text(cx + cw / 2, cy + 17.5, s, size=12, fill=MUTED, weight=700, anchor="middle")
        else:
            rect(cx, cy, cw, 26, color, r=13, opacity=0.14)
            rect(cx, cy, cw, 26, "none", r=13, stroke=color, sw=1, opacity=0.55)
            text(cx + cw / 2, cy + 17.5, s, size=12, fill=color, weight=700, anchor="middle")
        cx += cw + 6
    return cy + 26


def config_header(x, y, w, color):
    label(x, y, "AGENT CONFIG")
    gear_icon(x + w - 8, y - 4, MUTED)


# --- cards -----------------------------------------------------------------------

def agent_card(x, y, w, h, num, agent):
    color = agent["color"]
    status = agent["status"].upper()
    rect(x, y, w, h, PANEL, r=18, stroke=STROKE)
    rect(x, y, w, 5, color, r=2)
    robot_station(x + (w - 230) / 2, y + 22, color)
    py = y + 152
    text(x + 24, py, f"{num} · {agent['name']}", size=14, fill=color, weight=700, ls=1.6)
    pill(x + w - 24 - pill_width(status), py - 17, status, STATUS_COLORS[agent["status"]])
    add(f'<line x1="{x + 24}" y1="{py + 14}" x2="{x + w - 24}" y2="{py + 14}" stroke="{STROKE}"/>')
    label(x + 24, py + 40, "MAIN TASK")
    for i, line in enumerate(agent["main_task"]):
        text(x + 24, py + 78 + i * 38, line, size=34, fill=TEXT, weight=800, ls=0.5)
    sy = py + 78 + len(agent["main_task"]) * 38 + 8
    label(x + 24, sy, "SUB-TASKS")
    for i, st in enumerate(agent["sub_tasks"]):
        check_item(x + 24, sy + 30 + i * 30, st["name"], st["state"], color)

    # config section
    cy = sy + 30 + 2 * 30 + 26
    iw = w - 40
    rect(x + 12, cy, w - 24, h - (cy - y) - 12, BG, r=14, opacity=0.55)
    config_header(x + 20, cy + 24, iw, color)
    config_row(x + 20, cy + 36, iw, "llm", agent)
    config_row(x + 20, cy + 86, iw, "telegram", agent)
    label(x + 20, cy + 152, "SKILLS")
    skill_chips(x + 20, cy + 162, iw, agent["skills"], color)


def lead_card(x, y, w, h, agent):
    color = agent["color"]
    status = agent["status"].upper()
    rect(x, y, w, h, PANEL, r=18, stroke=color, sw=1.5)
    rect(x, y, w, 5, color, r=2)
    robot_station(x + 18, y + 60, color)
    tx = x + 270
    text(tx, y + 44, f"01 · {agent['name']}", size=14, fill=color, weight=700, ls=1.6)
    pill(tx, y + 58, status, STATUS_COLORS[agent["status"]])
    label(tx, y + 116, "MAIN TASK")
    for i, line in enumerate(agent["main_task"]):
        text(tx, y + 154 + i * 38, line, size=34, fill=TEXT, weight=800, ls=0.5)
    sx = tx + 210
    label(sx, y + 116, "SUB-TASKS")
    for i, st in enumerate(agent["sub_tasks"]):
        check_item(sx, y + 146 + i * 30, st["name"], st["state"], color)

    # config strip along the bottom
    cy = y + 226
    rect(x + 12, cy, w - 24, h - 238, BG, r=14, opacity=0.55)
    config_header(x + 24, cy + 24, w - 48, color)
    config_row(x + 24, cy + 36, 200, "llm", agent)
    config_row(x + 236, cy + 36, 200, "telegram", agent)
    label(x + 452, cy + 52, "SKILLS")
    skill_chips(x + 452, cy + 60, w - 452 - 24, agent["skills"], color)


def human_avatar(cx, cy, r=34):
    add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{CEO}" opacity="0.18"/>')
    add(f'<circle cx="{cx}" cy="{cy - 8}" r="{r * 0.36}" fill="#f1d3b8"/>')
    add(f'<path d="M{cx - r * 0.36} {cy - 14} a{r * 0.36} {r * 0.36} 0 0 1 {r * 0.72} 0 '
        f'q-{r * 0.36} -6 -{r * 0.72} 0z" fill="#2a2f45"/>')
    add(f'<path d="M{cx - r * 0.62} {cy + r * 0.78} a{r * 0.62} {r * 0.55} 0 0 1 {r * 1.24} 0 z" fill="{CEO}"/>')
    add(f'<path d="M{cx - 4} {cy + 10} l4 10 l4 -10 z" fill="#e8eef8"/>')


def dashboard(x, y, w, h, project, agents):
    # spread the 7 sections evenly over the panel height
    content = 200 + 96 + 76 + 72 + 92 + 92 + 56 + 64 + 112
    G = (h - 24 - content) / 8
    rect(x - 6, y - 6, w + 12, h + 12, CEO, r=24, opacity=0.08)
    rect(x, y, w, h, "#172747", r=20, stroke=CEO, sw=2)
    human_avatar(x + 58, y + 58)
    text(x + 108, y + 48, "HUMAN CEO", size=13, fill=CEO, weight=700, ls=2)
    text(x + 108, y + 78, "CEO DASHBOARD", size=28, fill=TEXT, weight=800, ls=0.5)
    add(f'<line x1="{x + 24}" y1="{y + 112}" x2="{x + w - 24}" y2="{y + 112}" stroke="{STROKE}"/>')

    # project + status
    label(x + 24, y + 146, "PROJECT")
    text(x + 24, y + 172, project["name"], size=20, fill=TEXT, weight=700)
    label(x + w - 24, y + 146, "STATUS", anchor="end")
    pill(x + w - 24 - 82, y + 156, project["status"], GOOD, w=82)

    # progress
    py = y + 200 + G
    rect(x + 24, py, w - 48, 96, PANEL_2, r=14)
    label(x + 44, py + 30, "PROJECT PROGRESS")
    text(x + w - 44, py + 46, f"{project['progress']}%", size=44, fill=TEXT, weight=800, anchor="end")
    bw = w - 88
    rect(x + 44, py + 64, bw, 12, "#2a3c5e", r=6)
    rect(x + 44, py + 64, bw * project["progress"] / 100, 12, CEO, r=6)

    # goal / active task
    ty = py + 96 + G
    tw = (w - 60) / 2
    for i, (lbl, value, color) in enumerate([("CURRENT GOAL", project["current_goal"], CEO),
                                             ("ACTIVE TASK", project["active_task"], WARN)]):
        tx = x + 24 + i * (tw + 12)
        rect(tx, ty, tw, 76, PANEL_2, r=14)
        rect(tx, ty + 16, 4, 44, color, r=2)
        label(tx + 18, ty + 30, lbl)
        words = value.split(" ")
        if len(value) > 16 and len(words) > 1:
            text(tx + 18, ty + 52, words[0], size=17, fill=TEXT, weight=700)
            text(tx + 18, ty + 70, " ".join(words[1:]), size=17, fill=TEXT, weight=700)
        else:
            text(tx + 18, ty + 58, value, size=17, fill=TEXT, weight=700)

    # agent status (computed from agents.json)
    ay = ty + 76 + G
    working = sum(a["status"] == "working" for a in agents)
    waiting = len(agents) - working
    rect(x + 24, ay, w - 48, 72, PANEL_2, r=14)
    label(x + 44, ay + 28, "AGENT STATUS")
    text(x + 44, ay + 56, f"{working} Working / {waiting} Waiting", size=17, fill=TEXT, weight=700)
    for i, a in enumerate(agents):
        cx = x + w - 44 - (len(agents) - 1 - i) * 30
        if a["status"] == "working":
            add(f'<circle cx="{cx}" cy="{ay + 38}" r="10" fill="{a["color"]}"/>')
        else:
            add(f'<circle cx="{cx}" cy="{ay + 38}" r="9" fill="none" stroke="{a["color"]}" stroke-width="2.5" '
                f'stroke-dasharray="4 3"/>')

    # team setup (computed from agents.json)
    sy = ay + 72 + G
    n = len(agents)
    llm_ok = sum(bool(a["llm"].get("model")) for a in agents)
    tg_ok = sum(bool(a["telegram"].get("enabled")) for a in agents)
    skills = sum(len(a["skills"]) for a in agents)
    rect(x + 24, sy, w - 48, 92, PANEL_2, r=14)
    label(x + 44, sy + 28, "TEAM SETUP")
    cw = (w - 88) / 3
    for i, (val, sub, color, icon) in enumerate([(f"{llm_ok}/{n}", "LLM connected", GOOD if llm_ok == n else WARN, "llm"),
                                                 (f"{tg_ok}/{n}", "Telegram bots", GOOD if tg_ok == n else WARN, "tg"),
                                                 (str(skills), "Skills added", CEO, None)]):
        cx = x + 44 + i * cw
        text(cx, sy + 64, val, size=22, fill=TEXT, weight=800)
        text(cx, sy + 82, sub, size=12, fill=MUTED, weight=600)
        vw = len(val) * 13.5 + 8
        add(f'<circle cx="{cx + vw + 4}" cy="{sy + 57}" r="4" fill="{color}"/>')

    # attention row
    ky = sy + 92 + G
    for i, (lbl, value, color) in enumerate([("APPROVAL NEEDED", project["approval_needed"], WARN),
                                             ("BLOCKERS", project["blockers"], BAD)]):
        tx = x + 24 + i * (tw + 12)
        rect(tx, ky, tw, 92, color, r=14, opacity=0.12)
        rect(tx, ky, tw, 92, "none", r=14, stroke=color, sw=1.5, opacity=0.7)
        label(tx + 18, ky + 30, lbl, fill=color)
        text(tx + 18, ky + 76, value, size=40, fill=TEXT, weight=800)
        text(tx + tw - 18, ky + 74, "Review" if i == 0 else "Resolve", size=14, fill=color,
             weight=700, anchor="end")

    # recent result
    ry = ky + 92 + G
    rect(x + 24, ry, w - 48, 56, PANEL_2, r=14)
    add(f'<circle cx="{x + 52}" cy="{ry + 28}" r="12" fill="{GOOD}"/>')
    add(f'<path d="M{x + 46} {ry + 28} l4 4 l7 -8" stroke="{BG}" stroke-width="2.4" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round"/>')
    label(x + 76, ry + 24, "RECENT RESULT")
    text(x + 76, ry + 44, project["recent_result"], size=16, fill=TEXT, weight=700)

    # next action
    ny = ry + 56 + G
    rect(x + 24, ny, w - 48, 64, CEO, r=14)
    label(x + 44, ny + 25, "NEXT ACTION", fill="#dbe6ff")
    text(x + 44, ny + 49, project["next_action"], size=19, fill="#ffffff", weight=800)
    add(f'<path d="M{x + w - 64} {ny + 32} h22 m-8 -8 l8 8 l-8 8" stroke="#ffffff" stroke-width="3" '
        f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')

    # CEO's own Telegram gateway (approvals / blockers / reports)
    tg = project["ceo_telegram"]
    on = tg.get("enabled", False)
    gy = ny + 64 + G
    rect(x + 24, gy, w - 48, 112, PANEL_2, r=14)
    telegram_icon(x + 54, gy + 34, on)
    label(x + 76, gy + 28, "CEO TELEGRAM")
    text(x + 76, gy + 48, tg["bot_username"], size=16, fill=TEXT if on else MUTED, weight=700)
    pill(x + w - 44 - pill_width("CONNECTED" if on else "OFF"), gy + 22, "CONNECTED" if on else "OFF",
         GOOD if on else DIM)
    cx = x + 44
    for n in tg["notify"]:
        cw = chip_width(n)
        rect(cx, gy + 70, cw, 26, TELEGRAM, r=13, opacity=0.14)
        text(cx + cw / 2, gy + 87.5, n, size=12, fill=TELEGRAM, weight=700, anchor="middle")
        cx += cw + 6


def arrow_head(x, y, color, direction="down"):
    d = {"down": f"M{x - 6} {y - 8} L{x} {y} L{x + 6} {y - 8}",
         "right": f"M{x - 8} {y - 6} L{x} {y} L{x - 8} {y + 6}",
         "left": f"M{x + 8} {y - 6} L{x} {y} L{x + 8} {y + 6}"}[direction]
    add(f'<path d="{d}" stroke="{color}" stroke-width="2.5" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round"/>')


def build(cfg):
    project, agents, workflow = cfg["project"], cfg["agents"], cfg["workflow"]
    by_id = {a["id"]: a for a in agents}
    lead, specialists = agents[0], agents[1:]
    LEAD = lead["color"]

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{FONT}">')
    add('<defs><pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">'
        f'<circle cx="1" cy="1" r="1" fill="#22324f"/></pattern></defs>')
    rect(0, 0, W, H, BG)
    rect(0, 0, W, H, "url(#grid)")

    # header
    rect(40, 38, 40, 40, LEAD, r=10)
    rect(50, 50, 20, 16, BG, r=4)
    add(f'<circle cx="56" cy="58" r="2.5" fill="{LEAD}"/><circle cx="64" cy="58" r="2.5" fill="{LEAD}"/>')
    text(96, 66, "AI SOFTWARE DEVELOPMENT WORKSPACE", size=26, fill=TEXT, weight=800, ls=1)
    text(720, 66, f"1 Human CEO  ·  {len(agents)} AI Agents", size=16, fill=MUTED, weight=500)

    # geometry
    agents_x0, card_w, gap = 40, 297, 24
    agents_y, agents_h = 560, 680
    lead_x, lead_y, lead_w, lead_h = 330, 110, 680, 360
    dash_x, dash_y, dash_w, dash_h = 1360, 30, 520, agents_y + agents_h - 30

    # --- connections ---------------------------------------------------
    line_c = "#3a5078"
    ly1, ly2 = lead_y + 120, lead_y + 180
    mid = (dash_x + lead_x + lead_w) / 2
    add(f'<line x1="{dash_x - 4}" y1="{ly1}" x2="{lead_x + lead_w + 6}" y2="{ly1}" stroke="{CEO}" '
        f'stroke-width="2.5" stroke-dasharray="2 7" stroke-linecap="round"/>')
    arrow_head(lead_x + lead_w + 6, ly1, CEO, "left")
    label(mid, ly1 - 12, "SUPERVISES", fill=CEO, anchor="middle")
    add(f'<line x1="{lead_x + lead_w + 6}" y1="{ly2}" x2="{dash_x - 8}" y2="{ly2}" stroke="{LEAD}" '
        f'stroke-width="2.5" stroke-dasharray="2 7" stroke-linecap="round"/>')
    arrow_head(dash_x - 6, ly2, LEAD, "right")
    label(mid, ly2 + 24, "REPORTS", fill=LEAD, anchor="middle")

    lead_cx = lead_x + lead_w / 2
    bus_y = lead_y + lead_h + 44
    centers = [agents_x0 + i * (card_w + gap) + card_w / 2 for i in range(len(specialists))]
    add(f'<line x1="{lead_cx}" y1="{lead_y + lead_h}" x2="{lead_cx}" y2="{bus_y}" stroke="{LEAD}" '
        f'stroke-width="2.5"/>')
    add(f'<line x1="{centers[0]}" y1="{bus_y}" x2="{centers[-1]}" y2="{bus_y}" stroke="{line_c}" '
        f'stroke-width="2.5" stroke-linecap="round"/>')
    add(f'<circle cx="{lead_cx}" cy="{bus_y}" r="5" fill="{LEAD}"/>')
    for c, a in zip(centers, specialists):
        add(f'<line x1="{c}" y1="{bus_y}" x2="{c}" y2="{agents_y - 6}" stroke="{line_c}" stroke-width="2.5"/>')
        arrow_head(c, agents_y - 4, a["color"])
    label(lead_cx + 14, bus_y - 14, "ASSIGNS & COORDINATES")

    # --- cards -----------------------------------------------------------
    lead_card(lead_x, lead_y, lead_w, lead_h, lead)
    for i, a in enumerate(specialists):
        agent_card(agents_x0 + i * (card_w + gap), agents_y, card_w, agents_h, f"{i + 2:02d}", a)

    for i in range(len(specialists) - 1):
        gx = agents_x0 + (i + 1) * (card_w + gap) - gap
        cy = agents_y + 76
        rect(gx - 4, cy - 14, gap + 8, 28, BG, r=14)
        add(f'<line x1="{gx + 3}" y1="{cy}" x2="{gx + gap - 4}" y2="{cy}" stroke="{MUTED}" stroke-width="2.5"/>')
        arrow_head(gx + gap - 2, cy, MUTED, "right")

    dashboard(dash_x, dash_y, dash_w, dash_h, project, agents)

    # --- workflow ----------------------------------------------------------
    wy = agents_y + agents_h + 30
    rect(40, wy, W - 80, 160, PANEL, r=18, stroke=STROKE)
    label(64, wy + 36, "DEVELOPMENT WORKFLOW")
    n = len(workflow)
    sgap = 62
    sw_ = (W - 128 - (n - 1) * sgap) / n
    sy = wy + 56
    for i, step in enumerate(workflow):
        owner = by_id[step["owner"]]
        col, state = owner["color"], step["state"]
        owner_name = owner.get("short_name", owner["name"])
        sx = 64 + i * (sw_ + sgap)
        if state == "active":
            rect(sx - 4, sy - 4, sw_ + 8, 84, col, r=18, opacity=0.18)
            rect(sx, sy, sw_, 76, PANEL_2, r=14, stroke=col, sw=2)
        else:
            rect(sx, sy, sw_, 76, PANEL_2, r=14, opacity=1 if state == "done" else 0.6)
        add(f'<circle cx="{sx + 38}" cy="{sy + 38}" r="18" fill="{col}" opacity="{1 if state != "todo" else 0.35}"/>')
        text(sx + 38, sy + 44, str(i + 1), size=16, fill=BG, weight=800, anchor="middle")
        text(sx + 70, sy + 36, step["step"], size=24, fill=TEXT if state != "todo" else MUTED, weight=800, ls=1)
        sub = {"done": "Done", "active": "In progress", "todo": "Up next"}[state]
        text(sx + 70, sy + 58, f"{owner_name} · {sub}", size=13, fill=col if state == "active" else MUTED,
             weight=600)
        if i < n - 1:
            ax = sx + sw_ + 12
            add(f'<line x1="{ax}" y1="{sy + 38}" x2="{ax + sgap - 26}" y2="{sy + 38}" stroke="{MUTED}" '
                f'stroke-width="2.5" stroke-linecap="round"/>')
            arrow_head(ax + sgap - 24, sy + 38, MUTED, "right")

    add("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    with open(os.path.join(HERE, "agents.json")) as f:
        cfg = json.load(f)
    with open(os.path.join(HERE, "workspace.svg"), "w") as f:
        f.write(build(cfg))
    print("wrote workspace.svg")
