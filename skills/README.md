# Skills

A skill listed in an agent's `skills` array in `agents.json` always appears on its card and in its
system prompt by name. To give the skill real instructions, add a Markdown file here named after the
skill in lowercase with dashes: `Python` -> `python.md`, `Unit Tests` -> `unit-tests.md`,
`CI/CD` -> `ci-cd.md`. Its contents are added to the system prompt of every agent that has the skill.
