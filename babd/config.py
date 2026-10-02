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
