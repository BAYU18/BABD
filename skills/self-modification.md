You can change BABD itself - the code the team runs on. This is powerful and gated. Follow these rules.

## How self-modification works

BABD's own code lives in a project called **babd-self** (its repository is BABD). You never edit the
running installation in place. A task on that project runs in an isolated git worktree:

    workspace/worktrees/babd-self/<run id>/

That is a full copy of the BABD code. You read it, edit it, and run its tests there. The installation
you are running from (`babd/`, `agents.json`, `.env`, `.git`) is **off limits** to your tools - the
deny rules block it on purpose, so a mistake can never take the team down mid-run.

## The flow

1. **Read the real code.** The worktree is the source of truth for this task. Read the module you are
   changing and the tests next to it (`tests/test_<module>.py`) before touching anything.
2. **Change the smallest thing.** One behaviour per change, the way the rest of the code is written.
3. **Test in the worktree.** Run `python -m pytest -q` (or the project's `test_command`). A change to
   BABD with no passing test is not done - QA will run the same command and a failure fails the task.
4. **Say what you changed.** Finish with: files touched, why, the test command you ran and its real
   output, and any risk for the next agent.

## Reaching the installation (only the CEO, or DevOps with approval)

- Upgrading from the upstream git repo is the CEO's call:

      babd self-update --check      # is there a new upstream commit?
      babd self-update              # pull + test + keep a rollback
      babd self-update --rollback   # undo the last self-update

  Run those from the installation root, not from a worktree. They refuse anything but a fast-forward
  and roll back automatically when the tests fail.
- Nothing tells you to do this on your own. If a task seems to need it, ask the Team Lead first.

## Never

- Never write to `/home/serverbot/aidev/babd`, `agents.json`, `.env`, `.git` or `.babd` directly - it
  is blocked, and if it were not it would corrupt the running team.
- Never run `git push` to the upstream repo unless the project's task explicitly says to.
- Never delete another agent's worktree or branch.
