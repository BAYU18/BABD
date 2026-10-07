"""One place for progress messages (installs, setup, team runs).

Messages go to stderr, and to any listener (the dashboard streams them to the browser).
"""
import sys
import threading

_listeners = []
_lock = threading.Lock()


def add_listener(fn):
    with _lock:
        _listeners.append(fn)


def remove_listener(fn):
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


def log(msg, source="setup"):
    print(f"[{source}] {msg}", file=sys.stderr, flush=True)
    with _lock:
        listeners = list(_listeners)
    for fn in listeners:
        try:
            fn(source, msg)
        except Exception:  # a broken listener must never break the work being logged
            pass
