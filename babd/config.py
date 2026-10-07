"""Load agents.json and resolve secrets (API keys) from the environment or a .env file."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "agents.json")
SKILLS_DIR = os.path.join(ROOT, "skills")


def load_dotenv(path=os.path.join(ROOT, ".env")):
    """Minimal .env loader: KEY=VALUE lines; existing environment variables win."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROTECTED_ENV = {"PATH", "HOME", "SHELL", "USER", "PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "HTTP_PROXY",
                 "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"}


def set_env_var(name, value, path=None):
    """Write NAME=value into .env (file mode 600) and the current process environment.
    An empty value removes the line."""
    path = path or ENV_PATH
    if not ENV_NAME_RE.match(name or ""):
        raise ValueError(f"invalid environment variable name: {name!r}")
    if name.upper() in PROTECTED_ENV or name.upper().startswith(("LD_", "DYLD_")):
        raise ValueError(f"{name} is a system variable; use a name like MY_AGENT_API_KEY")
    if any(c in value for c in "\r\n"):
        raise ValueError("value must be a single line")
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith(f"{name}=")]
    if value:
        lines.append(f"{name}={value}")
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
