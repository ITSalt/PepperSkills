# Mode: resume

Restore the orchestrator after a lost or new session: files, reconciliation with reality, next
step. No argument, or the program name when several workspaces exist.

## Steps

1. **Find the workspace.** `orch.py` searches upward for `orch.yaml`, then `features/*/orch.yaml`.
   With several, ask which program and pass `--workspace <dir>` (before or after the
   subcommand), or set `ORCH_WORKSPACE`. A new orchestrator session can start from
   `orchestration/bootstrap-prompt.md` of the workspace.
2. **Closed program?** If `orch.yaml` has `state: closed`, only report the result (the closeout
   report in `reports/`) together with the open archive items R/P of the owner queue
   (`orch.py queue`), and say: a new goal is a new program (`init`); to continue this goal,
   `reopen "<reason>"`. Do not look for work in it.
2a. **Session name and settings.** Compare this session's name (`ListAgents`: "This session is
   ...") with `coordinator_session`; if they differ, `/rename <coordinator_session>` before any
   message. On the first resume, remind the owner that the orchestrator should run with
   `--settings orchestration/settings/orchestrator.json` (or `/config` -> "Messages from your other
   sessions" -> accept): a session cannot check how it was started, and without it messages from
   sessions in another permission class are dropped after 5 minutes. `lint` warns about missing or
   stale settings files (`orch.py settings all`). The protocol never relies on messages: READY is
   also found by `gh pr list` and `orch.py ready`.
2b. **Delivery on hold?** `orch.py delivery show` (and the first `lint` warning) names a hold with
   its reason: say it first; nothing is delivered until the analysis ends with
   `orch.py unhold "<reason>"` (the orchestrator after the facts, or the owner).
3. **Read state.** `status.md` (WP table, owner queue, top of the journal), the tail of
   `decisions.md`, `orch.yaml`. `orch.py queue` lists open owner items.
4. **Reconcile with reality** (concept section 11), read-only, delegated when long:

   | What | How |
   |------|-----|
   | live sessions | `ListAgents` or `claude agents --json` where available |
   | worktrees per repository | `orch.py worktrees`: branch, dirty tree, ahead/behind the base, package |
   | PRs and CI | by branch: `gh pr list --repo <r> --head <branch> --state all`; by package id in the body: `gh pr list --repo <r> --search '"<WP>" in:body' --state all` (the id in quotes: GitHub splits it on hyphens otherwise); then `gh pr view`, `gh pr checks`, `gh run list` |
   | foreign writers | remote branches no package owns (`git -C <repo> branch -r`, for example cloud-session or other-agent branches), worktrees without a package, other sessions in `ListAgents` |
   | the stand | `gh run list --repo <r> --workflow <deploy_workflows entry> -L 5`: which branch deployed last, is it held by the `staging` lock holder |
   | branches of main checkouts | `git -C <repo> rev-parse --abbrev-ref HEAD`, lag behind `origin/<base>` |
   | paths | `orch.py overlap`: files outside allowed paths, undeclared or unlocked shared paths, repository checks |
   | trusted delivery | `orch.py delivery show`; for `ACCEPTED` packages with delivery handed over, `orch.py deliver --check <WP>` |
   | verification | `orch.py verify --list`: merged packages without `VERIFIED_TEST` (suggest `verify <WP> --env test` once the deploy run for the merge commit succeeded) and packages verified on test waiting for prod; only `VERIFIED_TEST` packages may go to a release sheet |
   | plugin defects and updates | `orch.py report --status`: recorded `PLUGIN-BUG-<n>` with their Issues; with `gh`, one line when a newer plugin version is on the marketplace (`claude plugin update pepper-orchestrator@pepperskills`) |
   | on-demand locks | `orch.py lock list` / `lint`: a lock held longer than `lock_stale_hours` (default 4) is a warning: ask its session whether it still needs it |
   | databases | migration journal and object definitions through a read-only tool, SELECT only |
   | deployed versions | version string in the served bundle, not the browser badge |

   **Without `gh`** (some cloud sessions): run `orch.py ready` (pushed branches of dispatched
   packages via `git ls-remote`), then find each **open** PR with the session's GitHub tools (by
   head branch, and check that its body contains the package id; read workflow runs for the
   stand), or ask the owner for the PR links. With `gh`, `ready` already does this. With a
   separate workspace and no local clone of the module repository, `ready` says so: ask the owner
   for the PR link. Never use a merge tool. Cloud module sessions send no READY: readiness
   is always found this way.

   A PR that exists for an `IN_PROGRESS` package means READY was lost: treat it as READY. Search
   PRs by branch and by package id: a module's own methodology may name branches and PR titles its
   own way, so the tag alone is not enough.
5. **Record discrepancies first.** For each mismatch: `orch.py journal "<what differs>" --wp <WP>
   --evidence "<command and result>"`, then fix the row with `orch.py set ... --evidence`.
   Owner items whose fact is now verified: `orch.py owner close R-n "<fact>"`.
6. **Pick the next step:** the earliest open item in lifecycle order (owner answers that unblock
   packages, review of arrived PRs, the merge queue, verification after merges and lock releases,
   dispatch of READY packages and of packages waiting for a released lock).
   When every package is in a terminal status and nothing is left to do, propose `close`
   (`orch.py close --check` lists what still blocks) instead of looking for more work.

7. **Commit.** `orch.py lint`, `orch.py commit "<program>: resume, reconciled"`.

## Result for the owner

Outcome of reconciliation (what changed since the last journal line), then the next step, then
owner commands if any. Unverified items are named first.
