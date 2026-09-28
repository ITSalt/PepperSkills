# Changelog

## 0.2.0 — preview, unreleased

Preview of stage 2a: streams in one repository and dispatch. A 0.1.0 workspace works unchanged
(`orch.py upgrade` only adds the two new tables when locks or the merge queue are needed).

- `orch.yaml`: `repos` block (base, branch prefix, worktree root and setup, merge policy, shared
  paths, resources, checks, deploy workflows) and modules of kind `area`, `domain` or `repo` with
  `paths`, `session`, `test_db`, `ports`, `tests`, `methodology`; the 0.1.0 module form is
  `kind: repo`, `paths: ["**"]`.
- New `orch.py` commands: `dispatch`, `overlap`, `lock acquire|release|list`,
  `merge add|done|drop|list`, `worktrees`, `upgrade`. `lint` checks module path overlaps,
  whole-repository modules sharing a repository, lock and merge queue tables.
- New mode `dispatch` and command `/pepper-orchestrator:dispatch`; `init` handles several modules
  per repository, reads the repository's branch prefix, asks the owner's language explicitly and
  refuses a workspace in a module's base checkout (also on `commit`); `resume` reads worktrees,
  finds PRs by branch and package id, foreign writers and stand deploys; `owner` prints the merge
  queue in order with waits and recommends batches when merges deploy production.
- Work package template: stream, worktree, allowed and shared paths, migrations, resources, test
  database and ports, line, merge slot, methodology limits; generated worktree preparation,
  delivery (with or without a remote) and start command (`claude -w` for streams).
- `safe_edit.py --stdin` (fragments in one block, no temporary files) and a backup fallback when
  `.orch-backup/` cannot be written.
- `plan` never writes an open P-n's recommendation as decided; the manifest description says
  where to start.
- Concept 1.1 (EN and RU): rules P1-P5 in sections 4, 7 and 12, new section 19 on repositories
  where a push deploys a stand.

## 0.1.0 — preview, unreleased

Preview of the stage 1 core; formats and commands may change before 1.0.0.

- Stage 1 core: canonical skill with a mode router and modes `init`, `plan`, `resume`, `owner`,
  `decide`.
- Workspace CLI `orch.py` (init, new-wp, set, journal, owner, queue, decide, lint, commit) and
  `safe_edit.py` (exactly one match, backup, size check), standard library only, with a self-test.
- Workspace, work package and bug templates in English and Russian; optional `Specification` field
  in work packages and `spec_graph: none` in `orch.yaml` as the docking point for a specification
  graph.
- Concept: English translation (`references/concept.md`) and Russian original
  (`references/concept.ru.md`).
- Claude Code short commands in `commands/`.
