"""One LLM client per agent, built from the agent's `llm` block in agents.json.

Two API styles are supported:
  * "anthropic" - Claude via the official Anthropic SDK (Messages API).
  * "openai"    - any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, OpenRouter, ...)
                  via the official OpenAI SDK (Chat Completions).
"""
import importlib
import subprocess
import sys
from urllib.parse import urlparse

from .config import resolve_api_key

try:
    import anthropic
except ImportError:  # installed on first use, see _sdk()
    anthropic = None
try:
    import openai
except ImportError:
    openai = None

SDK_REQUIREMENTS = {"anthropic": "anthropic>=1.11.0", "openai": "openai>=3.0.0"}


def _sdk(name):
    """The SDK module, pip-installing it into this Python environment the first time it is needed."""
    mod = globals().get(name)
    if mod is None:
        req = SDK_REQUIREMENTS[name]
        from .log import log
        log(f"installing {req} ...")
        proc = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", req], capture_output=True, text=True)
        if proc.returncode != 0:
            tail = " | ".join(proc.stderr.strip().splitlines()[-2:])
            raise LLMError(f"could not install {req} ({tail[:300]}); run: pip install -r requirements.txt")
        mod = importlib.import_module(name)
        globals()[name] = mod
    return mod

# Models that accept the server-side refusal fallback (`fallbacks: "default"`) on the Claude API.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


def api_style(llm):
    return llm.get("api") or ("anthropic" if llm.get("provider", "").lower() == "anthropic" else "openai")


class LLMClient:
    def __init__(self, llm, timeout=600.0):
        self.cfg = llm
        self.api = api_style(llm)
        self.model = llm["model"]
        self.base_url = llm.get("base_url") or None
        key = resolve_api_key(llm)

        if self.api in ("anthropic", "openai"):
            _sdk(self.api)
        if self.api == "anthropic":
            # The SDK appends /v1/messages itself, so drop a trailing /v1 from the configured URL.
            base = self.base_url.rstrip("/") if self.base_url else None
            if base and base.endswith("/v1"):
                base = base[:-3]
            # With no key configured the SDK resolves ANTHROPIC_API_KEY / `ant auth login` itself.
            kwargs = {"timeout": timeout}
            if key:
                kwargs["api_key"] = key
            if base:
                kwargs["base_url"] = base
            self.client = anthropic.Anthropic(**kwargs)
            host = urlparse(base or "https://api.anthropic.com").hostname
            self.use_fallback = (llm.get("refusal_fallback", True) and self.model in FALLBACK_MODELS
                                 and host == "api.anthropic.com")
        elif self.api == "openai":
            # Local servers usually ignore the key, but the SDK requires a non-empty value.
            self.client = openai.OpenAI(api_key=key or "not-needed", base_url=self.base_url, timeout=timeout)
        else:
            raise LLMError(f"unknown llm.api {self.api!r} (use 'anthropic' or 'openai')")

    def complete(self, system, messages, max_tokens=None, effort=None):
        """Send a conversation and return the assistant's reply text."""
        if self.api == "anthropic":
            return self._anthropic(system, messages, max_tokens or self.cfg.get("max_tokens", 16000), effort)
        return self._openai(system, messages, max_tokens or self.cfg.get("max_tokens", 4096))

    def _anthropic(self, system, messages, max_tokens, effort):
        kwargs = {"model": self.model, "max_tokens": max_tokens, "system": system, "messages": messages}
        effort = effort or self.cfg.get("effort")
        if effort:
            kwargs["output_config"] = {"effort": effort}
        try:
            if self.use_fallback:
                resp = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except TypeError as e:
            if "authentication method" not in str(e):
                raise
            env = self.cfg.get("api_key_env") or "ANTHROPIC_API_KEY"
            raise LLMError(f"no API key: set {env} (environment or .env), or put api_key in agents.json") from e
        except anthropic.AuthenticationError as e:
            raise LLMError(f"authentication failed - check the API key ({e.message})") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"model or endpoint not found: {self.model} @ {self.base_url} ({e.message})") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limited ({e.message})") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"cannot reach {self.base_url or 'api.anthropic.com'}: {e}") from e

        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            raise LLMError(f"request declined by the model ({getattr(details, 'category', None)})")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if resp.stop_reason == "max_tokens":
            text += "\n\n[truncated: reached max_tokens]"
        return text

    def _openai(self, system, messages, max_tokens):
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}] + messages,
            )
        except openai.AuthenticationError as e:
            raise LLMError(f"authentication failed - check the API key ({e})") from e
        except openai.NotFoundError as e:
            raise LLMError(f"model or endpoint not found: {self.model} @ {self.base_url} ({e})") from e
        except openai.RateLimitError as e:
            raise LLMError(f"rate limited ({e})") from e
        except openai.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e}") from e
        except openai.APIConnectionError as e:
            raise LLMError(f"cannot reach {self.base_url}: {e}") from e

        if not resp.choices:
            raise LLMError("endpoint returned no choices")
        choice = resp.choices[0]
        text = (choice.message.content or "").strip()
        if choice.finish_reason == "length":
            text += "\n\n[truncated: reached max_tokens]"
        return text
