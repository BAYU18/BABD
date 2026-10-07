# AI Software Development Workspace

An AI software company: one human CEO supervises a team of 5 AI agents. Each agent calls a real LLM
(Claude or any OpenAI-compatible endpoint) configured in `agents.json`, and the same file drives the
workspace illustration.

![AI Software Development Workspace](workspace.png)

## Files

| File | Description |
| --- | --- |
| `workspace.svg` | The illustration as a scalable vector (1920×1566) |
| `workspace.png` | The same image rendered as a PNG |
| `agents.json` | **Configuration** for each agent (LLM, Telegram bot, skills, tasks, status) and for the CEO dashboard |
| `generate_workspace.py` | Script that reads `agents.json` and writes `workspace.svg` |
| `babd/` | The team runtime: LLM clients, harnesses (`babd/harness/`), agents, Team Lead orchestration and the command line |
| `skills/` | Optional instruction files for skills (see `skills/README.md`) |
| `tests/` | Tests: real HTTP calls through both SDKs to a mock LLM server, and fake `hermes` / `claude` CLIs that record what each harness sends |

## Running the team

```bash
pip install -r requirements.txt
cp .env.example .env              # then fill in ANTHROPIC_API_KEY (and others you use)

python -m babd check                              # ping every agent through its harness + LLM
python -m babd harnesses                          # list harness types
python -m babd ask developer "Write a function that validates email addresses"
python -m babd chat architect                     # interactive multi-turn chat
python -m babd run "Build a login page with email + password" --update-dashboard
```

`run` does what the illustration shows:

1. **Team Lead** plans the work and assigns one task to each specialist.
2. **Architect → Developer → QA / Tester → DevOps** each do their task in order. Each one sees the
   plan and everything the previous agents produced.
3. **Team Lead** writes a CEO report: status, progress, active task, approvals, blockers, next action.

Everything is saved under `runs/<timestamp>/` (`01-plan.md`, one file per agent, `99-ceo-report.json`).
With `--update-dashboard`, the report is written into `project` in `agents.json` and `workspace.svg`
is regenerated, so the CEO Dashboard shows the real result.

Each agent uses its own harness and its own LLM. Its system prompt is built from its main task,
sub-tasks and skills.

## Harnesses

A harness is the program that runs an agent: a plain API call, or a full agent (Hermes, Claude Code)
with tools such as a terminal, files and web. Each agent picks one with `"harness"` in `agents.json`
(no `harness` means `direct`).
Whatever the harness, the agent keeps **its own custom LLM** (`llm` block): the harness gets the
agent's URL, key and model in the form it understands. The design follows the adapters in
[Paperclip](https://github.com/paperclipai/paperclip) (`packages/adapters/*`,
`server/src/services/ai-provider-routing.ts`).

| `harness.type` | Runs | How the agent's `llm` reaches it |
| --- | --- | --- |
| `direct` | One API call (Anthropic SDK or OpenAI-compatible SDK). No tools | SDK client with `base_url`, key, `model` |
| `hermes_local` | [Hermes Agent](https://github.com/NousResearch/hermes-agent) CLI: `hermes chat -q … -Q` | A private `HERMES_HOME` per agent (`.babd/hermes/<agent>/config.yaml`): `provider: custom` + `base_url` + `model` for OpenAI-compatible endpoints, `provider: anthropic` for Claude. The key stays in an env var; config.yaml only references `${OPENAI_API_KEY}` |
| `hermes_gateway` | A running Hermes API server: `POST /v1/runs`, poll `GET /v1/runs/{id}` | The model is set on the Hermes server (`send_model: true` also sends `llm.model`) |
| `claude_local` | Claude Code CLI: `claude --print --output-format json` | `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` + `--model`, `--effort`. Needs an Anthropic-compatible endpoint |
| `process` | Any command: prompt on stdin, reply on stdout | Env vars `BABD_LLM_BASE_URL`, `BABD_LLM_MODEL`, `BABD_LLM_API_KEY` (+ `OPENAI_*` or `ANTHROPIC_*`) |

Examples (the shipped `agents.json` uses `direct`, `hermes_local` and `claude_local`):

```json
"llm": {"provider": "Custom", "api": "openai", "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder:7b", "api_key_env": "LOCAL_LLM_API_KEY"},
"harness": {"type": "hermes_local", "toolsets": ["terminal", "file"], "max_turns": 30,
            "timeout_sec": 1200, "yolo": false}
```
```json
"harness": {"type": "claude_local", "max_turns": 40, "dangerously_skip_permissions": false}
```
```json
"harness": {"type": "hermes_gateway", "api_base_url": "http://127.0.0.1:8642",
            "api_key_env": "HERMES_GATEWAY_API_KEY"}
```
```json
"harness": {"type": "process", "command": "my-agent", "args": ["--model", "{model}"]}
```

| Harness option | Applies to | Meaning |
| --- | --- | --- |
| `toolsets` | hermes_local | Hermes toolsets to enable (`-t`), e.g. `terminal`, `file`, `web` |
| `skills` | hermes_local | Hermes-native skills to preload (`-s`) |
| `max_turns` | hermes_local, claude_local | Limit on tool-calling iterations |
| `timeout_sec` | CLI harnesses, gateway | Stop the run after this many seconds (default 1800) |
| `cwd` | CLI harnesses | Working directory. Default `workspace/`, shared by the agents so QA sees the Developer's files |
| `home` / `manage_config` | hermes_local | Use another `HERMES_HOME`; `manage_config: false` stops BABD from writing its config.yaml |
| `yolo` | hermes_local | Skip Hermes' approval prompts for dangerous commands. **Off by default**: without a terminal those prompts can only deny, so turn it on only inside a sandbox (container/VM) |
| `dangerously_skip_permissions` | claude_local | Same for Claude Code. **Off by default** |
| `env`, `extra_args` | CLI harnesses | Extra environment variables / command-line arguments |

Install the harnesses you use: `pip install hermes-agent` for Hermes; Claude Code from
https://claude.com/claude-code. `python -m babd check` says which ones are missing.

## Structure

```
Human CEO → CEO Dashboard → Team Lead / Orchestrator → Architect · Developer · QA / Tester · DevOps
```

Each agent card shows **AGENT NAME → MAIN TASK (large, bold) → 3 SUB-TASKS (checklist)**.
The CEO Dashboard shows only high-level information: status, progress, goal, active task,
agent status, approvals, blockers, recent result and next action.

The workflow strip at the bottom shows the development steps: PLAN → DESIGN → CODE → TEST → DEPLOY → MONITOR.

## Agent configuration (`agents.json`)

Each agent has an **AGENT CONFIG** section on its card, filled from `agents.json`:

```json
{
  "id": "developer",
  "llm": {
    "provider": "Custom",
    "api": "openai",
    "base_url": "http://localhost:11434/v1",
    "model": "qwen2.5-coder:7b",
    "api_key_env": "LOCAL_LLM_API_KEY"
  },
  "telegram": {
    "enabled": true,
    "bot_username": "@babd_dev_bot",
    "token_env": "TELEGRAM_DEV_BOT_TOKEN"
  },
  "skills": ["Python", "TypeScript", "Git"]
}
```

| Field | What it controls |
| --- | --- |
| `llm.provider` | Provider name shown on the card (e.g. `Anthropic`, `Custom`) |
| `llm.api` | API style: `anthropic` (Claude, via the Anthropic SDK) or `openai` (any OpenAI-compatible server: Ollama, vLLM, LM Studio, OpenRouter, ...). Defaults to `anthropic` when `provider` is `Anthropic`, else `openai` |
| `llm.base_url` | API endpoint URL, e.g. `https://api.anthropic.com` or `http://localhost:11434/v1` |
| `llm.model` | Model name/ID sent to that endpoint |
| `llm.api_key_env` | *(recommended)* Name of the environment variable that holds the API key |
| `llm.api_key` | *(alternative)* The API key itself. The image only ever shows it masked (`sk-•••wxyz`) |
| `llm.effort` | *(Claude only, optional)* `low` / `medium` / `high` / `xhigh` / `max`: how much the model thinks |
| `llm.max_tokens` | *(optional)* Reply length limit. Default 16000 for Claude, 4096 for OpenAI-compatible |
| `llm.refusal_fallback` | *(Claude only, default `true`)* If the model declines a request, the Claude API retries it on a fallback model. Only used with `api.anthropic.com` |
| `telegram.enabled` | Telegram bot gateway on/off (green dot = connected, grey = off) |
| `telegram.bot_username` | The agent's bot username (from @BotFather) |
| `telegram.token_env` | Name of the environment variable that holds the bot token |
| `skills` | List of skills, added to the agent's system prompt. Add `skills/<name>.md` to give a skill real instructions |

`project.ceo_telegram` configures the CEO's own Telegram bot, which receives
approvals, blockers and reports (`notify`).

The dashboard's **TEAM SETUP** numbers (LLMs connected, Telegram bots, number of skills)
and **AGENT STATUS** are calculated from this file automatically.

> Prefer `api_key_env` over `api_key`. If you do write a real key with `api_key`,
> do not commit `agents.json` to a public repository. The LLM status dot is green
> only when `base_url`, `model` and a key are all set; a missing key shows `KEY not set` in red.

## Regenerate

```bash
python3 generate_workspace.py   # reads agents.json, writes workspace.svg
```
