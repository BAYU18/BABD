"""What an agent may do with its tools: one permission profile per agent (`permissions` in agents.json).

    plan       no terminal: the agent reads and writes files and searches the web (Hermes toolsets
               file + web; Claude Code without Bash). For the Team Lead and the Architect.
    ask        the tool's own default: ordinary commands run, commands the tool finds dangerous need a
               person's approval. Nobody answers during a team run, so those are refused.
    workspace  runs commands without asking, in its task's worktree; a deny list blocks dangerous
               commands (sudo, rm -rf /, force pushes, curl | sh, ...) and any command that touches
               the BABD installation (its code, agents.json, .env, .git, .babd). For Developer, QA, DevOps.
    full       runs anything without asking. Only inside a sandbox.

Isolation (`sandbox` per agent, or `project.isolation` for every agent that does not set one):

    bwrap   the agent's program runs in its own Linux namespaces (bubblewrap): the whole system and the
            BABD installation are read-only, only the task's worktree, the agent's own home, its tool
            caches and /tmp can be written; .env, runs/, logs/, the secrets backup and the other agents'
            homes are hidden; BABD's processes are invisible (own PID namespace). No root needed:
            `apt install bubblewrap`. Extra writable folders: harness option `writable: ["/var/www"]`.
    docker  a Hermes agent's commands run in a Docker container that only sees the task's worktree.

The deny list is a guardrail, not a sandbox: a determined command can get around a pattern. The
bwrap sandbox is enforced by the kernel.
"""
import json
import os
import shutil

from .config import ROOT

PROFILES = {
    "plan": "No terminal: reads and writes files and searches the web only",
    "ask": "The tool's default: ordinary commands run; ones it finds dangerous need approval, which nobody gives during a run",
    "workspace": "Runs commands in its task's worktree without asking; dangerous commands and changes to BABD are blocked",
    "full": "Runs any command without asking (use only with the Docker sandbox)",
}
DEFAULT_PROFILE = {"lead": "plan", "architect": "plan", "developer": "workspace", "qa": "workspace",
                   "devops": "workspace", "researcher": "workspace"}
SANDBOXES = ("none", "bwrap", "docker")

DANGEROUS = [
    "sudo *", "* sudo *", "su -*", "*rm -rf /", "*rm -rf / *", "*rm -rf /\\**", "*rm -rf ~*", "*rm -rf $HOME*",
    "*mkfs*", "*shutdown*", "*reboot*", "*halt -*", "*:(){*", "*dd if=*of=/dev/*", "*> /dev/sd*",
    "*chmod -R 777 /*", "*chown -R * /*", "*git push --force*", "*git push -f*", "*git push * --force*",
    "*git push * -f*", "*curl *|*sh*", "*wget *|*sh*", "*docker system prune*", "*crontab -r*",
]


class PermissionsError(ValueError):
    pass


def babd_guards(root=ROOT):
    """Deny patterns for commands that touch the BABD installation (outside its workspace/)."""
    r = root.rstrip("/")
    from .config import SECRETS_BACKUP
    backup_dir = os.path.dirname(SECRETS_BACKUP)
    return [f"*cd {r}", f"*cd {r}[ ;&|]*", f"*cd {r}/", f"*-C {r}", f"*-C {r}[ /]*", f"*{r}/babd*",
            f"*{r}/agents.json*", f"*{r}/.env*", f"*{r}/.git", f"*{r}/.git[ /]*", f"*{r}/.babd*",
            f"*{r}/generate_workspace.py*", f"*{r}/install.sh*", f"*{r}/logs*",
            f"*{backup_dir}*", "*.config/babd*", "*/proc/*/environ*"]


def profile_of(agent_cfg):
    p = agent_cfg.get("permissions")
    if p is None:
        h = agent_cfg.get("harness") or {}
        if h.get("yolo"):
            return "full"
        p = DEFAULT_PROFILE.get(agent_cfg.get("id"), "ask")
    if p not in PROFILES:
        raise PermissionsError(f"agent {agent_cfg.get('id')}: permissions must be one of {', '.join(PROFILES)}")
    return p


def sandbox_of(agent_cfg, project=None):
    s = agent_cfg.get("sandbox") or (project or {}).get("isolation") or "none"
    if s not in SANDBOXES:
        raise PermissionsError(f"agent {agent_cfg.get('id')}: sandbox must be one of {', '.join(SANDBOXES)}")
    return s


def hermes_toolsets(profile, toolsets):
    """The toolsets for `hermes chat -t`: the plan profile never gets the terminal."""
    if profile != "plan":
        return toolsets
    allowed = [t for t in (toolsets or ["file", "web"]) if t not in ("terminal", "code_execution", "process")]
    return allowed or ["file"]


def hermes_config(profile, sandbox, root=ROOT):
    """YAML for HERMES_HOME/config.yaml: approvals (mode + deny rules) and the terminal backend."""
    lines = ["approvals:"]
    if profile in ("workspace", "full"):
        deny = (DANGEROUS if profile == "workspace" else []) + babd_guards(root)
        lines += ['  mode: "off"', "  deny:"] + [f"    - {json.dumps(d)}" for d in deny]
    else:
        lines += ['  mode: "manual"', "  deny:"] + [f"    - {json.dumps(d)}" for d in babd_guards(root)]
    lines += ['  cron_mode: "deny"']
    if sandbox == "docker":
        lines += ["terminal:", '  backend: "docker"', "  docker_mount_cwd_to_workspace: true",
                  '  cwd: "/workspace"']
    return "\n".join(lines) + "\n"


def check_sandbox(sandbox):
    if sandbox == "docker" and not shutil.which("docker"):
        raise PermissionsError("sandbox \"docker\" needs Docker on this machine (docker not found on PATH)")
    if sandbox == "bwrap":
        bwrap_check()


_bwrap_ok = {}


def bwrap_check():
    """Raise PermissionsError unless bubblewrap can make a sandbox on this machine (checked once)."""
    if "ok" in _bwrap_ok:
        if _bwrap_ok["ok"] is not True:
            raise PermissionsError(_bwrap_ok["ok"])
        return
    import subprocess
    path = shutil.which("bwrap")
    if not path:
        _bwrap_ok["ok"] = ("sandbox \"bwrap\" needs bubblewrap on this machine (Debian/Ubuntu: apt install bubblewrap)")
    else:
        try:
            proc = subprocess.run([path, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-pid",
                                   "--die-with-parent", "true"], capture_output=True, text=True, timeout=20)
            _bwrap_ok["ok"] = True if proc.returncode == 0 else (
                "bubblewrap cannot create a sandbox here: " + (proc.stderr.strip()[:300] or f"exit {proc.returncode}")
                + " (unprivileged user namespaces may be off: sysctl kernel.unprivileged_userns_clone=1, or the "
                  "AppArmor profile of the bubblewrap package on Ubuntu 24.04)")
        except (OSError, subprocess.TimeoutExpired) as e:
            _bwrap_ok["ok"] = f"bubblewrap failed: {e}"
    bwrap_check()


def bwrap_argv(argv, cwd, writable=(), root=ROOT, hide_dirs=(), hide_files=()):
    """argv wrapped in a bubblewrap sandbox: everything read-only, `writable` folders (and cwd) writable,
    BABD's secrets and data hidden, own PID namespace."""
    from .config import ENV_PATH, SECRETS_BACKUP
    home = os.path.expanduser("~")
    r = os.path.realpath(root)
    out = [shutil.which("bwrap") or "bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
           "--tmpfs", "/tmp", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
           "--new-session"]
    if os.path.isdir(home):
        out += ["--bind", home, home]  # tool caches (npm, pip, ~/.ssh known hosts) keep working
    out += ["--ro-bind", r, r]  # the installation: read-only, also when it is inside the home folder
    for d in dict.fromkeys(p for p in [cwd, *writable] if p and os.path.isdir(p)):
        out += ["--bind", d, d]  # ...except the task's folders and the agent's own home under it
    hidden_dirs = [os.path.join(r, "runs"), os.path.join(r, "logs"), os.path.dirname(SECRETS_BACKUP), *hide_dirs]
    for d in dict.fromkeys(hidden_dirs):
        if os.path.isdir(d) and not any(os.path.realpath(w).startswith(os.path.realpath(d)) for w in [cwd, *writable] if w):
            out += ["--tmpfs", d]
    for f in dict.fromkeys([ENV_PATH, os.path.join(r, ".babd", "telegram.json"), *hide_files]):
        if os.path.isfile(f):
            out += ["--ro-bind", "/dev/null", f]
    return out + ["--chdir", cwd, "--", *argv]


CLAUDE_DENY = ["Bash(sudo:*)", "Bash(git push --force:*)", "Bash(git push -f:*)", "Bash(rm -rf /:*)",
               "Bash(shutdown:*)", "Bash(reboot:*)", "Bash(mkfs:*)"]


def claude_guards(root=ROOT):
    """Claude Code rules that keep the agent's file tools away from BABD itself and its secrets."""
    from .config import SECRETS_BACKUP
    r = root.rstrip("/")
    secret = [f"{r}/.env", f"{r}/.babd/**", f"{os.path.dirname(SECRETS_BACKUP)}/**"]
    babd = [f"{r}/agents.json", f"{r}/babd/**", f"{r}/.git/**", f"{r}/runs/**", f"{r}/logs/**"]
    return ([f"Read(/{p})" for p in secret] + [f"Edit(/{p})" for p in secret + babd]
            + [f"Bash(cat {r}/.env:*)"])


def claude_args(profile):
    """Claude Code flags for a profile (it already keeps file edits inside its working folder)."""
    if profile == "plan":
        return ["--permission-mode", "acceptEdits", "--disallowedTools", "Bash", *claude_guards()]
    if profile == "workspace":
        return ["--permission-mode", "acceptEdits", "--allowedTools", "Bash", "--disallowedTools", *CLAUDE_DENY,
                *claude_guards()]
    if profile == "full":
        return ["--dangerously-skip-permissions"]
    return []
