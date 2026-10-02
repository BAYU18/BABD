# AI Software Development Workspace

A flat 2D vector template of an AI software company: one human CEO supervises a team of 5 AI agents.

![AI Software Development Workspace](workspace.png)

## Files

| File | Description |
| --- | --- |
| `workspace.svg` | The illustration as a scalable vector (1920×1200) |
| `workspace.png` | The same image rendered as a PNG |
| `generate_workspace.py` | Script that builds the SVG. Edit its labels, colors and statuses, then run it again |

## Structure

```
Human CEO → CEO Dashboard → Team Lead / Orchestrator → Architect · Developer · QA / Tester · DevOps
```

Each agent card shows **AGENT NAME → MAIN TASK (large, bold) → 3 SUB-TASKS (checklist)**.
The CEO Dashboard shows only high-level information: status, progress, goal, active task,
agent status, approvals, blockers, recent result and next action.

The workflow strip at the bottom shows the development steps: PLAN → DESIGN → CODE → TEST → DEPLOY → MONITOR.

## Regenerate

```bash
python3 generate_workspace.py   # writes workspace.svg
```
