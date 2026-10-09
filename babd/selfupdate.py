"""BABD updating itself: the code that lets the team change its own code.

Two ways, both safe by design (never a silent overwrite of the running installation):

  self-update   pull the upstream repository (origin) into this installation, run the
                project's tests, and only then move the installation to the new commit.
                The old commit is kept on the marker file, so `babd self-update --rollback`
                brings the team back.

  self-project  a project whose repository IS BABD (agents.json "projects", id
                "babd-self"): the agents edit BABD's code in an isolated git worktree
                under workspace/worktrees/, QA runs the tests there, and the change
                reaches the installation only through the CEO approval + merge gate.

The installation itself never runs from the worktree: agents work on a copy, the CEO
approves, and only then does the change land on the installation's branch.
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

from .config import ROOT

MARKER_DIR = os.path.join(ROOT, ".babd", "selfupdate")
BACKUP_DIR = os.path.join(MARKER_DIR, "backups")
SELF_PROJECT_ID = "babd-self"
DEFAULT_TEST_COMMAND = "python -m pytest -q"
UPSTREAM_REMOTE = "origin"
DEFAULT_UPSTREAM_BRANCH = "main"
# Files that must never be touched by an automatic pull (they hold local state/secrets).
KEPT_PATHS = (".env", "agents.json", "workspace", ".babd", "logs", "runs",
              "workspace.svg")


class SelfUpdateError(Exception):
    pass


def _run(argv, cwd=None, env=None, timeout=1800):
    """Run a command and return (returncode, stdout+stderr)."""
    cwd = cwd or ROOT
    e = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if env:
        e.update(env)
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=e, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return 1, f"{type(ex).__name__}: {ex}"
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def git(args, cwd=None, check=True, timeout=300):
    code, out = _run(["git", *args], cwd=cwd or ROOT, timeout=timeout)
    if check and code != 0:
        raise SelfUpdateError(f"git {' '.join(args[:2])} failed: {out[:400]}")
    return out


def is_installation(path=ROOT):
    """True when `path` looks like a BABD installation (has babd/ and .git/)."""
    p = os.path.realpath(path)
    return os.path.isdir(os.path.join(p, "babd")) and os.path.isdir(os.path.join(p, ".git"))


def current_commit():
    return git(["rev-parse", "HEAD"], check=False).strip() or None


def current_branch():
    return git(["rev-parse", "--abbrev-ref", "HEAD"], check=False).strip() or None


def remote_url(remote=UPSTREAM_REMOTE):
    return git(["remote", "get-url", remote], check=False).strip() or None


def dirty_paths():
    """Tracked files changed in the working tree (untracked ignored)."""
    out = git(["status", "--porcelain", "--untracked-files=no"], check=False)
    return [ln[2:].strip().strip(chr(34)) for ln in out.splitlines() if ln.strip()]


def _default_branch(remote=UPSTREAM_REMOTE):
    """The upstream branch: origin/HEAD if set, else current local branch, else main."""
    out = git(["symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD"], check=False).strip()
    if out.startswith(f"{remote}/"):
        return out[len(remote) + 1:]
    cur = current_branch()
    if cur and cur != "HEAD":
        return cur
    return DEFAULT_UPSTREAM_BRANCH


def upstream_commit(remote=UPSTREAM_REMOTE, branch=None):
    branch = branch or _default_branch(remote)
    out = git(["rev-parse", "--verify", "-q", f"refs/remotes/{remote}/{branch}"], check=False)
    return out.strip() or None


def fetch(remote=UPSTREAM_REMOTE, timeout=600):
    return git(["fetch", "--prune", remote], timeout=timeout, check=False)


def behind_ahead(remote=UPSTREAM_REMOTE, branch=None):
    """(behind, ahead) of local HEAD vs the upstream branch. (0, 0) when unknown."""
    branch = branch or _default_branch(remote)
    out = git(["rev-list", "--left-right", "--count", f"HEAD...{remote}/{branch}"], check=False)
    parts = out.split()
    if len(parts) != 2:
        return 0, 0
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0
    return behind, ahead


def _stash_if_dirty(keep=KEPT_PATHS):
    """Set local tracked changes aside (except the kept paths) so a pull can move HEAD."""
    changed = dirty_paths()
    to_stash = [p for p in changed if not any(p == k or p.startswith(k + "/") for k in keep)]
    if not to_stash:
        return None
    msg = f"babd-selfupdate-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    code, out = _run(["git", "stash", "push", "-u", "-m", msg, "--", *to_stash])
    if code != 0:
        return None
    ref = git(["rev-parse", "stash@{0}"], check=False).strip()
    return ref or None


def _backup_installation(max_keep=5):
    """Copy the code tree (not workspace/secrets) to .babd/selfupdate/backups/<stamp>."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = os.path.join(BACKUP_DIR, stamp)
    os.makedirs(dest, exist_ok=True)
    src = os.path.join(ROOT, "babd")
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(dest, "babd"), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    for name in ("agents.json", "generate_workspace.py", "README.md"):
        s = os.path.join(ROOT, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, name))
    try:
        old = sorted(d for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, d)))
        for d in old[:-max_keep]:
            shutil.rmtree(os.path.join(BACKUP_DIR, d), ignore_errors=True)
    except OSError:
        pass
    return dest


def test_command():
    """The command that verifies an update: project.self_test_command, else pytest if present."""
    try:
        from .config import load_config
        project = (load_config().get("project") or {})
        cmd = (project.get("self_test_command") or "").strip()
        if cmd:
            return cmd
    except Exception:
        pass
    if shutil.which("pytest") or os.path.isdir(os.path.join(ROOT, "tests")):
        return DEFAULT_TEST_COMMAND
    return ""


def run_tests(cwd=None, timeout=1800):
    cmd = test_command()
    if not cmd:
        return True, "(no test command configured; skipped)"
    code, out = _run(["bash", "-lc", cmd], cwd=cwd, timeout=timeout)
    tail = "\n".join(out.splitlines()[-40:])
    return code == 0, tail


def status(remote=UPSTREAM_REMOTE):
    fetch(remote, timeout=120)
    behind, ahead = behind_ahead(remote)
    return {
        "installation": ROOT,
        "branch": current_branch(),
        "commit": current_commit(),
        "remote": remote_url(remote),
        "dirty": dirty_paths(),
        "behind": behind,
        "ahead": ahead,
        "upstream": upstream_commit(remote),
        "test_command": test_command(),
    }


def update(remote=UPSTREAM_REMOTE, branch=None, do_test=True, do_backup=True, keep=KEPT_PATHS):
    """Pull upstream into the installation and verify. Returns a report dict.

    Steps: fetch -> stash local edits -> fast-forward-only merge -> run tests. On a failing
    test the merge is undone back to the previous HEAD (the team keeps running).
    """
    report = {"ok": False, "steps": [], "before": current_commit(), "after": None}

    def step(name, ok, detail=""):
        report["steps"].append({"step": name, "ok": ok, "detail": detail})
        return ok

    if not is_installation():
        raise SelfUpdateError(f"{ROOT} is not a BABD installation (needs babd/ and .git/)")
    branch = branch or _default_branch(remote)
    before = current_commit()
    step("fetch", True, fetch(remote))

    target = f"{remote}/{branch}"
    behind, ahead = behind_ahead(remote, branch)
    if behind == 0:
        step("up-to-date", True, f"already at {target} ({before[:10] if before else '?'})")
        report.update(ok=True, after=before, updated=False)
        return report
    report["behind"] = behind

    if do_backup:
        dest = _backup_installation()
        step("backup", True, dest)

    stash = _stash_if_dirty(keep)
    if stash:
        step("stash", True, f"local edits set aside ({stash[:10]})")

    code, out = _run(["git", "merge", "--ff-only", target])
    if code != 0:
        if stash:
            _run(["git", "stash", "pop"])
        step("merge", False, out[:400])
        report["error"] = "fast-forward merge failed (the installation has its own commits or diverged)"
        return report
    step("merge", True, f"{before[:10]} -> {current_commit()[:10]}")

    if do_test:
        ok, detail = run_tests()
        step("tests", ok, detail)
        if not ok:
            _run(["git", "reset", "--hard", before or "HEAD"])
            if stash:
                _run(["git", "stash", "pop"])
            report["error"] = "tests failed; rolled back to the previous commit"
            report["after"] = current_commit()
            return report
    if stash:
        code, out = _run(["git", "stash", "pop"])
        step("restore", code == 0, out[:200] if code else "")

    report.update(ok=True, after=current_commit(), updated=True)
    _write_marker(report)
    return report


def rollback():
    """Undo the last self-update: back to the commit recorded before it."""
    marker = _read_marker()
    if not marker or not marker.get("before"):
        raise SelfUpdateError("no recorded self-update to roll back")
    before = marker["before"]
    code, out = _run(["git", "reset", "--hard", before])
    if code != 0:
        raise SelfUpdateError(f"rollback failed: {out[:400]}")
    return {"ok": True, "after": current_commit(), "restored": before}


def _marker_path():
    os.makedirs(MARKER_DIR, exist_ok=True)
    return os.path.join(MARKER_DIR, "last.json")


def _write_marker(report):
    try:
        with open(_marker_path(), "w") as f:
            json.dump({"before": report.get("before"), "after": report.get("after"),
                       "at": datetime.now(timezone.utc).isoformat()}, f, indent=2)
    except OSError:
        pass


def _read_marker():
    try:
        with open(_marker_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def format_report(report):
    lines = []
    for s in report.get("steps", []):
        first = (s["detail"] or "").splitlines()
        lines.append("  %s %-12s %s" % ("OK " if s["ok"] else "FAIL", s["step"], first[0] if first else ""))
    return "\n".join(lines)
