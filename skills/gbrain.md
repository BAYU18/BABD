You share one team memory, GBrain (https://github.com/garrytan/gbrain), running locally on this machine.
Every task follows the same cycle:

1. **Read first.** Before you start, BABD searches GBrain for the goal and your task and puts what it
   finds at the top of your prompt under "Team memory (gbrain)". Read it before anything else.
   Follow earlier decisions (designs, conventions, fixed bugs, CEO approvals) unless your task says
   otherwise, and say explicitly when you deviate and why. If it says nothing was found, you are the
   first to work on this.
2. **Work.** Do the task.
3. **Write when done.** BABD saves your full answer to GBrain as a page and a one-line fact with you
   as the source. So finish with what the next agent should know: decisions taken, what you changed,
   open problems. Keep it factual; never put secrets (keys, tokens, passwords) in your answer.

If you can run commands (Hermes, Claude Code), the `gbrain` command is on your PATH and already points
at the team brain (GBRAIN_HOME). Use it for more than the automatic read/write:

- search deeper: `gbrain recall --query "login or lockout" --budget-tokens 800 --json`
  (keyword search: join a few distinctive words with `or`)
- read a page: `gbrain get <slug>`
- save an extra fact: `gbrain remember "<one fact>" --entity babd/goals/<goal-slug> --provenance "<you>, <why>" --json`

Never delete or overwrite other agents' pages.
