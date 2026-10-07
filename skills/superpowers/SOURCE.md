# Superpowers skills (vendored)

These 15 skills are an unmodified copy of the `skills/` directory of
[obra/superpowers](https://github.com/obra/superpowers) by Jesse Vincent, MIT licensed (see `LICENSE`).

- Commit: `8ca22dba9a94f28898bbce59f2537ff4d87c747d` (2026-09-25)
- Copied so they run locally, with no network access and no plugin install.

BABD hands each skill to the agents it fits (`superpowers` in `agents.json`) and uses it on every
matching step; see `babd/superpowers.py` and `ADAPTATION.md`. To update, replace this directory with a
newer copy of `skills/` from the repository and update the commit above.
