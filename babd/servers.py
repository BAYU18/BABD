"""Servers the team may reach over SSH (agents.json "servers"), so a task can just say "server lpnotif".

    "servers": [
      {"id": "lpnotif", "name": "Server lpnotif", "host": "203.0.113.7", "port": 22, "user": "root",
       "key": "~/.ssh/babd_lpnotif", "agents": ["devops"], "notes": "Ubuntu 22.04, nginx + app"}
    ]

BABD writes an SSH config (workspace/.babd-ssh/config) with one Host entry per server, so an agent runs
`ssh -F <config> lpnotif '<command>'`; the agents a server lists (default: DevOps) get its entry in
their prompt. Only the key's path is stored, never the key: "Generate key" makes an ed25519 key pair
on this machine and shows the public key to add to the server's ~/.ssh/authorized_keys.
"""
import os
import re
import subprocess

from .config import ROOT

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
HOST_RE = re.compile(r"^(?!-)[A-Za-z0-9.:\-\[\]%]{1,253}$")
USER_RE = re.compile(r"^(?!-)[A-Za-z0-9_.][A-Za-z0-9_.-]{0,31}$")
PATH_RE = re.compile(r"^[^\s\"'`$;|&<>]+$")


class ServerError(Exception):
    pass


def ssh_dir():
    return os.path.join(ROOT, "workspace", ".babd-ssh")


def config_path():
    return os.path.join(ssh_dir(), "config")


def normalize(s):
    sid = str(s.get("id") or "").strip().lower() or re.sub(r"[^a-z0-9]+", "-", str(s.get("name") or "").lower()).strip("-")
    if not ID_RE.match(sid or ""):
        raise ServerError(f"server id {sid!r}: use lowercase letters, digits, '.', '_' or '-'")
    host = str(s.get("host") or "").strip()
    if not HOST_RE.match(host):
        raise ServerError(f"server {sid}: host must be a host name or an IP address")
    user = str(s.get("user") or "root").strip()
    if not USER_RE.match(user):
        raise ServerError(f"server {sid}: {user!r} is not a valid user name")
    try:
        port = int(s.get("port") or 22)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise ServerError(f"server {sid}: port must be 1-65535")
    key = str(s.get("key") or f"~/.ssh/babd_{sid}").strip()
    if not PATH_RE.match(key):
        raise ServerError(f"server {sid}: the key path may not contain spaces or shell characters")
    agents = [str(a) for a in (s.get("agents") or ["devops"]) if str(a).strip()]
    return {"id": sid, "name": str(s.get("name") or sid).strip()[:80], "host": host, "port": port, "user": user,
            "key": key, "agents": agents, "notes": " ".join(str(s.get("notes") or "").split())[:500]}


def servers(cfg):
    return [normalize(s) for s in cfg.get("servers") or []]


def get(cfg, sid):
    for s in servers(cfg):
        if s["id"] == sid:
            return s
    raise ServerError(f"no server {sid!r}")


def key_path(server):
    return os.path.expanduser(server["key"])


def write_config(cfg):
    """The SSH config every agent uses (no secrets in it: only where each server's key is)."""
    os.makedirs(ssh_dir(), mode=0o700, exist_ok=True)
    known = os.path.join(ssh_dir(), "known_hosts")
    lines = ["# Written by BABD from agents.json \"servers\"; edits are overwritten.", ""]
    for s in servers(cfg):
        lines += [f"Host {s['id']}", f"  HostName {s['host']}", f"  User {s['user']}", f"  Port {s['port']}",
                  f"  IdentityFile {key_path(s)}", "  IdentitiesOnly yes", "  BatchMode yes", "  ConnectTimeout 15",
                  "  StrictHostKeyChecking accept-new", f"  UserKnownHostsFile {known}", ""]
    path = config_path()
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write("\n".join(lines))
    return path


def prompt_block(cfg, agent_id):
    """The servers this agent may use, for its prompt ("" when none)."""
    mine = [s for s in servers(cfg) if agent_id in s["agents"]]
    if not mine:
        return ""
    path = config_path()
    rows = "\n".join(f"- {s['id']}: {s['name']} ({s['user']}@{s['host']}:{s['port']})"
                     + (f" — {s['notes']}" if s["notes"] else "") for s in mine)
    return ("## Servers you can reach\n" + rows + f"\n\nConnect with `ssh -F {path} <server id> '<command>'` "
            f"(copy files with `scp -F {path} …`). The keys are set up already; never print or copy a private key. "
            "Say exactly which commands you ran on which server.")


def overview(cfg):
    """One line per server for the Team Lead's triage (who can reach what)."""
    return "\n".join(f"- {s['id']}: {s['name']} (reachable by {', '.join(s['agents'])})" for s in servers(cfg))


def keygen(server):
    """Make the server's key pair when it does not exist yet; return the public key."""
    path = key_path(server)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        try:
            proc = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"babd {server['name']}", "-f", path],
                                  capture_output=True, text=True, timeout=60)
        except FileNotFoundError as e:
            raise ServerError("ssh-keygen is not installed on this machine (Debian/Ubuntu: apt install openssh-client)") from e
        if proc.returncode != 0:
            raise ServerError(f"ssh-keygen failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    pub = path + ".pub"
    if not os.path.exists(pub):
        try:
            proc = subprocess.run(["ssh-keygen", "-y", "-f", path], capture_output=True, text=True, timeout=30)
        except FileNotFoundError as e:
            raise ServerError("ssh-keygen is not installed on this machine (apt install openssh-client)") from e
        if proc.returncode != 0:
            raise ServerError("the key exists but its public key cannot be read (a key with a passphrase?)")
        return proc.stdout.strip()
    with open(pub) as f:
        return f.read().strip()


def test(cfg, sid, timeout=25):
    """Connect once: {"ok", "output"}."""
    server = get(cfg, sid)
    path = write_config(cfg)
    try:
        proc = subprocess.run(["ssh", "-F", path, server["id"], "echo BABD_OK; hostname; uptime"],
                              capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return {"ok": False, "output": "ssh is not installed on this machine"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": f"no answer within {timeout} s"}
    out = (proc.stdout + proc.stderr).strip()
    return {"ok": proc.returncode == 0 and "BABD_OK" in proc.stdout, "output": out[-1500:]}
