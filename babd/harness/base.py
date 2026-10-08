"""Harness interface: how an agent turns (system prompt, conversation) into a reply.

Modelled on Paperclip's adapters (packages/adapters/* in paperclipai/paperclip): every harness gets
the agent's own `llm` block and projects it into whatever that harness needs (SDK client,
config file, environment variables), so each agent keeps its custom LLM whatever harness it uses.
"""
import os
import signal
import subprocess
import threading
import time
import weakref

from ..config import ROOT
from ..llm import LLMError

DEFAULT_TIMEOUT_SEC = 1800
DEFAULT_WORKSPACE = os.path.join(ROOT, "workspace")

# Every harness child process currently running, so a Stop can kill all of them even when a
# step is between two calls (otherwise the program becomes an orphan and keeps holding its slot).
_RUNNING_PROCS = weakref.WeakSet()
_RUNNING_LOCK = threading.Lock()


def _register_proc(proc):
    with _RUNNING_LOCK:
        _RUNNING_PROCS.add(proc)


def _unregister_proc(proc):
    with _RUNNING_LOCK:
        _RUNNING_PROCS.discard(proc)


def kill_all_running():
    """Kill every harness child process still running (called when a task is stopped)."""
    with _RUNNING_LOCK:
        procs = list(_RUNNING_PROCS)
    for p in procs:
        _kill(p)


def kill_by_run(run_id):
    """Kill every process whose environment carries BABD_RUN_ID == run_id.

    Second line of defence: a program spawned between two registry updates (or by a harness that
    bypassed run_process) is still found here, so a stopped task never leaves an orphan running.
    """
    if not run_id or os.name != "posix":
        return 0
    killed = 0
    me = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == me:
            continue
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read()
        except OSError:
            continue
        if f"BABD_RUN_ID={run_id}".encode() in env.split(b"\x00") or \
                b"\x00BABD_RUN_ID=" + run_id.encode() + b"\x00" in env + b"\x00":
            try:
                os.killpg(pid, signal.SIGTERM)
            except OSError:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    continue
            killed += 1
    return killed


class HarnessError(LLMError):
    pass


class Harness:
    type = ""
    has_tools = False  # can it read/write files and run commands itself (else BABD writes its file blocks)
    label = ""
    install_spec = None   # tools.InstallSpec of the program this harness runs, if any
    defaults = {}         # options written to agents.json when this harness is selected

    def __init__(self, agent_cfg):
        self.extra_env = {}   # set by the team (e.g. GBRAIN_HOME + the gbrain command); PATH is prepended
        self.skill_packs = {}  # {pack: this agent's skills}, installed natively where the harness supports it
        self.agent_cfg = agent_cfg
        self._usage = threading.local()
        self.agent_id = agent_cfg["id"]
        self.llm = agent_cfg["llm"]
        self.cfg = harness_config(agent_cfg)
        from .. import permissions
        self.permissions = permissions.profile_of(agent_cfg)   # plan / ask / workspace / full
        self.sandbox = permissions.sandbox_of(agent_cfg)       # none / bwrap / docker

    def complete(self, system, messages, max_tokens=None, effort=None):
        raise NotImplementedError

    # Token counts of this thread's last complete(): {"input", "output", "cost"?}. Harnesses that know
    # them (direct API, Claude Code) report them; the agent estimates the rest from the text.
    def take_usage(self):
        u = getattr(self._usage, "last", None)
        self._usage.last = None
        return u

    def record_usage(self, usage):
        self._usage.last = usage

    def describe(self):
        """Short text for the card / CLI, e.g. 'hermes chat - terminal,file'."""
        return self.label

    def setup(self):
        """Install what this harness needs and write its configuration. Safe to run repeatedly.
        Returns a one-line summary. Called by `babd setup` / `babd use`, and before the first run."""
        parts = []
        if self.install_spec:
            path = self.command_path()
            parts.append(os.path.relpath(path, ROOT) if path.startswith(ROOT + os.sep) else path)
        parts += self.configure() or []
        return " · ".join(parts) or "ready"

    def configure(self):
        """Write harness config files for this agent. Returns notes for the summary."""
        return []

    def command_path(self):
        from .tools import ensure_command  # tools imports this module
        return ensure_command(self.label, self.cfg, self.install_spec)

    # -- helpers for CLI harnesses ------------------------------------------------------------

    @property
    def timeout(self):
        return float(self.cfg.get("timeout_sec", DEFAULT_TIMEOUT_SEC)) or None

    @property
    def cwd(self):
        cwd = self.cfg.get("cwd") or DEFAULT_WORKSPACE
        if not os.path.isabs(cwd):
            cwd = os.path.join(ROOT, cwd)
        os.makedirs(cwd, exist_ok=True)
        return cwd

    def private_dirs(self):
        """Folders this harness writes besides the task's worktree (its own home, config)."""
        return []

    def sandboxed(self, argv):
        """argv inside the bubblewrap sandbox (see permissions.py)."""
        from .. import permissions
        permissions.bwrap_check()
        mine = [d for d in self.private_dirs() if d]
        for d in mine:
            os.makedirs(d, exist_ok=True)
        others = []  # the other agents' homes stay hidden
        for base in {os.path.dirname(d) for d in mine}:
            if os.path.isdir(base):
                others += [os.path.join(base, n) for n in os.listdir(base)
                           if os.path.join(base, n) not in mine and os.path.isdir(os.path.join(base, n))]
        writable = mine + [os.path.expanduser(w) for w in self.cfg.get("writable") or []]
        gbrain_home = (self.extra_env or {}).get("GBRAIN_HOME")
        if gbrain_home:
            writable.append(gbrain_home)
        return permissions.bwrap_argv(argv, self.cwd, writable, hide_dirs=others)

    def child_env(self, env_overrides):
        """Environment for the harness's program: ours + team extras + harness `env` + LLM routing."""
        from .tools import extra_path  # tools imports this module
        extra = dict(self.extra_env)
        extra_paths = [p for p in extra.pop("PATH", "").split(os.pathsep) if p]
        from ..config import scrub_env
        # BABD's secrets never reach the agent's program; the LLM routing below adds back only this
        # agent's own key. `pass_env` (harness option) lists variables the agent may still see.
        base = scrub_env(os.environ, keep=self.cfg.get("pass_env") or ())
        env = apply_env(base, extra, self.cfg.get("env") or {}, env_overrides)
        env["PATH"] = os.pathsep.join(extra_paths + extra_path() + [env.get("PATH", "")])
        return env

    def run_process(self, argv, env_overrides, stdin_text=None):
        """Run the harness's program and return its stdout. When the task is stopped (cancel_event), the
        program and everything it started are killed at once instead of running to the end."""
        env = self.child_env(env_overrides)
        cancel = getattr(self, "cancel_event", None)
        if self.sandbox == "bwrap":
            argv = self.sandboxed(argv)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=self.cwd,
                                    start_new_session=os.name == "posix")
        except OSError as e:
            raise HarnessError(f"{self.label}: cannot start {argv[0]}: {e}") from e
        _register_proc(proc)
        # Watchdog: kill the process group the moment the task is stopped, even if the loop below is
        # blocked inside communicate(); without this a stopped step could leave an orphan program
        # running (it kept its agent slot, so the next task waited forever).
        if cancel is not None:
            def _watchdog():
                while proc.poll() is None:
                    if cancel.wait(0.3):
                        _kill(proc)
                        return
            threading.Thread(target=_watchdog, daemon=True, name="harness-watchdog").start()
        # Write stdin in a background thread. communicate() may only be called once with input=...,
        # so feeding stdin ourselves lets us poll for cancellation/timeout freely afterwards.
        if stdin_text is not None:
            def _feed():
                try:
                    proc.stdin.write(stdin_text)
                    proc.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass  # the program exited before reading all of stdin
            threading.Thread(target=_feed, daemon=True).start()
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    out, err = proc.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    if cancel is not None and cancel.is_set():
                        _kill(proc)
                        raise HarnessError(f"{self.label}: stopped (task cancelled)")
                    if time.monotonic() > deadline:
                        _kill(proc)
                        raise HarnessError(f"{self.label}: timed out after {self.timeout:.0f}s")
        finally:
            # the program is done (or killed): drop it from the registry, and if the task was
            # cancelled while we waited, make sure nothing of its process group survives.
            if cancel is not None and cancel.is_set():
                _kill(proc)
            _unregister_proc(proc)
        if proc.returncode != 0:
            # CLIs print errors on stdout or stderr; the first and last meaningful lines carry the story.
            lines = [ln.strip() for ln in ((out or "") + "\n" + (err or "")).splitlines()
                     if ln.strip() and not ln.strip().startswith("session_id:")]
            detail = " | ".join(dict.fromkeys(lines[:1] + lines[-1:])) or "no output"
            raise HarnessError(f"{self.label}: exit code {proc.returncode}: {detail[:500]}")
        return out

def _kill(proc):
    """Kill a harness program and its children (its own process group)."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            pass
    try:
        proc.communicate(timeout=5)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass


def apply_env(base, *layers):
    """Copy of `base` with each layer applied in order; a value of None removes the variable."""
    env = dict(base)
    for layer in layers:
        for k, v in layer.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = str(v)
    return env


def harness_config(agent_cfg):
    """The agent's harness block; a bare string is shorthand for {"type": <string>}."""
    h = agent_cfg.get("harness") or {"type": "direct"}
    return {"type": h} if isinstance(h, str) else dict(h)


def render_prompt(system, messages):
    """Flatten system prompt + conversation into one prompt for CLI harnesses that take a single query.

    Same shape Paperclip uses for Hermes: instructions first, a separator, then the task.
    """
    parts = [system.strip(), "---"]
    if len(messages) == 1:
        parts.append(messages[0]["content"])
    else:
        for m in messages:
            who = "User" if m["role"] == "user" else "You (earlier reply)"
            parts.append(f"## {who}\n{m['content']}")
    return "\n\n".join(parts)
