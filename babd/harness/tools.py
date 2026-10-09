"""Find or install the program a harness needs.

Like Paperclip's runtime command spec (command / detectCommand / installCommand per adapter), but
installs into the project (.babd/tools/<name>) instead of globally:
  * pip packages get their own virtualenv: .babd/tools/<name>/bin/<command>
  * npm packages get their own prefix:     .babd/tools/<name>/node_modules/.bin/<command>
"""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass

from ..config import ROOT
from ..log import log as _log
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


NODE_DIST = "https://nodejs.org/dist/latest-v22.x"


def log(msg):
    _log(msg, "setup")


def node_dir():
    return os.path.join(TOOLS_DIR, "node")


def extra_path():
    """PATH entries for BABD-installed runtimes (Node.js), so npm-installed CLIs find `node`."""
    d = os.path.join(node_dir(), "bin")
    return [d] if os.path.isdir(d) else []


def _node_platform():
    system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if not system or not arch:
        raise HarnessError(f"automatic Node.js install is not supported on {platform.system()} "
                           f"{platform.machine()}; install Node.js 18+ from https://nodejs.org")
    return f"{system}-{arch}"


def install_node():
    """Download the latest Node.js 22 into .babd/tools/node (checksum-verified). Returns npm path."""
    plat = _node_platform()
    with urllib.request.urlopen(f"{NODE_DIST}/SHASUMS256.txt", timeout=60) as r:
        sums = r.read().decode()
    line = next((ln for ln in sums.splitlines() if ln.endswith(f"-{plat}.tar.gz")), None)
    if not line:
        raise HarnessError(f"no Node.js build for {plat} at {NODE_DIST}")
    digest, name = line.split()
    log(f"downloading Node.js {name} into {os.path.relpath(node_dir(), ROOT)} ...")
    with tempfile.TemporaryDirectory() as tmp:
        archive = os.path.join(tmp, name)
        urllib.request.urlretrieve(f"{NODE_DIST}/{name}", archive)
        h = hashlib.sha256()
        with open(archive, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise HarnessError(f"Node.js download checksum mismatch for {name}")
        with tarfile.open(archive) as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:  # Python without extraction filters: check paths ourselves
                root = os.path.realpath(tmp)
                for member in tar.getmembers():
                    target = os.path.realpath(os.path.join(tmp, member.name))
                    link = None
                    if member.issym():
                        link = os.path.realpath(os.path.join(os.path.dirname(target), member.linkname))
                    elif member.islnk():
                        link = os.path.realpath(os.path.join(tmp, member.linkname))
                    if (not target.startswith(root + os.sep) or member.isdev()
                            or (link is not None and not link.startswith(root + os.sep))):
                        raise HarnessError(f"unsafe path in the Node.js archive: {member.name}")
                tar.extractall(tmp)
        shutil.rmtree(node_dir(), ignore_errors=True)
        os.makedirs(TOOLS_DIR, exist_ok=True)
        shutil.move(os.path.join(tmp, name[: -len(".tar.gz")]), node_dir())
    npm = os.path.join(node_dir(), "bin", "npm")
    log(f"installed Node.js -> {os.path.relpath(npm, ROOT)}")
    return npm


def ensure_npm():
    """npm from PATH, else BABD's own Node.js (installing it the first time)."""
    managed = os.path.join(node_dir(), "bin", "npm")
    if os.path.exists(managed):
        return managed
    return shutil.which("npm") or install_node()


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
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(extra_path() + [env.get("PATH", "")])
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_SEC, env=env)
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
        npm = ensure_npm()
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
        # A relative `command` (e.g. `scripts/researcher_adapter.py` in agents.json) is ROOT-relative:
        # resolve it to an absolute path so a subprocess launched from any cwd finds the program
        # (QA: `Process.command_path()` used to return the relative string, which only worked when
        # cwd happened to be ROOT). An absolute path is used as given. A bare name (no separator)
        # is looked up on PATH first, then as a ROOT-relative file.
        candidate = explicit if os.path.isabs(explicit) else os.path.join(ROOT, explicit)
        if os.sep in explicit:
            path = candidate if os.access(candidate, os.X_OK) else None
        else:
            path = shutil.which(explicit) or (candidate if os.access(candidate, os.X_OK) else None)
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
