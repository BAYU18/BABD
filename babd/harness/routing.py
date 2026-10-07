"""Project one agent's `llm` block into a harness's environment / config files.

Python port of the idea in Paperclip's server/src/services/ai-provider-routing.ts
(`managedProviderRouting`): one authoritative LLM connection per agent, translated into what each
harness understands.
"""
import json
from urllib.parse import urlparse

from ..config import resolve_api_key
from ..llm import api_style
from .base import HarnessError

ANTHROPIC_DEFAULT_HOST = "api.anthropic.com"
ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"

# Inherited variables that would silently override an agent's own Anthropic key or endpoint
# (another login, a host-managed proxy, Bedrock/Vertex/Foundry routing). None = unset for the child.
COMPETING_ANTHROPIC_AUTH = {
    "ANTHROPIC_AUTH_TOKEN": None, "CLAUDE_CODE_OAUTH_TOKEN": None, "CLAUDE_CODE_USE_BEDROCK": None,
    "CLAUDE_CODE_USE_VERTEX": None, "CLAUDE_CODE_USE_FOUNDRY": None, "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST": None,
}


def anthropic_base(base_url):
    """Endpoint root for Anthropic clients (they append /v1/... themselves)."""
    return (base_url or ANTHROPIC_DEFAULT_URL).rstrip("/").removesuffix("/v1")


def is_default_anthropic(base_url):
    return not base_url or urlparse(base_url).hostname == ANTHROPIC_DEFAULT_HOST


def anthropic_auth_env(llm):
    """Env for a child process that must call Anthropic as this agent.

    With the agent's own key, or a custom endpoint, the endpoint is set explicitly and competing
    inherited auth is removed, so another login or a host proxy can't silently take over. With
    neither, the child keeps this machine's own Claude login and settings.
    """
    key = resolve_api_key(llm)
    base_url = llm.get("base_url")
    env = {}
    if key or not is_default_anthropic(base_url):
        env["ANTHROPIC_BASE_URL"] = anthropic_base(base_url)
    if key:
        env["ANTHROPIC_API_KEY"] = key
        env.update(COMPETING_ANTHROPIC_AUTH)
    return env


def hermes_routing(llm):
    """(env, config_yaml, provider_arg) for `hermes chat` with this agent's LLM.

    Custom / OpenAI-compatible endpoints go into config.yaml as provider "custom" (Hermes reads custom
    routing from config.yaml, not OPENAI_BASE_URL). The key stays in the environment and config.yaml
    only references it, so it is never written to disk.
    """
    key = resolve_api_key(llm)
    model = llm.get("model", "")
    base_url = llm.get("base_url") or ""
    env = {}
    lines = ["model:"]
    if api_style(llm) == "anthropic":
        provider = "anthropic"
        env.update(anthropic_auth_env(llm))
        lines += [f'  provider: "anthropic"', f"  default: {json.dumps(model)}"]
        if not is_default_anthropic(base_url):
            lines.append(f"  base_url: {json.dumps(base_url)}")
    else:
        provider = None  # "auto": Hermes uses the custom provider from config.yaml
        if not base_url:
            raise HarnessError("hermes: llm.base_url is required for an OpenAI-compatible endpoint")
        env["OPENAI_BASE_URL"] = base_url
        env["OPENAI_API_KEY"] = key or ""
        lines += ['  provider: "custom"', f"  default: {json.dumps(model)}",
                  f"  base_url: {json.dumps(base_url)}", '  api_mode: "chat_completions"']
        if key:
            lines.append('  api_key: "${OPENAI_API_KEY}"')
    return env, "\n".join(lines) + "\n", provider


def claude_code_routing(llm):
    """Environment for the Claude Code CLI (`claude`) with this agent's LLM."""
    if api_style(llm) != "anthropic":
        raise HarnessError("claude_local: needs an Anthropic-compatible endpoint (set llm.api to \"anthropic\"); "
                           "use hermes_local or process for OpenAI-compatible endpoints")
    env = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    env.update(anthropic_auth_env(llm))
    model = llm.get("model")
    if model:
        for var in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"):
            env[var] = model
    return env


def generic_routing(llm):
    """Environment for a `process` harness: the LLM settings under neutral and OpenAI-style names."""
    key = resolve_api_key(llm) or ""
    env = {
        "BABD_LLM_API": api_style(llm),
        "BABD_LLM_PROVIDER": llm.get("provider", ""),
        "BABD_LLM_BASE_URL": llm.get("base_url", ""),
        "BABD_LLM_MODEL": llm.get("model", ""),
        "BABD_LLM_API_KEY": key,
    }
    if api_style(llm) == "anthropic":
        env.update(anthropic_auth_env(llm))
    else:
        env["OPENAI_API_KEY"] = key
        env["OPENAI_BASE_URL"] = llm.get("base_url", "")
    return env
