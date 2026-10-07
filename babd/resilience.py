"""Retries and fallback models: one flaky LLM call should not fail a whole task.

    project.retry = {"attempts": 3, "base_delay": 5, "max_delay": 60}
        a step that hits a temporary error (time-out, rate limit, 5xx, lost connection, an empty
        answer) is tried again up to `attempts` times, waiting base_delay, 2x, 4x ... (max max_delay)
    agents[].llm.fallback = {"model": "...", "base_url": "...", "api": "...", "api_key_env": "..."}
        when the agent's own model still fails, the step is tried on this model (fields left out are
        the agent's own)

Errors that another try cannot fix (wrong key, unknown model, a refusal) are not retried, but they
do go to the fallback model when there is one.
"""
import re
import threading
import time

TRANSIENT = re.compile(
    r"rate.?limit|timed? ?out|timeout|cannot reach|connection|temporar|overloaded|unavailable|"
    r"API error (?:408|409|425|429|5\d\d)|\b(?:502|503|504|529)\b|empty response|returned no choices|"
    r"reset by peer|broken pipe|exit code (?:-9|137|143)", re.I)
PERMANENT = re.compile(r"authentication failed|no API key|not found|declined|unknown llm|needs an Anthropic", re.I)
DEFAULTS = {"attempts": 3, "base_delay": 5.0, "max_delay": 60.0}


def settings(project_cfg):
    r = {**DEFAULTS, **((project_cfg or {}).get("retry") or {})}
    try:
        return {"attempts": max(1, min(10, int(r["attempts"]))), "base_delay": max(0.0, float(r["base_delay"])),
                "max_delay": max(0.0, float(r["max_delay"]))}
    except (TypeError, ValueError):
        return dict(DEFAULTS)


def is_transient(err):
    text = f"{type(err).__name__}: {err}"
    return bool(TRANSIENT.search(text)) and not PERMANENT.search(text)


class Listener(threading.local):
    """Per-thread hooks set by the run around one step: on_retry(info) and a cancel event."""
    on_retry = None
    cancelled = None


def call(fn, cfg, on_retry=None, cancelled=None, sleep=None):
    """fn() with retries on temporary errors. on_retry({"attempt", "of", "error", "wait"}) before each wait."""
    attempts = cfg["attempts"]
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            if attempt >= attempts or not is_transient(e):
                raise
            wait = min(cfg["max_delay"], cfg["base_delay"] * 2 ** (attempt - 1))
            if on_retry:
                on_retry({"attempt": attempt, "of": attempts, "error": str(e)[:300], "wait": wait})
            if cancelled is not None:
                if cancelled.wait(wait):
                    raise
            else:
                (sleep or time.sleep)(wait)
