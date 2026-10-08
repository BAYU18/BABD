"""Projects: where the agents' work goes, kept apart from the BABD installation itself.

A project is a folder (or a git repository cloned into one) listed in agents.json:

    "projects": [
      {"id": "shop", "name": "Web shop", "repo": "https://github.com/acme/shop.git", "branch": "main",
       "merge": "on_approval", "push": false},
      {"id": "car-game", "name": "Car game"}            # a local folder: workspace/projects/car-game
    ]

Every task runs in its own git worktree of the project, on a branch `babd/<run id>`
(workspace/worktrees/<project>/<run id>), so tasks running at the same time never touch each other's
files and the project's main checkout stays clean. When the task ends, BABD commits what the agents
changed on that branch and merges it into the project's branch (`merge`: "on_approval" = QA passed and
the deploy was approved, "on_pass" = QA passed, "never" = leave the branch for review), then pushes
when `push` is on and the project has a remote.
"""
import os
import re
import shutil
import subprocess
import threading
import time

from .config import ROOT

PROJECTS_DIR = os.path.join(ROOT, "workspace", "projects")
WORKTREES_DIR = os.path.join(ROOT, "workspace", "worktrees")
DEFAULT_ID = "default"
MERGE_POLICIES = ("on_approval", "on_pass", "never", "pr")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
BRANCH_RE = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)(?!.*@\{)[A-Za-z0-9._/-]{1,200}(?<![./])$")
# Where a project may be cloned from: https / http / ssh / git URLs, scp-style git@host:path, or a
# local repository path. Never an option (a "repo" like --upload-pack=... runs a command) and never
# git's ext:: transport.
REPO_RE = re.compile(r"^(https?://|ssh://|git://|file://|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:|/|~)[^\s]*$")
_locks = {}
_locks_lock = threading.Lock()


class ProjectError(Exception):
    pass


def _lock(project_dir):
    with _locks_lock:
        return _locks.setdefault(project_dir, threading.Lock())


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48]
    return s or "project"


def projects(cfg):
    """The configured projects with defaults filled in; there is always a "default" project."""
    out = []
    for p in cfg.get("projects") or []:
        out.append(normalize(p))
    if not any(p["id"] == DEFAULT_ID for p in out):
        out.insert(0, normalize({"id": DEFAULT_ID, "name": "Default project"}))
    return out


def normalize(p):
    pid = p.get("id") or slug(p.get("name"))
    if not ID_RE.match(pid):
        raise ProjectError(f"project id {pid!r}: use lowercase letters, digits, '.', '_' or '-'")
    path = p.get("path") or os.path.join(PROJECTS_DIR, pid)
    if not os.path.isabs(path):
        path = os.path.join(ROOT, path)
    repo = str(p.get("repo") or "").strip()
    if repo and (repo.startswith("-") or not REPO_RE.match(repo) or "::" in repo.split("/")[0]):
        raise ProjectError(f"project {pid}: repo must be a git URL (https://, ssh://, git@host:path) or a local path")
    branch = str(p.get("branch") or "").strip()
    if branch and not BRANCH_RE.match(branch):
        raise ProjectError(f"project {pid}: {branch!r} is not a valid branch name")
    gh_repo = str(p.get("github_repo") or "").strip()
    if gh_repo and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", gh_repo):
        raise ProjectError(f"project {pid}: github_repo must look like owner/repo")
    merge = p.get("merge", "on_approval")
    if merge not in MERGE_POLICIES:
        raise ProjectError(f"project {pid}: merge must be one of {', '.join(MERGE_POLICIES)}")
    return {"id": pid, "name": p.get("name") or pid, "path": os.path.normpath(path), "repo": repo,
            "branch": branch, "merge": merge, "push": bool(p.get("push", False)),
            "test_command": (p.get("test_command") or "").strip(), "custom_path": bool(p.get("path")),
            "github_repo": gh_repo}


def get(cfg, project_id=None):
    project_id = project_id or (cfg.get("project") or {}).get("default_project") or DEFAULT_ID
    for p in projects(cfg):
        if p["id"] == project_id:
            return p
    raise ProjectError(f"no project {project_id!r} (add it under Team settings → Projects)")


def inside_babd(path):
    """True when `path` is the BABD installation or inside it (outside workspace/)."""
    real, root = os.path.realpath(path), os.path.realpath(ROOT)
    workspace = os.path.join(root, "workspace")
    return (real == root or real.startswith(root + os.sep)) and not (real == workspace or real.startswith(workspace + os.sep))


def git(args, cwd, check=True, timeout=300):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):  # never point at BABD's own repository
        env.pop(k, None)
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout)
    if check and proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        raise ProjectError(f"git {args[0]} failed: {' | '.join(msg[-2:])[:400]}")
    return proc.stdout.strip()


def is_repo_root(path):
    return os.path.isdir(path) and git(["rev-parse", "--show-toplevel"], path, check=False) == os.path.realpath(path)


def ensure(project):
    """Create or clone the project folder, as its own git repository. Returns its base branch."""
    path = project["path"]
    if inside_babd(path):
        raise ProjectError(f"project {project['id']}: {path} is inside the BABD installation; use a folder "
                           "outside it (or under workspace/)")
    with _lock(path):
        if not is_repo_root(path):
            if project["repo"] and not (os.path.isdir(path) and os.listdir(path)):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                git(["-c", "protocol.ext.allow=never", "clone", "--", project["repo"], path], ROOT, timeout=900)
            else:
                os.makedirs(path, exist_ok=True)
                git(["init", "-q", "-b", project["branch"] or "main"], path)
        if not git(["rev-parse", "--verify", "-q", "HEAD"], path, check=False):  # worktrees need a commit
            _identity(path)
            git(["commit", "-q", "--allow-empty", "-m", "babd: start project"], path)
        branch = project["branch"] or git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        return branch


def _identity(path):
    if not git(["config", "user.email"], path, check=False):
        git(["config", "user.email", "babd@localhost"], path)
    if not git(["config", "user.name"], path, check=False):
        git(["config", "user.name", "BABD agents"], path)


def start(project, run_id):
    """A fresh worktree for one task: {"project", "dir", "branch", "base", "project_dir"}."""
    base = ensure(project)
    branch = f"babd/{run_id}"
    wt = os.path.join(WORKTREES_DIR, project["id"], run_id)
    with _lock(project["path"]):
        if not os.path.isdir(wt):
            os.makedirs(os.path.dirname(wt), exist_ok=True)
            exists = git(["rev-parse", "--verify", "-q", f"refs/heads/{branch}"], project["path"], check=False)
            git(["worktree", "add", "-q", wt, branch] if exists else
                ["worktree", "add", "-q", "-b", branch, wt, base], project["path"])
        _identity(wt)
    return {"project": project["id"], "name": project["name"], "dir": wt, "branch": branch, "base": base,
            "project_dir": project["path"]}


def finish(project, ws, message, merge):
    """Commit the task's changes on its branch; merge into the base branch when `merge`; push when set.
    Returns what happened (never raises: a git problem is reported, not fatal)."""
    out = {"branch": ws["branch"], "commit": None, "files": 0, "merged": False, "pushed": False, "note": ""}
    wt, path = ws["dir"], project["path"]
    try:
        git(["add", "-A"], wt)
        secrets_left = [f for f in git(["diff", "--cached", "--name-only", "-z"], wt).split("\0") if f and is_secret(wt, f)]
        if secrets_left:  # private keys, .env files: never committed (and the worktree keeps them)
            git(["reset", "-q", "--", *secrets_left], wt)
            out["secrets_left_out"] = secrets_left
        changed = [line for line in git(["status", "--porcelain"], wt).splitlines() if line.strip()]
        out["files"] = len(changed)
        if changed:
            git(["commit", "-q", "-m", message], wt)
        ahead = git(["rev-list", "--count", f"{ws['base']}..{ws['branch']}"], path)
        out["commit"] = git(["rev-parse", "--short", ws["branch"]], path) if ahead != "0" else None
        if not out["commit"]:
            out["note"] = "the agents changed no files"
        elif merge:
            with _lock(path):
                current = git(["rev-parse", "--abbrev-ref", "HEAD"], path)
                dirty = git(["status", "--porcelain", "--untracked-files=no"], path)
                if current != ws["base"] or dirty:
                    out["note"] = (f"not merged: {path} is on {current}" + (" with uncommitted changes" if dirty else "")
                                   + f"; merge {ws['branch']} by hand")
                else:
                    proc = subprocess.run(["git", "merge", "--no-ff", "-q", "-m", f"Merge {ws['branch']}: {message}",
                                           ws["branch"]], cwd=path, capture_output=True, text=True)
                    if proc.returncode != 0:
                        git(["merge", "--abort"], path, check=False)
                        out["note"] = f"not merged: conflict with {ws['base']}; merge {ws['branch']} by hand"
                    else:
                        out["merged"] = True
                        if project["push"] and git(["remote"], path, check=False):
                            git(["push", "-q", "origin", ws["base"]], path, timeout=300)
                            out["pushed"] = True
        else:
            out["note"] = f"kept on branch {ws['branch']} for review"
    except (ProjectError, OSError, subprocess.TimeoutExpired) as e:
        out["note"] = f"git: {e}"
    if out.get("secrets_left_out"):
        out["note"] = (out["note"] + "; " if out["note"] else "") + (
            f"not committed (secrets): {', '.join(out['secrets_left_out'][:5])} - kept in {wt}")
    try:  # the branch keeps the work; the worktree folder is not needed any more
        if (out["merged"] or out["commit"] is None) and not out.get("secrets_left_out"):
            git(["worktree", "remove", "--force", wt], path, check=False)
            shutil.rmtree(wt, ignore_errors=True)
    except OSError:
        pass
    return out


SECRET_NAMES = re.compile(r"(^|/)(\.env(\..*)?|id_(rsa|dsa|ecdsa|ed25519)(_sk)?|.*\.(pem|key|p12|pfx|keystore|jks))$", re.I)
SECRET_TEXT = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE" rb" KEY-----")


def is_secret(root, rel):
    """A file that must never be committed: a private key or an env file (by name or content)."""
    if rel.endswith((".pub", ".env.example", ".env.sample")):
        return False
    if SECRET_NAMES.search(rel):
        return True
    try:
        with open(os.path.join(root, rel), "rb") as f:
            return bool(SECRET_TEXT.search(f.read(65536)))
    except OSError:
        return False


def run_tests(command, cwd, timeout=900):
    """Run the project's own test command in the task's worktree: {"command", "exit", "output", "seconds"}."""
    started = time.monotonic()
    from .config import scrub_env
    env = {k: v for k, v in scrub_env(os.environ).items() if not k.startswith(("GIT_DIR", "GIT_WORK_TREE"))}
    try:
        proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        code, out = proc.returncode, (proc.stdout + ("\n" + proc.stderr if proc.stderr else ""))
    except subprocess.TimeoutExpired as e:
        code, out = 124, f"{(e.stdout or b'').decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')}\n[timed out after {timeout}s]"
    tail = out.strip()
    if len(tail) > 6000:
        tail = "[...]\n" + tail[-6000:]
    return {"command": command, "exit": code, "output": tail, "seconds": round(time.monotonic() - started, 1)}


FILE_BLOCK_RE = re.compile(r"^```[^\n`]*?\bfile=([^\s`]+)[^\n]*\n(.*?)^```[ \t]*$", re.S | re.M)


def write_file_blocks(text, root):
    """For agents without file tools: write each ```lang file=path block of `text` under `root`.
    Returns the relative paths written. Paths that leave `root` are ignored."""
    written = []
    root_real = os.path.realpath(root)
    for rel, body in FILE_BLOCK_RE.findall(text or ""):
        rel = rel.strip().strip("'\"")
        target = os.path.realpath(os.path.join(root, rel))
        if not target.startswith(root_real + os.sep) or os.sep + ".git" + os.sep in target + os.sep:
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write(body)
        written.append(os.path.relpath(target, root_real))
    return written
