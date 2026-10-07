"""GBrain team memory (https://github.com/garrytan/gbrain), running locally.

Every agent starts a task by READING gbrain and finishes it by WRITING to gbrain:

    recall (keywords of the goal + task)  ->  agent works with that memory in its prompt
    put_page (the agent's full output)    +   remember (a one-line fact with provenance)

BABD does both calls itself around every agent step, so it happens no matter which harness or model
the agent runs on. Agents with tools (Hermes, Claude Code) also get the `gbrain` command and
GBRAIN_HOME in their environment, to search or save more on their own.

Local and keyless by default: a PGLite brain (embedded Postgres, no server) in .babd/gbrain, keyword
search, no embeddings. Cloud API keys are removed from gbrain's environment unless
project.gbrain.allow_cloud is true, so no memory text leaves the machine.

Installed into the project, like the harnesses: Bun from GitHub releases (checksum-verified) and the
gbrain source (git clone, or a GitHub tarball without git), with `bun install`; never from npm (the
npm package called gbrain is unrelated).
"""
import datetime
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

from .config import ROOT
from .log import log as _log

GBRAIN_REPO = "https://github.com/garrytan/gbrain.git"
GBRAIN_TARBALL = "https://codeload.github.com/garrytan/gbrain/tar.gz/{ref}"
BUN_RELEASES = "https://github.com/oven-sh/bun/releases/latest/download"
MIN_BUN = (1, 4, 0)
DEFAULT_REF = "latest-stable"
CLOUD_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "VOYAGE_API_KEY", "GOOGLE_API_KEY",
              "GEMINI_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY", "ZEROENTROPY_API_KEY")
STOPWORDS = set("""a an and are as at be by for from has have in into is it its of on or that the this to with your you
our we will can should must make build do does done task goal work team please using use via per each all any not
than then them they their there these those what when where which who how also just only more most new add
""".split())
_lock = threading.Lock()  # one gbrain call at a time: the PGLite brain has a single writer


class BrainError(Exception):
    pass


def log(msg):
    _log(msg, "gbrain")


def tools_dir():
    from .harness import tools  # tools.TOOLS_DIR can be patched in tests
    return tools.TOOLS_DIR


def bun_dir():
    return os.path.join(tools_dir(), "bun")


def gbrain_dir():
    return os.path.join(tools_dir(), "gbrain")


def launcher_path():
    return os.path.join(gbrain_dir(), "bin", "gbrain")


def _version_tuple(text):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _run(argv, what, cwd=None, env=None, timeout=900):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, env=env, timeout=timeout)
    except FileNotFoundError as e:
        raise BrainError(f"{what}: {argv[0]!r} not found") from e
    except subprocess.TimeoutExpired as e:
        raise BrainError(f"{what}: timed out") from e
    if proc.returncode != 0:
        tail = " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-3:])
        raise BrainError(f"{what} failed: {tail[:400]}")
    return proc.stdout


# -- installation ------------------------------------------------------------------------------

def _bun_asset():
    system = {"Linux": "linux", "Darwin": "darwin"}.get(platform.system())
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "aarch64", "arm64": "aarch64"}.get(platform.machine().lower())
    if not system or not arch:
        raise BrainError(f"automatic Bun install is not supported on {platform.system()} {platform.machine()}; "
                         "install Bun 1.4+ from https://bun.sh")
    name = f"bun-{system}-{arch}"
    if name == "bun-linux-x64":
        try:
            with open("/proc/cpuinfo") as f:
                if "avx2" not in f.read():
                    name += "-baseline"  # Bun's build for CPUs without AVX2
        except OSError:
            pass
    return name


def install_bun():
    """Download the latest Bun into .babd/tools/bun (checksum-verified). Returns the bun path."""
    asset = _bun_asset()
    with urllib.request.urlopen(f"{BUN_RELEASES}/SHASUMS256.txt", timeout=60) as r:
        sums = r.read().decode()
    line = next((ln for ln in sums.splitlines() if ln.endswith(f" {asset}.zip")), None)
    if not line:
        raise BrainError(f"no Bun build {asset}.zip in the latest release")
    digest = line.split()[0]
    log(f"downloading Bun ({asset}) into {os.path.relpath(bun_dir(), ROOT)} ...")
    with urllib.request.urlopen(f"{BUN_RELEASES}/{asset}.zip", timeout=300) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise BrainError("Bun download checksum mismatch")
    os.makedirs(os.path.join(bun_dir(), "bin"), exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        exe = z.read(f"{asset}/bun")
    path = os.path.join(bun_dir(), "bin", "bun")
    with open(path, "wb") as f:
        f.write(exe)
    os.chmod(path, 0o755)
    log(f"installed Bun {_bun_version(path)}")
    return path


def _bun_version(path):
    try:
        return subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ensure_bun():
    managed = os.path.join(bun_dir(), "bin", "bun")
    if os.path.exists(managed) and _version_tuple(_bun_version(managed)) >= MIN_BUN:
        return managed
    system = shutil.which("bun")
    if system and _version_tuple(_bun_version(system)) >= MIN_BUN:
        return system
    return install_bun()


def install_gbrain(ref=DEFAULT_REF):
    """gbrain source + dependencies in .babd/tools/gbrain, and a `gbrain` launcher. Returns its path."""
    bun = ensure_bun()
    src = os.path.join(gbrain_dir(), "src")
    marker = os.path.join(gbrain_dir(), ".babd-installed")
    if os.path.exists(launcher_path()) and os.path.exists(marker):
        with open(marker) as f:
            if f.read().strip() == ref:
                write_launcher(bun, src)  # keep the launcher current with this BABD version
                return launcher_path()
    log(f"installing gbrain ({ref}) into {os.path.relpath(gbrain_dir(), ROOT)} ...")
    shutil.rmtree(src, ignore_errors=True)
    os.makedirs(gbrain_dir(), exist_ok=True)
    if shutil.which("git"):
        _run(["git", "clone", "--quiet", "--depth", "1", "--branch", ref, GBRAIN_REPO, src], "git clone gbrain")
    else:
        with urllib.request.urlopen(GBRAIN_TARBALL.format(ref=ref), timeout=300) as r:
            data = r.read()
        with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(data)) as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                tar.extractall(tmp)
            (top,) = os.listdir(tmp)
            shutil.move(os.path.join(tmp, top), src)
    _run([bun, "install"], "bun install (gbrain)", cwd=src)
    write_launcher(bun, src)
    with open(marker, "w") as f:
        f.write(ref)
    log(f"installed gbrain -> {os.path.relpath(launcher_path(), ROOT)}")
    return launcher_path()


def write_launcher(bun, src):
    """.babd/tools/gbrain/bin/gbrain: runs gbrain with Bun and, unless BABD_GBRAIN_ALLOW_CLOUD=1, without
    cloud API keys, so memory stays on this machine even when an agent (which has its own LLM key)
    calls gbrain itself."""
    unset = " ".join(CLOUD_KEYS)
    script = ("#!/bin/sh\n"
              f'if [ "${{BABD_GBRAIN_ALLOW_CLOUD:-0}}" != "1" ]; then unset {unset}; fi\n'
              f'exec "{bun}" "{os.path.join(src, "src", "cli.ts")}" "$@"\n')
    os.makedirs(os.path.dirname(launcher_path()), exist_ok=True)
    with open(launcher_path(), "w") as f:
        f.write(script)
    os.chmod(launcher_path(), 0o755)


# -- the brain ---------------------------------------------------------------------------------

def keywords(*texts, limit=8):
    """Distinctive words from the texts, for gbrain's keyword search ("a or b or c")."""
    seen = []
    for t in texts:
        for w in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", t or ""):
            w = w.lower().strip("-_")
            if w not in STOPWORDS and w not in seen:
                seen.append(w)
    return seen[:limit]


def slugify(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:limit].rstrip("-") or "untitled"


def one_line(text, limit=280):
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


class GBrain:
    """The team's shared gbrain. Settings come from project.gbrain in agents.json."""

    def __init__(self, project_cfg=None):
        c = dict((project_cfg or {}).get("gbrain") or {})
        self.enabled = c.get("enabled", True)
        self.strict = c.get("strict", True)            # a failed read/write fails the agent step
        self.allow_cloud = c.get("allow_cloud", False)  # pass cloud API keys to gbrain
        self.ref = c.get("ref", DEFAULT_REF)
        self.budget_tokens = int(c.get("budget_tokens", 1200))
        home = c.get("home") or os.path.join(".babd", "gbrain")
        self.home = home if os.path.isabs(home) else os.path.join(ROOT, home)
        self.command = c.get("command")  # use an existing gbrain instead of installing one

    # -- environment + calls -----------------------------------------------------------------

    @property
    def db_path(self):
        return os.path.join(self.home, ".gbrain", "brain.pglite")

    def gbrain_path(self):
        if self.command:
            path = shutil.which(self.command) or self.command
            if not os.path.exists(path):
                raise BrainError(f"gbrain command {self.command!r} not found")
            return path
        return launcher_path() if os.path.exists(launcher_path()) else None

    def env(self):
        env = dict(os.environ)
        if not self.allow_cloud:
            for k in CLOUD_KEYS:
                env.pop(k, None)
        env["GBRAIN_HOME"] = self.home
        env["NO_COLOR"] = "1"
        if self.allow_cloud:
            env["BABD_GBRAIN_ALLOW_CLOUD"] = "1"
        extra = [os.path.join(bun_dir(), "bin"), os.path.dirname(launcher_path())]
        env["PATH"] = os.pathsep.join([p for p in extra if os.path.isdir(p)] + [env.get("PATH", "")])
        return env

    def agent_env(self):
        """Env vars that give a harness agent its own `gbrain` command on the team brain."""
        if not self.enabled or not os.path.exists(self.db_path):
            return {}
        try:
            path = self.gbrain_path()
        except BrainError:
            return {}
        if not path:
            return {}
        dirs = [os.path.dirname(os.path.abspath(path)), os.path.join(bun_dir(), "bin")]
        env = {"GBRAIN_HOME": self.home, "PATH": os.pathsep.join(dirs)}
        if self.allow_cloud:  # BABD's launcher strips cloud keys unless this is set
            env["BABD_GBRAIN_ALLOW_CLOUD"] = "1"
        return env

    def call(self, *args, stdin=None, timeout=180):
        path = self.gbrain_path()
        if not path:
            raise BrainError("gbrain is not installed (run: babd setup)")
        with _lock:
            try:
                proc = subprocess.run([path, *args], input=stdin, capture_output=True, text=True,
                                      env=self.env(), cwd=self.home, timeout=timeout)
            except subprocess.TimeoutExpired as e:
                raise BrainError(f"gbrain {args[0]} timed out") from e
        if proc.returncode != 0:
            lines = [ln for ln in (proc.stdout + "\n" + proc.stderr).splitlines() if ln.strip()]
            raise BrainError(f"gbrain {args[0]} failed (exit {proc.returncode}): {' | '.join(lines[-2:])[:400]}")
        out = proc.stdout.strip()
        try:
            return json.loads(out) if out else {}
        except json.JSONDecodeError:
            starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]  # tolerate a log line first
            return json.loads(out[min(starts):]) if starts else {"text": out}

    # -- setup -------------------------------------------------------------------------------

    def setup(self):
        """Install Bun + gbrain if needed and create the local brain. Safe to run repeatedly."""
        if not self.enabled:
            return "disabled"
        if not self.command:
            install_gbrain(self.ref)
        os.makedirs(self.home, mode=0o700, exist_ok=True)
        ready = os.path.join(self.home, ".babd-brain-ready")
        if not os.path.exists(ready):
            if os.path.exists(self.db_path) and self._answers():
                pass  # a brain from an earlier BABD version: keep it
            else:
                if os.path.exists(os.path.join(self.home, ".gbrain")):  # a half-made brain: keep it aside
                    aside = os.path.join(self.home, f".gbrain.failed-{datetime.datetime.now():%Y%m%d-%H%M%S}")
                    os.rename(os.path.join(self.home, ".gbrain"), aside)
                    log(f"moved an unusable brain aside to {os.path.relpath(aside, ROOT)}")
                log(f"creating the team brain in {os.path.relpath(self.home, ROOT)} (PGLite, keyless) ...")
                # --git: the brain's content folder gets its own repository. Without it gbrain refuses
                # to create the folder inside another git worktree, i.e. inside a cloned BABD project.
                self.call("init", "--pglite", "--no-embedding", "--git", "--json", timeout=300)
            self.call("apply-migrations", "--yes", "--no-autopilot-install", timeout=600)
            with open(ready, "w") as f:
                f.write(now_stamp() + "\n")
        version = subprocess.run([self.gbrain_path(), "--version"], capture_output=True, text=True,
                                 env=self.env(), timeout=60).stdout.strip()
        return f"{version or 'gbrain'} · brain {os.path.relpath(self.home, ROOT)}"

    def _answers(self):
        try:
            self.call("recall", "--query", "babd", "--budget-tokens", "50", "--json", timeout=120)
            return True
        except BrainError:
            return False

    def status(self):
        return {"enabled": self.enabled, "installed": bool(self.gbrain_path()),
                "brain": os.path.exists(self.db_path), "home": os.path.relpath(self.home, ROOT),
                "strict": self.strict, "allow_cloud": self.allow_cloud}

    # -- the read / write cycle --------------------------------------------------------------

    def recall(self, *texts, budget_tokens=None):
        """Memory relevant to the texts: {"query", "facts", "results"}."""
        words = keywords(*texts)
        query = " or ".join(words) or "babd"
        data = self.call("recall", "--query", query, "--budget-tokens", str(budget_tokens or self.budget_tokens),
                         "--budget-policy", "query_first", "--json")
        return {"query": query, "facts": data.get("facts") or [], "results": data.get("results") or []}

    def remember(self, fact, entity, provenance):
        return self.call("remember", one_line(fact, 600), "--entity", entity, "--provenance", provenance, "--json")

    def put_page(self, slug, title, body, tags=()):
        tag_list = ", ".join(json.dumps(t) for t in tags)
        md = f"---\ntitle: {json.dumps(title)}\ntype: note\ntags: [{tag_list}]\n---\n\n{body.strip()}\n"
        # Handle revision_conflict: page may already exist (e.g., resume run)
        try:
            existing = self.call("get", slug, "--json")
            revision = existing.get("revision") or existing.get("knowledge_revision") or ""
            if revision:
                return self.call("put", slug, "--expected-revision", revision, stdin=md)
        except BrainError:
            pass  # page does not exist yet: create it
        return self.call("put", slug, stdin=md)

    def search(self, query, limit=10):
        return self.call("search", query, "--json")[:limit] if query.strip() else []


def format_memory(memory):
    """Recall result as a prompt section the agent reads before working."""
    lines = []
    for f in memory["facts"]:
        lines.append(f"- {f.get('fact')} [source: {f.get('provenance') or f.get('source') or '?'}]")
    for r in memory["results"]:
        chunk = one_line(r.get("chunk") or "", 600)
        lines.append(f"- page {r.get('slug')}: {chunk}")
    if not lines:
        return ("## Team memory (gbrain)\nNothing relevant found in gbrain for: "
                f"{memory['query']}. You are the first to work on this.")
    return ("## Team memory (gbrain)\nRead before you work. These are earlier decisions and results saved by the "
            "team; follow them unless the task says otherwise, and say so when you deviate.\n" + "\n".join(lines))


def now_stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
