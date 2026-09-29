# Changelog

## 0.2.0 — preview, unreleased

Preview of stage 2a: streams in one repository and dispatch. A 0.1.0 workspace works unchanged
(`orch.py upgrade` only adds the two new tables when locks or the merge queue are needed). 0.1.0
modules that share one repository path now get a `lint` warning (not an error) and are dispatched
one at a time; each keeps its own base. To run them in parallel, add a `repos` entry and turn
them into `kind: area|domain` modules with paths.

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
- `safe_edit.py --stdin`: one or more OLD/NEW blocks, applied all or nothing, no temporary files;
  `lint` rejects leftover marker lines; backup fallback when `.orch-backup/` cannot be written.
- P4 identifies a module repository by git common directory and origin URL (linked worktrees and
  clones included; git older than 2.31 supported); `orch/<program>` is the only allowed branch.
- Globs support `{a,b}` (expanded for matching and overlaps; `init` keeps commas inside braces);
  `[`/`]` are literal. Dependencies accept module ids with hyphens (`WP-ADMIN-UI-01`).
- Locks: shared-path locks collide by glob; unknown resources and paths outside `shared_paths`
  are refused; a released lock with a queue stays as a free row, the queue is respected, and a
  package leaves every queue once it gets its lock; `merge done` names the waiting packages.
- `push_deploys: true` on a repository: delivery sections tell sessions to commit locally and push
  only with the stand slot. `git status` in session worktrees uses `--no-optional-locks`.
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
