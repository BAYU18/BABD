#!/usr/bin/env python3
"""Generate the AI development team workspace illustration (workspace.svg)."""

W, H = 1920, 1200

BG = "#0d1628"
PANEL = "#15223a"
PANEL_2 = "#1b2a45"
STROKE = "#26385a"
TEXT = "#e8eef8"
MUTED = "#8597b4"
DIM = "#5a6c8a"

FONT = "Inter, 'Segoe UI', 'Helvetica Neue', 'Liberation Sans', Arial, sans-serif"

LEAD = "#9b8cff"
ARCH = "#38bdf8"
DEV = "#34d399"
QA = "#fbbf24"
OPS = "#f472b6"
CEO = "#5b8cff"
GOOD = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"

out = []


def add(s):
    out.append(s)


def text(x, y, s, size=16, fill=TEXT, weight=400, anchor="start", ls=0, opacity=1):
    add(
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
        f'text-anchor="{anchor}" letter-spacing="{ls}" opacity="{opacity}">{s}</text>'
    )


def rect(x, y, w, h, fill, r=0, stroke=None, sw=1, opacity=1, extra=""):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{st} opacity="{opacity}" {extra}/>')


def pill(x, y, label, color, w=None, size=12):
    w = w or (len(label) * size * 0.68 + 30)
    rect(x, y, w, 24, color, r=12, opacity=0.16)
    add(f'<circle cx="{x + 13}" cy="{y + 12}" r="4" fill="{color}"/>')
    text(x + 23, y + 16.5, label, size=size, fill=color, weight=700, ls=0.8)
    return w


def check_item(x, y, label, state, color):
    """state: done | active | todo"""
    if state == "done":
        rect(x, y - 14, 18, 18, color, r=5)
        add(f'<path d="M{x + 4} {y - 5} l4 4 l7 -8" stroke="{BG}" stroke-width="2.4" fill="none" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')
        text(x + 30, y, label, size=16, fill=MUTED)
    elif state == "active":
        rect(x + 1, y - 13, 16, 16, "none", r=5, stroke=color, sw=2)
        rect(x + 6, y - 8, 6, 6, color, r=2)
        text(x + 30, y, label, size=16, fill=TEXT, weight=600)
    else:
        rect(x + 1, y - 13, 16, 16, "none", r=5, stroke=DIM, sw=2)
        text(x + 30, y, label, size=16, fill=MUTED)


def robot_station(x, y, color, scale=1.0):
    """Robot avatar at a small workstation. (x, y) = top-left of a ~230x110 box."""
    add(f'<g transform="translate({x} {y}) scale({scale})">')
    # floor glow
    add(f'<ellipse cx="115" cy="104" rx="105" ry="7" fill="{color}" opacity="0.10"/>')
    # robot
    add(f'<line x1="58" y1="8" x2="58" y2="20" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
    add(f'<circle cx="58" cy="7" r="5" fill="{color}"/>')
    rect(32, 20, 52, 40, "#dfe7f3", r=12)
    rect(39, 29, 38, 20, BG, r=8)
    add(f'<circle cx="51" cy="39" r="4" fill="{color}"/><circle cx="65" cy="39" r="4" fill="{color}"/>')
    rect(27, 33, 6, 14, "#b9c5d8", r=3)
    rect(83, 33, 6, 14, "#b9c5d8", r=3)
    add(f'<path d="M34 98 v-24 a12 12 0 0 1 12 -12 h24 a12 12 0 0 1 12 12 v24 z" fill="{color}"/>')
    rect(50, 72, 16, 8, BG, r=3, opacity=0.35)
    # arm reaching to keyboard
    add(f'<path d="M80 80 q14 2 26 4" stroke="{color}" stroke-width="7" stroke-linecap="round" fill="none"/>')
    # desk
    rect(18, 92, 196, 8, "#2f4266", r=4)
    # monitor
    rect(122, 26, 88, 56, "#2a3c5e", r=7)
    rect(128, 32, 76, 44, BG, r=4)
    rect(135, 40, 34, 4, color, r=2)
    rect(135, 49, 54, 4, "#3a5078", r=2)
    rect(135, 58, 44, 4, "#3a5078", r=2)
    rect(135, 67, 24, 4, color, r=2, opacity=0.6)
    rect(160, 82, 12, 10, "#2a3c5e")
    rect(102, 86, 36, 6, "#3a5078", r=3)
    add("</g>")


def agent_card(x, y, w, h, num, name, color, main, subs, status, status_color):
    rect(x, y, w, h, PANEL, r=18, stroke=STROKE)
    rect(x, y, w, 5, color, r=2)
    robot_station(x + (w - 230) / 2, y + 22, color)
    py = y + 152
    text(x + 24, py, f"{num} · {name}", size=14, fill=color, weight=700, ls=1.6)
    pill(x + w - 24 - (len(status) * 12 * 0.68 + 30), py - 17, status, status_color)
    add(f'<line x1="{x + 24}" y1="{py + 14}" x2="{x + w - 24}" y2="{py + 14}" stroke="{STROKE}"/>')
    text(x + 24, py + 40, "MAIN TASK", size=11, fill=MUTED, weight=700, ls=2)
    for i, line in enumerate(main):
        text(x + 24, py + 78 + i * 38, line, size=34, fill=TEXT, weight=800, ls=0.5)
    sy = py + 78 + len(main) * 38 + 8
    text(x + 24, sy, "SUB-TASKS", size=11, fill=MUTED, weight=700, ls=2)
    for i, (label, state) in enumerate(subs):
        check_item(x + 24, sy + 30 + i * 30, label, state, color)


def lead_card(x, y, w, h):
    color = LEAD
    rect(x, y, w, h, PANEL, r=18, stroke=color, sw=1.5)
    rect(x, y, w, 5, color, r=2)
    robot_station(x + 18, y + 70, color, scale=1.0)
    tx = x + 270
    text(tx, y + 44, "01 · TEAM LEAD / ORCHESTRATOR", size=14, fill=color, weight=700, ls=1.6)
    pill(tx, y + 58, "WORKING", GOOD)
    text(tx, y + 116, "MAIN TASK", size=11, fill=MUTED, weight=700, ls=2)
    text(tx, y + 154, "MANAGE", size=34, fill=TEXT, weight=800, ls=0.5)
    text(tx, y + 192, "PROJECT", size=34, fill=TEXT, weight=800, ls=0.5)
    sx = tx + 210
    text(sx, y + 116, "SUB-TASKS", size=11, fill=MUTED, weight=700, ls=2)
    for i, (label, state) in enumerate([("Plan Work", "done"), ("Assign Agents", "done"),
                                        ("Coordinate Results", "active")]):
        check_item(sx, y + 146 + i * 30, label, state, color)
    text(x + 24, y + h - 22, "Coordinates the four specialist agents", size=13, fill=MUTED)


def human_avatar(cx, cy, r=34):
    add(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{CEO}" opacity="0.18"/>')
    add(f'<circle cx="{cx}" cy="{cy - 8}" r="{r * 0.36}" fill="#f1d3b8"/>')
    add(f'<path d="M{cx - r * 0.36} {cy - 14} a{r * 0.36} {r * 0.36} 0 0 1 {r * 0.72} 0 '
        f'q-{r * 0.36} -6 -{r * 0.72} 0z" fill="#2a2f45"/>')
    add(f'<path d="M{cx - r * 0.62} {cy + r * 0.78} a{r * 0.62} {r * 0.55} 0 0 1 {r * 1.24} 0 z" fill="{CEO}"/>')
    add(f'<path d="M{cx - 4} {cy + 10} l4 10 l4 -10 z" fill="#e8eef8"/>')


def dashboard(x, y, w, h):
    rect(x - 6, y - 6, w + 12, h + 12, CEO, r=24, opacity=0.08)
    rect(x, y, w, h, "#172747", r=20, stroke=CEO, sw=2)
    # header
    human_avatar(x + 58, y + 58)
    text(x + 108, y + 48, "HUMAN CEO", size=13, fill=CEO, weight=700, ls=2)
    text(x + 108, y + 78, "CEO DASHBOARD", size=28, fill=TEXT, weight=800, ls=0.5)
    add(f'<line x1="{x + 24}" y1="{y + 112}" x2="{x + w - 24}" y2="{y + 112}" stroke="{STROKE}"/>')

    # project + status
    text(x + 24, y + 146, "PROJECT", size=11, fill=MUTED, weight=700, ls=2)
    text(x + 24, y + 172, "Software Project", size=20, fill=TEXT, weight=700)
    text(x + w - 24, y + 146, "STATUS", size=11, fill=MUTED, weight=700, ls=2, anchor="end")
    pill(x + w - 24 - 82, y + 156, "ACTIVE", GOOD, w=82)

    # progress
    G = 24
    py = y + 200 + 6
    rect(x + 24, py, w - 48, 96, PANEL_2, r=14)
    text(x + 44, py + 30, "PROJECT PROGRESS", size=11, fill=MUTED, weight=700, ls=2)
    text(x + w - 44, py + 46, "72%", size=44, fill=TEXT, weight=800, anchor="end")
    bw = w - 88
    rect(x + 44, py + 64, bw, 12, "#2a3c5e", r=6)
    rect(x + 44, py + 64, bw * 0.72, 12, CEO, r=6)

    # goal / active task
    ty = py + 112 + G
    tw = (w - 60) / 2
    for i, (label, value, color) in enumerate([("CURRENT GOAL", "Complete Authentication", CEO),
                                               ("ACTIVE TASK", "QA Testing", QA)]):
        tx = x + 24 + i * (tw + 12)
        rect(tx, ty, tw, 76, PANEL_2, r=14)
        rect(tx, ty + 16, 4, 44, color, r=2)
        text(tx + 18, ty + 30, label, size=11, fill=MUTED, weight=700, ls=2)
        words = value.split(" ")
        if len(value) > 16:
            text(tx + 18, ty + 52, words[0], size=17, fill=TEXT, weight=700)
            text(tx + 18, ty + 70, " ".join(words[1:]), size=17, fill=TEXT, weight=700)
        else:
            text(tx + 18, ty + 58, value, size=17, fill=TEXT, weight=700)

    # agent status
    ay = ty + 92 + G
    rect(x + 24, ay, w - 48, 72, PANEL_2, r=14)
    text(x + 44, ay + 28, "AGENT STATUS", size=11, fill=MUTED, weight=700, ls=2)
    text(x + 44, ay + 56, "4 Working / 1 Waiting", size=17, fill=TEXT, weight=700)
    for i, (c, s) in enumerate([(LEAD, 1), (ARCH, 1), (DEV, 1), (QA, 1), (OPS, 0)]):
        cx = x + w - 168 + i * 30
        if s:
            add(f'<circle cx="{cx}" cy="{ay + 38}" r="10" fill="{c}"/>')
        else:
            add(f'<circle cx="{cx}" cy="{ay + 38}" r="9" fill="none" stroke="{c}" stroke-width="2.5" '
                f'stroke-dasharray="4 3"/>')

    # attention row
    ky = ay + 88 + G
    for i, (label, value, color) in enumerate([("APPROVAL NEEDED", "2", WARN), ("BLOCKERS", "1", BAD)]):
        tx = x + 24 + i * (tw + 12)
        rect(tx, ky, tw, 92, color, r=14, opacity=0.12)
        rect(tx, ky, tw, 92, "none", r=14, stroke=color, sw=1.5, opacity=0.7)
        text(tx + 18, ky + 30, label, size=11, fill=color, weight=700, ls=2)
        text(tx + 18, ky + 76, value, size=40, fill=TEXT, weight=800)
        text(tx + tw - 18, ky + 74, "Review" if i == 0 else "Resolve", size=14, fill=color,
             weight=700, anchor="end")

    # recent result
    ry = ky + 108 + G
    rect(x + 24, ry, w - 48, 56, PANEL_2, r=14)
    add(f'<circle cx="{x + 52}" cy="{ry + 28}" r="12" fill="{GOOD}"/>')
    add(f'<path d="M{x + 46} {ry + 28} l4 4 l7 -8" stroke="{BG}" stroke-width="2.4" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round"/>')
    text(x + 76, ry + 24, "RECENT RESULT", size=11, fill=MUTED, weight=700, ls=2)
    text(x + 76, ry + 44, "API Completed", size=16, fill=TEXT, weight=700)

    # next action
    ny = ry + 70 + G
    rect(x + 24, ny, w - 48, 64, CEO, r=14)
    text(x + 44, ny + 25, "NEXT ACTION", size=11, fill="#dbe6ff", weight=700, ls=2)
    text(x + 44, ny + 49, "Run Integration Tests", size=19, fill="#ffffff", weight=800)
    add(f'<path d="M{x + w - 64} {ny + 32} h22 m-8 -8 l8 8 l-8 8" stroke="#ffffff" stroke-width="3" '
        f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def arrow_head(x, y, color, direction="down"):
    if direction == "down":
        add(f'<path d="M{x - 6} {y - 8} L{x} {y} L{x + 6} {y - 8}" stroke="{color}" stroke-width="2.5" '
            f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    elif direction == "right":
        add(f'<path d="M{x - 8} {y - 6} L{x} {y} L{x - 8} {y + 6}" stroke="{color}" stroke-width="2.5" '
            f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    elif direction == "left":
        add(f'<path d="M{x + 8} {y - 6} L{x} {y} L{x + 8} {y + 6}" stroke="{color}" stroke-width="2.5" '
            f'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def build():
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
    text(720, 66, "1 Human CEO  ·  5 AI Agents", size=16, fill=MUTED, weight=500)

    # geometry
    agents_x0, card_w, gap = 40, 297, 24
    agents_y, agents_h = 520, 420
    lead_x, lead_y, lead_w, lead_h = 330, 120, 680, 300
    dash_x, dash_y, dash_w, dash_h = 1360, 30, 520, 910

    # --- connections ---------------------------------------------------
    line_c = "#3a5078"
    # CEO dashboard <-> team lead
    ly1, ly2 = lead_y + 120, lead_y + 180
    add(f'<line x1="{dash_x - 4}" y1="{ly1}" x2="{lead_x + lead_w + 6}" y2="{ly1}" stroke="{CEO}" '
        f'stroke-width="2.5" stroke-dasharray="2 7" stroke-linecap="round"/>')
    arrow_head(lead_x + lead_w + 6, ly1, CEO, "left")
    text((dash_x + lead_x + lead_w) / 2, ly1 - 12, "SUPERVISES", size=11, fill=CEO, weight=700, ls=2,
         anchor="middle")
    add(f'<line x1="{lead_x + lead_w + 6}" y1="{ly2}" x2="{dash_x - 8}" y2="{ly2}" stroke="{LEAD}" '
        f'stroke-width="2.5" stroke-dasharray="2 7" stroke-linecap="round"/>')
    arrow_head(dash_x - 6, ly2, LEAD, "right")
    text((dash_x + lead_x + lead_w) / 2, ly2 + 24, "REPORTS", size=11, fill=LEAD, weight=700, ls=2,
         anchor="middle")

    # team lead -> four specialists (bus)
    lead_cx = lead_x + lead_w / 2
    bus_y = 466
    centers = [agents_x0 + i * (card_w + gap) + card_w / 2 for i in range(4)]
    add(f'<line x1="{lead_cx}" y1="{lead_y + lead_h}" x2="{lead_cx}" y2="{bus_y}" stroke="{LEAD}" '
        f'stroke-width="2.5"/>')
    add(f'<line x1="{centers[0]}" y1="{bus_y}" x2="{centers[-1]}" y2="{bus_y}" stroke="{line_c}" '
        f'stroke-width="2.5" stroke-linecap="round"/>')
    add(f'<circle cx="{lead_cx}" cy="{bus_y}" r="5" fill="{LEAD}"/>')
    for c, col in zip(centers, [ARCH, DEV, QA, OPS]):
        add(f'<line x1="{c}" y1="{bus_y}" x2="{c}" y2="{agents_y - 6}" stroke="{line_c}" stroke-width="2.5"/>')
        arrow_head(c, agents_y - 4, col)
    text(lead_cx + 14, bus_y - 14, "ASSIGNS &amp; COORDINATES", size=11, fill=MUTED, weight=700, ls=2)

    # --- cards -----------------------------------------------------------
    lead_card(lead_x, lead_y, lead_w, lead_h)
    agents = [
        ("02", "ARCHITECT", ARCH, ["DESIGN", "SYSTEM"],
         [("Analyze Requirements", "done"), ("Design Architecture", "done"), ("Research Solutions", "active")],
         "WORKING", GOOD),
        ("03", "DEVELOPER", DEV, ["BUILD", "SOFTWARE"],
         [("Write Code", "done"), ("Refactor Code", "active"), ("Review Code", "todo")],
         "WORKING", GOOD),
        ("04", "QA / TESTER", QA, ["VALIDATE", "SOFTWARE"],
         [("Create Tests", "done"), ("Find Bugs", "active"), ("Verify Fixes", "todo")],
         "WORKING", GOOD),
        ("05", "DEVOPS", OPS, ["DEPLOY &amp;", "OPERATE"],
         [("Build", "done"), ("Deploy", "todo"), ("Monitor", "todo")],
         "WAITING", WARN),
    ]
    for i, a in enumerate(agents):
        agent_card(agents_x0 + i * (card_w + gap), agents_y, card_w, agents_h, *a)

    # hand-off arrows between neighbouring specialists
    for i in range(3):
        gx = agents_x0 + (i + 1) * (card_w + gap) - gap
        cy = agents_y + 76
        rect(gx - 4, cy - 14, gap + 8, 28, BG, r=14)
        add(f'<line x1="{gx + 3}" y1="{cy}" x2="{gx + gap - 4}" y2="{cy}" stroke="{MUTED}" stroke-width="2.5"/>')
        arrow_head(gx + gap - 2, cy, MUTED, "right")

    dashboard(dash_x, dash_y, dash_w, dash_h)

    # --- workflow ----------------------------------------------------------
    wy = 982
    rect(40, wy, W - 80, 178, PANEL, r=18, stroke=STROKE)
    text(64, wy + 36, "DEVELOPMENT WORKFLOW", size=13, fill=MUTED, weight=700, ls=2.4)
    steps = [("PLAN", "Team Lead", LEAD, "done"), ("DESIGN", "Architect", ARCH, "done"),
             ("CODE", "Developer", DEV, "done"), ("TEST", "QA / Tester", QA, "active"),
             ("DEPLOY", "DevOps", OPS, "todo"), ("MONITOR", "DevOps", OPS, "todo")]
    sw_, sgap = 246, 62
    sx0 = 64
    sy = wy + 62
    for i, (label, owner, col, state) in enumerate(steps):
        sx = sx0 + i * (sw_ + sgap)
        if state == "active":
            rect(sx - 4, sy - 4, sw_ + 8, 92, col, r=18, opacity=0.18)
            rect(sx, sy, sw_, 84, PANEL_2, r=14, stroke=col, sw=2)
        else:
            rect(sx, sy, sw_, 84, PANEL_2, r=14, opacity=1 if state == "done" else 0.6)
        add(f'<circle cx="{sx + 38}" cy="{sy + 42}" r="18" fill="{col}" opacity="{1 if state != "todo" else 0.35}"/>')
        text(sx + 38, sy + 48, str(i + 1), size=16, fill=BG, weight=800, anchor="middle")
        text(sx + 70, sy + 40, label, size=24, fill=TEXT if state != "todo" else MUTED, weight=800, ls=1)
        sub = {"done": "Done", "active": "In progress", "todo": "Up next"}[state]
        text(sx + 70, sy + 62, f"{owner} · {sub}", size=13, fill=col if state == "active" else MUTED,
             weight=600)
        if i < len(steps) - 1:
            ax = sx + sw_ + 12
            add(f'<line x1="{ax}" y1="{sy + 42}" x2="{ax + sgap - 26}" y2="{sy + 42}" stroke="{MUTED}" '
                f'stroke-width="2.5" stroke-linecap="round"/>')
            arrow_head(ax + sgap - 24, sy + 42, MUTED, "right")

    add("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    with open("workspace.svg", "w") as f:
        f.write(build())
    print("wrote workspace.svg")
