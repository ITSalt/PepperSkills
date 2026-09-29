# Changelog

## 0.3.0 — preview, unreleased

Preview of stage 2b: review of module deliveries.

- Mode `review` and command `/pepper-orchestrator:review`: automatic findings, the
  `orchestrator-reviewer` agent on the first submission, the revision diff on resubmissions,
  verdict REVISE/ACCEPTED, report from the `review-report` template (EN/RU), REVISE message and
  ACCEPTED hand-over (merge queue, owner merge item). Never merges, approves or comments.
- `orch.py review-start <WP>`: automatic findings reusing the stream rules (files outside the
  allowed paths, shared paths undeclared or without the lock, repository `checks`) plus a stale
  merge-base with the branch files the base changed since; report skeleton; status `REVIEW`; the
  disposable clone command; `--since/--round` for resubmissions (`git range-diff` after a rebase).
- `scripts/review_clone.sh`: clone at a SHA into a marked temporary directory, setup, tests,
  removal (`--keep` for mutations, `--cleanup` only for marked directories); never pushes.
- Agents (Claude Code adapter): `orchestrator-reviewer` (read-only, disposable clone, mutations,
  claims as claims, base comparison) and `orchestrator-scout` (read-only facts, SELECT only).
- `references/review-brief.md`: brief template and risk checklists (state machines, migrations,
  registries and shared types, UI, permissions, integrations).
- README: "Typical workflows" (EN/RU) with exact calls for local and cloud sessions.
- `review-start` reviews `origin/<branch>` or the given `--ref` (never a local branch), warns when
  the local branch differs, stops on a failing fetch (`--no-fetch` to skip), prints
  `git range-diff <base>..<old> <base>..<new>` after a rebase, and puts `main @ <sha>` in the
  report header. Review clones use the repository's own `review_setup` with
  `ORCH_MAIN_CHECKOUT`, never `worktree_setup`. `review_clone.sh` checks flag values and `mktemp`.
- Agents state honestly that MCP tools are not available to them (the orchestrator collects
  database and GitHub-tool facts) and forbid database clients and `ssh` through Bash; the cloud
  review brief allows only reading GitHub tools. The report template has an "Owner questions"
  section, and small fixes that need the owner's consent become conditional REVISE items.

## 0.2.1 — preview, unreleased

Preview of stage 2c: cloud sessions over one repository.

- In-repo workspace: `init --in-repo <repo-id>` switches to `orch/<program>` (created without
  tracking the base), finds a directory every push workflow ignores (`on.push` `paths-ignore`,
  `branches`, `branches-ignore` in `.github/workflows/*`) and refuses when there is none; new
  `orch.yaml` keys `workspace_mode`, `workspace_branch`, `workspace_dir`; repository paths may be
  relative to the workspace's repository (`path: .`). `commit` goes only to `workspace_branch` and
  always pushes to the same-named remote branch.
- `sessions: cloud` on a repository or module: work packages carry a cloud-session prompt (read the
  package from `orch/<program>` or inline, branch from the base, PR with the package id, no message
  back, never merge tools such as `mcp__github__merge_pull_request`); `dispatch` prints it
  (`--inline` appends the package text).
- `orch.py ready`: dispatched packages whose branch is on origin (`git ls-remote`), with the PR via
  `gh` when available; `resume` describes the no-`gh` path through the session's GitHub tools.
- Workspace discovery also finds nested in-repo workspaces (up to four levels below the current
  directory); `lint` checks the in-repo keys and warns when the workspace directory is not
  ignored by every push workflow.
- `scripts/install-skill.sh` (repository root): idempotent copy of a canonical skill into
  `~/.claude/skills` for cloud environment setup scripts; README section "Cloud sessions".
- Skill: hard rule "no merge tools", cloud section, `/pepper-orchestrator <mode>` calls without
  plugin commands. Concept 1.2 (EN and RU), section 20 "Cloud sessions".
- Deploy check is strict: workflows are read from the pushed ref (`git ls-tree`/`git show`), a
  missing ref or any workflow form outside the documented list is a refusal, hidden directories
  are never candidates and `docs/` comes first; an unsafe `--dir` is refused; the only override is
  an owner decision (`--deploy-override D-n`, stored as `deploy_check_override`). `commit` of an
  in-repo workspace refuses while the check fails.
- `dispatch --dry-run` writes nothing for any module; a cloud package must be on
  `origin/orch/<program>` (same content) before its prompt is printed; with `push_deploys` a cloud
  package holds the `staging` lock and its prompt says to push once.
- `init --in-repo` fetches first and reuses an existing `origin/orch/<program>` (refusing a second
  workspace); `commit` refuses a detached HEAD before committing, pushes to the branch's own remote
  and keeps an existing upstream; repository names are read from GitHub and cloud proxy URLs;
  `ready` reports only open PRs with the package id in their body.
- README setup fragment never fails the environment's setup script; `install-skill.sh` removes its
  temporary directory on failure.

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
