"""Load agents.json and resolve secrets (API keys) from the environment or a .env file."""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "agents.json")
SKILLS_DIR = os.path.join(ROOT, "skills")


def _read_env_file(path):
    """{NAME: value} from a .env file (KEY=VALUE lines, optional `export `, quotes stripped)."""
    out = {}
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return out
    except OSError as e:  # e.g. written by another user (mode 600): say so instead of losing every key
        print(f"babd: cannot read {path}: {e}", file=sys.stderr)
        return out
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_dotenv(path=None):
    """Load .env (and the secrets backup outside the installation, see set_env_var) into the
    environment. A variable that is already set wins, unless it is set but empty. Keys found only in
    the backup are written back into .env (after a reinstall or a fresh clone). Returns the names loaded."""
    path = path or ENV_PATH
    values = _read_env_file(path)
    restored = {k: v for k, v in _read_env_file(SECRETS_BACKUP).items() if v and not values.get(k)} \
        if path == ENV_PATH else {}
    loaded = []
    for key, value in {**values, **restored}.items():
        if value and not os.environ.get(key):
            os.environ[key] = value
            loaded.append(key)
        elif value and os.environ.get(key) != value:
            print(f"babd: {key} is set in the environment (systemd unit, shell profile, ...) and that value "
                  f"wins over the one in {path}; unset it there to use the key saved from the dashboard",
                  file=sys.stderr)
    for key, value in restored.items():
        try:
            set_env_var(key, value, path=path, backup=False)
        except (OSError, ValueError):
            pass
    return loaded


def load_config(path=CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


def save_config(cfg, path=CONFIG_PATH):
    with open(path, "w") as f:
        f.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def resolve_api_key(llm):
    """The agent's API key: `api_key` if written in the config, else the `api_key_env` variable."""
    if llm.get("api_key"):
        return llm["api_key"]
    if llm.get("api_key_env"):
        return os.environ.get(llm["api_key_env"]) or None
    return None


def resolve_env(name):
    """The value of an environment variable named in the config (None when unset or unnamed)."""
    return (os.environ.get(name) or None) if name else None


def skill_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_skill_text(name):
    """Contents of skills/<slug>.md for a skill, or None when there is no such file."""
    path = os.path.join(SKILLS_DIR, skill_slug(name) + ".md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return None


ENV_PATH = os.path.join(ROOT, ".env")
# A copy of the keys set through BABD, outside the installation (one file per installation folder).
SECRETS_BACKUP = os.environ.get("BABD_SECRETS_BACKUP") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config"), "babd",
    f"secrets-{hashlib.sha256(ROOT.encode()).hexdigest()[:10]}.env")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROTECTED_ENV = {"PATH", "HOME", "SHELL", "USER", "PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "HTTP_PROXY",
                 "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"}


def set_env_var(name, value, path=None, backup=True):
    """Write NAME=value into .env (file mode 600) and the current process environment. An empty value
    removes the line. Keys written to BABD's own .env are also kept in SECRETS_BACKUP (outside the
    installation, mode 600), so a reinstall, a fresh clone or `git clean` never loses them."""
    path = path or ENV_PATH
    if not ENV_NAME_RE.match(name or ""):
        raise ValueError(f"invalid environment variable name: {name!r}")
    if name.upper() in PROTECTED_ENV or name.upper().startswith(("LD_", "DYLD_")):
        raise ValueError(f"{name} is a system variable; use a name like MY_AGENT_API_KEY")
    if any(c in value for c in "\r\n"):
        raise ValueError("value must be a single line")
    _write_env_line(path, name, value)
    if value:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
    if backup and path == ENV_PATH and SECRETS_BACKUP:
        try:
            _write_env_line(SECRETS_BACKUP, name, value)
        except OSError as e:
            print(f"babd: cannot update the secrets backup {SECRETS_BACKUP}: {e}", file=sys.stderr)


def _write_env_line(path, name, value):
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = [ln for ln in f.read().splitlines()
                     if not ln.strip().removeprefix("export ").lstrip().startswith(f"{name}=")]
    if value:
        lines.append(f"{name}={value}")
    os.makedirs(os.path.dirname(path) or ".", mode=0o700, exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)  # never a half-written .env


def missing_keys(cfg):
    """{variable: [agent ids]} for API key variables named in agents.json that hold no value."""
    out = {}
    for a in cfg.get("agents", []):
        llm = a.get("llm") or {}
        if llm.get("api_key") or not llm.get("api_key_env"):
            continue
        if not os.environ.get(llm["api_key_env"]):
            out.setdefault(llm["api_key_env"], []).append(a["id"])
    return out
