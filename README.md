# AI Software Development Workspace

A flat 2D vector template of an AI software company: one human CEO supervises a team of 5 AI agents.

![AI Software Development Workspace](workspace.png)

## Files

| File | Description |
| --- | --- |
| `workspace.svg` | The illustration as a scalable vector (1920×1200) |
| `workspace.png` | The same image rendered as a PNG |
| `agents.json` | **Configuration** for each agent (LLM, Telegram bot, skills, tasks, status) and for the CEO dashboard |
| `generate_workspace.py` | Script that reads `agents.json` and writes `workspace.svg` |

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
| `llm.base_url` | API endpoint URL. Any endpoint works, e.g. `https://api.anthropic.com/v1` or a self-hosted OpenAI-compatible server such as `http://localhost:11434/v1` |
| `llm.model` | Model name/ID sent to that endpoint |
| `llm.api_key_env` | *(recommended)* Name of the environment variable that holds the API key |
| `llm.api_key` | *(alternative)* The API key itself. The image only ever shows it masked (`sk-•••wxyz`) |
| `telegram.enabled` | Telegram bot gateway on/off (green dot = connected, grey = off) |
| `telegram.bot_username` | The agent's bot username (from @BotFather) |
| `telegram.token_env` | Name of the environment variable that holds the bot token |
| `skills` | List of skills. Add an item to give the agent a new skill |

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
