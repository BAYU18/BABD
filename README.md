# AI Software Development Workspace

An AI software company: one human CEO supervises a team of 5 AI agents. Each agent runs on its own
harness (direct API, Hermes Agent, Claude Code, …) with its own LLM (Claude or any OpenAI-compatible
endpoint), the agents work through a fixed CEO → Team Lead → specialists flow, and a web dashboard
lets the CEO configure, command and watch them. `agents.json` drives all of it, including the
workspace illustration.

![AI Software Development Workspace](workspace.png)

## Install

```bash
git clone https://github.com/bayu18/babd.git && cd babd
./install.sh
```

`install.sh` (Linux / macOS; on Windows use WSL) needs only Python 3.10+. It:

1. creates `.venv` and installs BABD with its Python dependencies (`anthropic`, `openai`);
2. creates `.env` (file mode 600) for API keys;
3. installs **GBrain** (the team memory: Bun 1.4+ from GitHub releases, checksum-verified, and the
   gbrain source) and creates a local brain in `.babd/gbrain`;
4. installs and configures the harness of every agent in `agents.json`: Hermes Agent into its own
   virtualenv, Claude Code with npm (BABD downloads Node.js itself, checksum-verified, when npm is
   missing), and a per-agent config for each.

Re-running it is safe. Everything BABD installs stays inside the project (`.venv/`, `.babd/`).

## Dashboard

```bash
.venv/bin/babd dashboard
```

Opens the CEO command center in your browser (`http://127.0.0.1:8800/?token=…`).

![BABD dashboard](docs/dashboard.png)

- **Animated agents**: each card has its robot at its workstation, moving with what the agent is
  really doing: idle (breathing, blinking, "z z z", a screensaver), working (typing, code scrolling on
  the monitor, sparks), waiting (head tilt, "…" bubble, hourglass), blocked (shake, red alert),
  setting up (progress bar), plus a GBrain badge with ↓ / ↑ when it reads or writes memory. Turned
  off automatically when the system asks for reduced motion.

  ![Agent animations: idle, working, waiting, blocked, setting up](docs/agent-states.gif)
- **Give the team a goal** and watch the run live: the stage stepper, every message between the
  agents, and the CEO report at the end.
- **Approve or reject the deploy** when QA has passed (or tick "approve automatically").
- **Configure each agent**: role and tasks, LLM (provider, API style, base URL, model, effort,
  API key), harness and its options, Telegram, skills. Saving writes `agents.json`, redraws the
  workspace image, and **Save & set up** installs and configures the harness right away.
  API keys typed here go to `.env` under the agent's key variable, never to `agents.json`, and
  are never sent back to the browser.
- **Chat with one agent** directly through its harness.
- **Check agents** (send each a short test message), **Set up all**, team settings (project name,
  CEO approval before deploy, QA fix rounds), run history, and an activity log with install output.

The panel listens on 127.0.0.1 only. Every API call needs the token from the start-up URL, and the
Host header must be the panel's own address, so other web pages can't drive it.

## Team memory: GBrain

Every agent has the **GBrain** skill ([garrytan/gbrain](https://github.com/garrytan/gbrain)) and
uses it on every task, enforced by BABD around each step rather than left to the model:

```
read  gbrain recall  (keywords of the goal + the task)  ->  "Team memory (gbrain)" at the top of the prompt
work  the agent does the task with that memory
write gbrain put     babd/runs/<run>/<nn>-<agent>-<kind>   (the agent's full output as a page)
      gbrain remember "<one-line fact>" --entity babd/goals/<goal> --provenance "babd run <run> · <agent> · <kind>"
```

This holds for every step of a team run (plan, design, code, test, fix, deploy, report) and for
direct chats. So the next agent, and the next run, starts from what the team already decided: a new
goal's plan reads the earlier designs, QA verdicts and CEO reports. Agents with tools (Hermes, Claude
Code) also get the `gbrain` command and `GBRAIN_HOME` to search or save more themselves; the skill's
instructions are in `skills/gbrain.md`.

It runs **locally and keyless**: a PGLite brain (embedded Postgres, no server, no Docker) with keyword
search and no embeddings. BABD strips cloud API keys from gbrain's environment, including when an
agent calls `gbrain` itself, so no memory text leaves the machine (`allow_cloud: true` changes that).

| `project.gbrain` | Meaning |
| --- | --- |
| `enabled` | Read before / write after every agent step (default `true`) |
| `strict` | A failed gbrain read or write stops that step with a clear error (default `true`). `false`: carry on without memory |
| `allow_cloud` | Pass cloud API keys to gbrain, e.g. for embeddings or fact extraction (default `false`) |
| `home` | Where the brain lives (default `.babd/gbrain`, i.e. `GBRAIN_HOME`) |
| `ref` | gbrain git ref to install (default `latest-stable`) |
| `budget_tokens` | How much memory one recall may put in a prompt (default 1200) |
| `command` | Use an existing `gbrain` program instead of installing one |

```bash
babd brain                     # status
babd brain login lockout       # what the team knows about these words
```

The dashboard shows each read and write in the run timeline, has a **Team memory** search, a GBrain
status in the top bar, and the GBrain settings under Team settings.

## How the agents talk to each other

```
CEO ──goal──▶ Team Lead ──plan──┐
                                ├─▶ Architect ──design──▶ Team Lead
                                ├─▶ Developer ──code────▶ Team Lead
                                ├─▶ QA ──test report + VERDICT──▶ Team Lead
                                │      FAIL: Team Lead ─▶ Developer (fix) ─▶ Team Lead ─▶ QA (re-test)
                                │            … up to max_fix_rounds, then the run is BLOCKED
Team Lead ──approval request──▶ CEO ──approve / reject──▶ Team Lead       (require_approval: deploy)
                                └─▶ DevOps ──deploy + monitoring──▶ Team Lead   (only after PASS + approval)
Team Lead ──report──▶ CEO
```

- The Team Lead is the hub: specialists only talk to the Team Lead, and only the Team Lead talks to
  the CEO. Any other route is refused (`babd/flow.py`, `MessageBus`).
- Each agent gets the work it builds on: the Developer gets the design, QA gets design + code,
  DevOps gets code + QA report + the CEO's approval note.
- QA must end with `VERDICT: PASS` or `VERDICT: FAIL`; a missing verdict counts as FAIL.
- The report's status, progress, approvals and blockers are computed from what happened (QA verdict,
  approval, deploy), not taken from the model.
- Every message is saved in `runs/<id>/messages.jsonl`, with `state.json` and one file per step.

## Files

| File | Description |
| --- | --- |
| `install.sh` | One-command install (see above) |
| `workspace.svg` | The illustration as a scalable vector (1920×1630) |
| `workspace.png` | The same image rendered as a PNG |
| `agents.json` | **Configuration** for each agent (LLM, harness, Telegram bot, skills, tasks, status) and for the CEO dashboard and flow |
| `generate_workspace.py` | Script that reads `agents.json` and writes `workspace.svg` |
| `babd/` | The runtime: LLM clients, harnesses (`harness/`), team flow (`flow.py`), team memory (`gbrain.py`), dashboard (`dashboard/`) and the command line |
| `skills/` | Optional instruction files for skills (see `skills/README.md`) |
| `tests/` | Tests: GBrain read/write around every step (fake gbrain CLI), the flow with scripted agents, the dashboard API over HTTP, real HTTP calls through both SDKs to a mock LLM server, and fake `hermes` / `claude` CLIs |

## Command line

```bash
source .venv/bin/activate        # or prefix the commands with .venv/bin/

babd dashboard                                # web panel
babd check                                    # ping every agent through its harness + LLM
babd harnesses                                # list harness types
babd use qa hermes_local                      # pick a harness: installs + configures it
babd setup                                    # install + configure every agent's harness
babd ask developer "Write a function that validates email addresses"
babd chat architect                           # interactive multi-turn chat
babd run "Build a login page with email + password" --update-dashboard [--approve]
```

`run` follows the flow above and prints each message as it is sent. The CEO approval is asked in
the terminal (or given up front with `--approve`). With `--update-dashboard`, the result is written
into `agents.json` (project status, workflow strip, agent states) and `workspace.svg` is redrawn.

Each agent uses its own harness and its own LLM. Its system prompt is built from its main task,
sub-tasks and skills.

| `project` setting | Meaning |
| --- | --- |
| `require_approval` | `["deploy"]` (default): the CEO must approve before DevOps deploys. `[]`: no approval step |
| `max_fix_rounds` | How many times a failed QA report goes back to the Developer (default 2) |

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
| `hermes_gateway` | A Hermes API server: `POST /v1/runs`, poll `GET /v1/runs/{id}` | No `api_base_url`: BABD starts a private gateway for the agent on 127.0.0.1 with the agent's LLM in its `config.yaml` and a generated key, and stops it on exit. With `api_base_url`: that server's own model is used (`send_model: true` also sends `llm.model`) |
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
| `home` / `manage_config` | hermes_local, hermes_gateway | Use another `HERMES_HOME`; `manage_config: false` stops BABD from writing its config.yaml |
| `version` | hermes_*, claude_local | Pin the version BABD installs (e.g. `"0.19.0"`) |
| `auto_install` | hermes_*, claude_local | `false` = never install, report what is missing instead |
| `command` | CLI harnesses | Use this program instead of finding / installing one |
| `isolated_config`, `config_dir` | claude_local | Private Claude Code config dir per agent (default: on when the agent has its own key) |
| `api_base_url`, `api_key_env`, `port` | hermes_gateway | Use an existing server, or fix the port of the auto-started one |
| `install` | process | Command run once to install the program (re-run when it changes) |
| `yolo` | hermes_local | Skip Hermes' approval prompts for dangerous commands. **Off by default**: without a terminal those prompts can only deny, so turn it on only inside a sandbox (container/VM) |
| `dangerously_skip_permissions` | claude_local | Same for Claude Code. **Off by default** |
| `env`, `extra_args` | CLI harnesses | Extra environment variables / command-line arguments |

### Automatic install and configuration

Selecting a harness is enough: BABD installs what it needs and writes its configuration.

```bash
babd use architect hermes_local --set max_turns=50 --set 'toolsets=["web","file"]'
babd use developer claude_local
babd use devops hermes_gateway
babd setup            # (re)install + configure all agents, e.g. after editing agents.json
```

`use` writes the harness into `agents.json` (starting from that harness's defaults, plus any `--set`),
redraws `workspace.svg`, then runs setup for that agent. The same setup also runs automatically
before an agent's first task, so editing `agents.json` by hand works too.

| Harness | Installed automatically | Configured automatically |
| --- | --- | --- |
| `direct` | the `anthropic` / `openai` SDK into the current Python, if missing | SDK client from `llm` |
| `hermes_local` | `hermes-agent` (+ `aiohttp`) in its own virtualenv: `.babd/tools/hermes/` | `.babd/hermes/<agent>/config.yaml` from `llm`, rewritten before every run |
| `hermes_gateway` | same Hermes install | `.babd/hermes-gateway/<agent>/`: config.yaml, generated 64-char API key (file mode 600), gateway started on a free local port |
| `claude_local` | `@anthropic-ai/claude-code` with npm into `.babd/tools/claude-code/` (needs Node.js) | `.babd/claude/<agent>/` config dir + endpoint, key and model env vars |
| `process` | your `install` command, once | LLM settings as env vars |

A program already on your PATH is used as-is unless you pin a `version`. When the agent has its own
API key, BABD sets that agent's endpoint and key explicitly and clears inherited `ANTHROPIC_AUTH_TOKEN`,
`CLAUDE_CODE_OAUTH_TOKEN` and Bedrock/Vertex switches, so another login on the machine can't take over.
Without its own key, the agent uses the machine's existing Claude login.

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
