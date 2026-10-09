"""Matt Pocock's skills (https://github.com/mattpocock/skills), vendored in skills/mattpocock and run locally.

Each agent gets the skills that fit its role (`mattpocock` in agents.json, RECOMMENDED below). Skills no
agent needs by default are listed in OPTIONAL with the reason; they stay available to tick in the
dashboard. How the skills are always used is in babd/skillpacks.py.
"""
from . import skillpacks

# Which skills each agent needs: shown as recommended, and used when agents.json has no list for the agent.
RECOMMENDED = {
    "lead": ["grilling", "to-spec", "to-tickets", "implement-spec", "triage", "wayfinder", "chief-of-staff",
             "handoff", "to-questionnaire", "wait-what", "retro", "writing-for-agents", "ask-matt"],
    "architect": ["grilling", "domain-modeling", "codebase-design", "improve-codebase-architecture", "prototype",
                  "research", "to-spec"],
    "developer": ["implement", "tdd", "codebase-design", "diagnosing-bugs", "prototype", "pr", "research"],
    "qa": ["tdd", "code-review", "diagnosing-bugs", "triage"],
    "devops": ["wizard", "diagnosing-bugs", "pr", "setup-pre-commit"],
    "researcher": ["research", "domain-modeling", "handoff"],
}

# Which skills apply to which step of the team flow (a step uses those the agent has).
STEP_SKILLS = {
    "plan": ["grilling", "to-spec", "to-tickets"],
    "design": ["domain-modeling", "codebase-design", "grilling"],
    "code": ["implement", "tdd", "codebase-design"],
    "test_report": ["code-review", "tdd", "diagnosing-bugs"],
    "fix": ["diagnosing-bugs", "tdd"],
    "test_plan": ["tdd"],
    "deploy_prep": ["wizard", "setup-pre-commit"],
    "deploy_report": ["wizard", "pr"],
    "report": ["wait-what", "retro"],
    "report_blocked": ["wait-what", "retro", "to-questionnaire"],
}

WHY = {  # one technical line per skill
    "ask-matt": "router over the skills: which flow fits the situation",
    "code-review": "two-axis review of the diff: Standards (incl. Fowler smells) and Spec",
    "codebase-design": "deep modules: small interface, clean seam, testable through the interface",
    "diagnosing-bugs": "build a tight red-capable feedback loop, minimise, ranked hypotheses, regression test",
    "domain-modeling": "sharpen terms into GLOSSARY.md, record hard-to-reverse decisions as ADRs",
    "grilling": "interview in rounds over the design tree, a recommended answer for each question",
    "implement": "build from the spec or tickets with tdd, then code-review",
    "implement-spec": "work the tickets as a task graph, frontier in parallel, one integration branch",
    "improve-codebase-architecture": "find shallow modules and propose deepening refactors",
    "pr": "PR body: smallest visual summary, before/after evidence, merge danger",
    "prototype": "throwaway code that answers one design question (logic or UI)",
    "research": "investigate against primary sources, findings in one cited Markdown file",
    "retro": "after the run: improve the environment (checks, standards, navigation, tooling)",
    "to-spec": "turn what is known into a spec: problem, user stories, decisions, testing, out of scope",
    "to-tickets": "split work into tracer-bullet vertical slices with blocking edges",
    "triage": "move issues through triage roles, verify claims, write agent-ready briefs",
    "wayfinder": "plan work too big for one session as a map of decision tickets",
    "wizard": "a bash wizard that walks a human through manual steps (credentials, infra, cutover)",
    "chief-of-staff": "pursue a long goal by coordinating agents, tactical and strategic",
    "handoff": "compact the work into a handoff document for the next agent",
    "to-questionnaire": "turn an open decision into questions for the person who knows",
    "wait-what": "re-pitch in Simplified Technical English with the project's own words",
    "writing-for-agents": "write skills and agent docs that make agents behave predictably",
    "setup-pre-commit": "pre-commit hooks: formatting, type check and tests before every commit",
    "tdd": "red-green in vertical slices, tests only at agreed seams, no tautological tests",
}

PLAIN = {  # what the skill does for you, in plain words (shown to people new to this)
    "ask-matt": "Picks the right working method for the situation.",
    "code-review": "Checks the code two ways: is it written well, and does it do what was asked.",
    "codebase-design": "Keeps the code simple to use and easy to test, so changes stay cheap.",
    "diagnosing-bugs": "Reproduces a bug reliably first, then finds and fixes its real cause.",
    "domain-modeling": "Agrees on clear names for things and writes down important decisions.",
    "grilling": "Asks the hard questions early, each with a suggested answer, so nothing is assumed.",
    "implement": "Builds the feature from the spec, test first, then reviews it.",
    "implement-spec": "Runs the build of a whole spec, ticket by ticket, in the right order.",
    "improve-codebase-architecture": "Spots parts of the code that are hard to change and proposes fixes.",
    "pr": "Writes a clear change summary: what changed, proof it works, how risky it is.",
    "prototype": "Builds a quick throwaway version to answer a design question before the real build.",
    "research": "Looks things up in official sources and writes down the findings with links.",
    "retro": "After the work, suggests how the team can do better next time.",
    "to-spec": "Turns the idea into a clear spec: the problem, user stories, decisions and tests.",
    "to-tickets": "Cuts the work into small tasks, each one working end to end, in the right order.",
    "triage": "Sorts bug reports and requests: what they are, if they are real, what to do next.",
    "wayfinder": "Charts a route for a very big project, one decision at a time.",
    "wizard": "Writes a step-by-step script for setup steps only a person can do (accounts, keys).",
    "chief-of-staff": "Keeps a long project on track and improves how the team works.",
    "handoff": "Writes a short handover note so the next agent can carry on.",
    "to-questionnaire": "Turns an open question into a short questionnaire for the right person.",
    "wait-what": "Explains things again in simple words when a message is unclear.",
    "writing-for-agents": "Writes instructions for AI agents that they follow reliably.",
    "setup-pre-commit": "Adds automatic checks that run before every code save to the repository.",
    "tdd": "Writes one test, then just enough code to pass it, one small piece at a time.",
}

OPTIONAL = {  # vendored and available to tick, but no agent gets them by default
    "grill-me": "shortcut that only runs grilling (agents already have grilling)",
    "grill-with-docs": "shortcut that only runs grilling + domain-modeling (both already given)",
    "setup-matt-pocock-skills": "BABD already does this setup (see skills/mattpocock/ADAPTATION.md)",
    "claude-handoff": "starts a background Claude Code session; BABD routes work itself",
    "git-guardrails-claude-code": "installs Claude Code hooks on a machine; set up by hand if wanted",
    "setup-ts-deep-modules": "TypeScript monorepos only",
    "migrate-to-shoehorn": "TypeScript test code only",
    "scaffold-exercises": "for writing course exercises, not software delivery",
    "teach": "for teaching a person a topic",
    "loop-me": "for specifying personal workflows",
    "writing-beats": "for writing articles",
    "writing-fragments": "for writing articles",
    "writing-shape": "for writing articles",
}

PACK = skillpacks.Pack("mattpocock", "Matt Pocock's skills", "mattpocock/skills", "https://github.com/mattpocock/skills",
                       RECOMMENDED, STEP_SKILLS, WHY, PLAIN, OPTIONAL)
