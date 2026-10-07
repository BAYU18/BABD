"""Find or install the program a harness needs.

Like Paperclip's runtime command spec (command / detectCommand / installCommand per adapter), but
installs into the project (.babd/tools/<name>) instead of globally:
  * pip packages get their own virtualenv: .babd/tools/<name>/bin/<command>
  * npm packages get their own prefix:     .babd/tools/<name>/node_modules/.bin/<command>
"""
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

from ..config import ROOT
from .base import HarnessError

TOOLS_DIR = os.path.join(ROOT, ".babd", "tools")
INSTALL_TIMEOUT_SEC = 1200
MARKER = ".babd-installed"


@dataclass(frozen=True)
class InstallSpec:
    name: str        # folder under .babd/tools
    kind: str        # "pip" or "npm"
    package: str     # e.g. "hermes-agent", "@anthropic-ai/claude-code"
    command: str     # executable it provides, e.g. "hermes"
    extras: tuple = ()  # more packages installed alongside (same tool folder)

    def requirement(self, version=None):
        if not version:
            return self.package
        return f"{self.package}=={version}" if self.kind == "pip" else f"{self.package}@{version}"

    def install_list(self, version=None):
        return [self.requirement(version), *self.extras]

    @property
    def install_hint(self):
        return f"pip install {self.package}" if self.kind == "pip" else f"npm install -g {self.package}"


# aiohttp: Hermes' API server (used by hermes_gateway) needs it, but hermes-agent only pulls it in
# through its large "messaging" extra.
HERMES = InstallSpec("hermes", "pip", "hermes-agent", "hermes", extras=("aiohttp>=3.9",))
CLAUDE_CODE = InstallSpec("claude-code", "npm", "@anthropic-ai/claude-code", "claude")


def log(msg):
    print(f"[setup] {msg}", file=sys.stderr, flush=True)


def tool_dir(spec):
    return os.path.join(TOOLS_DIR, spec.name)


def managed_path(spec):
    d = tool_dir(spec)
    if spec.kind == "pip":
        sub = "Scripts" if os.name == "nt" else "bin"
        exe = spec.command + (".exe" if os.name == "nt" else "")
        return os.path.join(d, sub, exe)
    return os.path.join(d, "node_modules", ".bin", spec.command + (".cmd" if os.name == "nt" else ""))


def installed_requirement(spec):
    try:
        with open(os.path.join(tool_dir(spec), MARKER)) as f:
            return f.read().strip()
    except OSError:
        return None


def _run(argv, what):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_SEC)
    except FileNotFoundError as e:
        raise HarnessError(f"{what}: {argv[0]!r} not found") from e
    except subprocess.TimeoutExpired as e:
        raise HarnessError(f"{what}: timed out after {INSTALL_TIMEOUT_SEC}s") from e
    if proc.returncode != 0:
        tail = " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:])
        raise HarnessError(f"{what} failed: {tail[:500]}")


def install(spec, version=None):
    """Install `spec` into .babd/tools/<name>. Returns the executable path."""
    reqs = spec.install_list(version)
    req = " ".join(reqs)
    d = tool_dir(spec)
    what = f"installing {req}"
    log(f"{what} into {os.path.relpath(d, ROOT)} ...")
    if spec.kind == "pip":
        if not os.path.exists(os.path.join(d, "pyvenv.cfg")):
            _run([sys.executable, "-m", "venv", d], f"creating a virtualenv for {spec.package}")
        py = os.path.join(d, "Scripts" if os.name == "nt" else "bin", "python")
        _run([py, "-m", "pip", "install", "--quiet", "--upgrade", *reqs], what)
    elif spec.kind == "npm":
        npm = shutil.which("npm")
        if not npm:
            raise HarnessError(f"{what}: npm not found. Install Node.js (https://nodejs.org) first")
        os.makedirs(d, exist_ok=True)
        _run([npm, "install", "--prefix", d, "--no-audit", "--no-fund", "--loglevel=error", *reqs], what)
    else:
        raise HarnessError(f"unknown install kind {spec.kind!r}")
    path = managed_path(spec)
    if not os.path.exists(path):
        raise HarnessError(f"{what}: finished but {path} is missing")
    with open(os.path.join(d, MARKER), "w") as f:
        f.write(req)
    log(f"installed {req} -> {os.path.relpath(path, ROOT)}")
    return path


def ensure_command(label, cfg, spec):
    """Path of the harness program, installing it when needed.

    Order: explicit `command` -> BABD-managed install -> on PATH -> auto-install (unless
    `auto_install: false`). With `version` set, only a managed install of that version counts.
    """
    explicit = cfg.get("command")
    if explicit:
        path = shutil.which(explicit) or (explicit if os.path.isabs(explicit) and os.access(explicit, os.X_OK) else None)
        if not path:
            raise HarnessError(f"{label}: command {explicit!r} not found")
        return path
    version = cfg.get("version")
    managed = managed_path(spec)
    if os.path.exists(managed):
        have = installed_requirement(spec)
        if have == " ".join(spec.install_list(version)):
            return managed
        if not version and have == " ".join(spec.install_list()[:1]):
            return install(spec)  # older BABD install without the extras: top it up
        if not version:
            return managed
    if not version:
        on_path = shutil.which(spec.command)
        if on_path:
            return on_path
    if not cfg.get("auto_install", True):
        raise HarnessError(f"{label}: {spec.command!r} not found and auto_install is off ({spec.install_hint})")
    return install(spec, version)
