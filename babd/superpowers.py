"""Superpowers skills (https://github.com/obra/superpowers), vendored in skills/superpowers and run locally.

Each agent gets the skills that fit its role (`superpowers` in agents.json, DEFAULT_ASSIGNMENT below:
the skills recommended for it). How they are always used is in babd/skillpacks.py.
"""
from . import skillpacks

# Which skills each agent needs: shown as recommended, and used when agents.json has no list for the agent.
DEFAULT_ASSIGNMENT = {
    "lead": ["using-superpowers", "brainstorming", "writing-plans", "subagent-driven-development",
             "dispatching-parallel-agents", "requesting-code-review", "verification-before-completion",
             "finishing-a-development-branch", "diagnosing-superpowers", "writing-skills"],
    "architect": ["using-superpowers", "brainstorming", "writing-plans", "dispatching-parallel-agents"],
    "developer": ["using-superpowers", "test-driven-development", "executing-plans", "systematic-debugging",
                  "receiving-code-review", "verification-before-completion", "using-git-worktrees"],
    "qa": ["using-superpowers", "test-driven-development", "systematic-debugging", "requesting-code-review",
           "verification-before-completion"],
    "devops": ["using-superpowers", "verification-before-completion", "finishing-a-development-branch",
               "using-git-worktrees", "systematic-debugging"],
}

# Which skills apply to which step of the team flow (a step uses those the agent has).
STEP_SKILLS = {
    "plan": ["brainstorming", "writing-plans", "subagent-driven-development", "dispatching-parallel-agents"],
    "design": ["brainstorming", "writing-plans"],
    "code": ["test-driven-development", "executing-plans", "using-git-worktrees", "verification-before-completion"],
    "test_report": ["test-driven-development", "systematic-debugging", "requesting-code-review",
                    "verification-before-completion"],
    "fix": ["systematic-debugging", "receiving-code-review", "test-driven-development",
            "verification-before-completion"],
    "deploy_report": ["verification-before-completion", "finishing-a-development-branch", "using-git-worktrees"],
    "report": ["verification-before-completion", "finishing-a-development-branch"],
    "report_blocked": ["verification-before-completion", "diagnosing-superpowers"],
}

WHY = {  # one line per agent/skill pair, shown in the dashboard
    "using-superpowers": "the rule: check for and use a matching skill before any action",
    "brainstorming": "clarify intent, constraints and alternatives before any design or code",
    "writing-plans": "turn the design into bite-sized, testable tasks with exact files and tests",
    "subagent-driven-development": "hand each task to the right agent with a precise brief, review each result",
    "dispatching-parallel-agents": "split independent work so it can proceed in parallel",
    "requesting-code-review": "review work against the requirements, issues by severity",
    "receiving-code-review": "verify review findings technically before changing code",
    "test-driven-development": "red-green-refactor: a failing test before any production code",
    "systematic-debugging": "root cause first, no fixes by guessing",
    "verification-before-completion": "no success claim without fresh evidence",
    "executing-plans": "execute the plan task by task, each proven by a test",
    "using-git-worktrees": "work in an isolated workspace / branch",
    "finishing-a-development-branch": "tests green, then merge / PR / keep / discard",
    "diagnosing-superpowers": "find out with evidence why a run went wrong",
    "writing-skills": "create or edit team skills, tested like code",
}

PLAIN = {  # what the skill does for you, in plain words (shown to people new to this)
    "using-superpowers": "Makes the agent check its skills before every action, so it never skips them.",
    "brainstorming": "Thinks through what you really want and the options before building anything.",
    "writing-plans": "Writes a clear step-by-step plan that anyone on the team can follow.",
    "subagent-driven-development": "Gives each piece of work to the right agent with clear instructions, then checks it.",
    "dispatching-parallel-agents": "Splits work that does not depend on each other so it can be done at the same time.",
    "requesting-code-review": "Has the work checked against what was asked, with problems sorted by how serious they are.",
    "receiving-code-review": "Checks review comments are really right before changing the code.",
    "test-driven-development": "Writes a test first, then the code: fewer bugs reach you.",
    "systematic-debugging": "Finds the real cause of a bug instead of guessing at fixes.",
    "verification-before-completion": "Never says \"done\" without proof: test output, logs, a health check.",
    "executing-plans": "Builds the plan one small, tested step at a time.",
    "using-git-worktrees": "Works in a separate copy of the code so the main version stays safe.",
    "finishing-a-development-branch": "Closes the work properly: tests green, then merge, pull request or discard.",
    "diagnosing-superpowers": "When a run goes wrong, finds out why with evidence.",
    "writing-skills": "Writes and improves the team's own skills, tested like code.",
}

PACK = skillpacks.Pack("superpowers", "Superpowers", "obra/superpowers", "https://github.com/obra/superpowers",
                       DEFAULT_ASSIGNMENT, STEP_SKILLS, WHY, PLAIN)
SKILLS_DIR = PACK.dir
SuperpowersError = skillpacks.SkillError
skill_names = PACK.skill_names
load = PACK.load
catalog = PACK.catalog
assigned = PACK.assigned
enabled = PACK.enabled
for_step = PACK.for_step
missing = skillpacks.missing
step_block = skillpacks.step_block
install_native = skillpacks.install_native


def system_section(agent_cfg):
    return skillpacks.system_section({"superpowers": assigned(agent_cfg)})
