"""Scheduled tasks: a goal that becomes a task on a schedule (agents.json "schedules").

    "schedules": [
      {"id": "disk-lpnotif", "goal": "cek disk dan service di server lpnotif", "cron": "0 7 * * *",
       "mode": "quick", "project": "", "auto_approve": false, "enabled": true}
    ]

`cron` is the usual five fields (minute hour day-of-month month day-of-week; `*`, `*/n`, `a-b`, `a,b`;
day-of-week 0-6 with 0 = Sunday, or mon..sun), in this machine's local time. Short forms:
"hourly", "daily 07:00", "weekly mon 07:00", "monthly 1 07:00". The dashboard checks every 30 seconds
and starts each due schedule once per matching minute (the last start is kept in runs/_schedules.json).
"""
import datetime
import json
import os
import re

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
DAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
MODES = ("auto", "quick", "full")


class ScheduleError(Exception):
    pass


def _field(text, lo, hi, days=False):
    out = set()
    for part in text.split(","):
        part = part.strip().lower()
        if days:
            for name, n in DAYS.items():
                part = part.replace(name, str(n))
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            if not s.isdigit() or int(s) < 1:
                raise ScheduleError(f"bad step in {text!r}")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise ScheduleError(f"bad range in {text!r}")
            a, b = int(a), int(b)
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ScheduleError(f"bad value {part!r}")
        if days and b == 7:  # 7 is Sunday too
            out.add(0)
            if a == 7:
                continue
            b = 6
        if a < lo or b > hi or a > b:
            raise ScheduleError(f"{text!r} is outside {lo}-{hi}")
        out.update(range(a, b + 1, step))
    return out


def expand(text):
    """A short form ("daily 07:00", ...) as a five-field cron expression."""
    t = " ".join(str(text or "").lower().split())
    m = re.fullmatch(r"hourly(?: :?(\d{1,2}))?", t)
    if m:
        return f"{int(m.group(1) or 0)} * * * *"
    m = re.fullmatch(r"daily (\d{1,2}):(\d{2})", t)
    if m:
        return f"{int(m.group(2))} {int(m.group(1))} * * *"
    m = re.fullmatch(r"weekly ([a-z]{3}(?:,[a-z]{3})*) (\d{1,2}):(\d{2})", t)
    if m:
        return f"{int(m.group(3))} {int(m.group(2))} * * {m.group(1)}"
    m = re.fullmatch(r"monthly (\d{1,2}) (\d{1,2}):(\d{2})", t)
    if m:
        return f"{int(m.group(3))} {int(m.group(2))} {int(m.group(1))} * *"
    return t.removeprefix("cron ").strip()


def parse(cron):
    """[minutes, hours, days, months, weekdays] sets, or ScheduleError."""
    parts = expand(cron).split()
    if len(parts) != 5:
        raise ScheduleError(f"{cron!r}: use five fields (minute hour day month weekday) or e.g. 'daily 07:00'")
    return [_field(p, lo, hi, days=(i == 4)) for i, (p, (lo, hi)) in enumerate(zip(parts, FIELDS))]


def matches(cron, when):
    mi, ho, da, mo, wd = parse(cron)
    weekday = (when.weekday() + 1) % 7  # Python: Monday = 0; cron: Sunday = 0
    parts = expand(cron).split()
    if parts[2] != "*" and parts[4] != "*":  # both restricted: either one matches (as cron does)
        day_ok = when.day in da or weekday in wd
    else:
        day_ok = when.day in da and weekday in wd
    return when.minute in mi and when.hour in ho and when.month in mo and day_ok


def next_run(cron, after=None):
    """The next minute (after `after`, default now) the schedule fires, or None within a year."""
    parse(cron)
    t = (after or datetime.datetime.now()).replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if matches(cron, t):
            return t
        t += datetime.timedelta(minutes=1)
    return None


def normalize(s, agent_project_ids=None):
    goal = " ".join(str(s.get("goal") or "").split())
    if not goal:
        raise ScheduleError("a schedule needs a goal")
    sid = str(s.get("id") or "").strip().lower() or re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")[:40]
    if not ID_RE.match(sid):
        raise ScheduleError(f"schedule id {sid!r}: use lowercase letters, digits, '.', '_' or '-'")
    cron = expand(s.get("cron") or "")
    parse(cron)
    mode = s.get("mode") or "quick"
    if mode not in MODES:
        raise ScheduleError(f"schedule {sid}: mode must be one of {', '.join(MODES)}")
    return {"id": sid, "goal": goal[:2000], "cron": cron, "mode": mode, "project": str(s.get("project") or ""),
            "auto_approve": bool(s.get("auto_approve")), "enabled": s.get("enabled", True) is not False}


def schedules(cfg):
    return [normalize(s) for s in cfg.get("schedules") or []]


def describe(cron):
    """A short human text for a cron expression."""
    parts = cron.split()
    if len(parts) == 5 and parts[2:] == ["*", "*", "*"] and parts[0].isdigit() and parts[1].isdigit():
        return f"every day at {int(parts[1]):02d}:{int(parts[0]):02d}"
    if len(parts) == 5 and parts[1:] == ["*", "*", "*", "*"] and parts[0].isdigit():
        return f"every hour at :{int(parts[0]):02d}"
    if len(parts) == 5 and parts[2:4] == ["*", "*"] and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[4]} at {int(parts[1]):02d}:{int(parts[0]):02d}"
    return cron


class Book:
    """When each schedule last started a task (runs/_schedules.json)."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self, data):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)


def due(cfg, book, now=None):
    """The schedules to start now (each once per matching minute); marks them in the book."""
    now = (now or datetime.datetime.now()).replace(second=0, microsecond=0)
    stamp = now.isoformat(timespec="minutes")
    data = book.load()
    out = []
    for s in schedules(cfg):
        if s["enabled"] and matches(s["cron"], now) and data.get(s["id"], {}).get("fired") != stamp:
            data.setdefault(s["id"], {})["fired"] = stamp
            out.append(s)
    if out:
        book.save(data)
    return out
