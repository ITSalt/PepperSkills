# Mode: resume

Restore the orchestrator after a lost or new session: files, reconciliation with reality, next
step. No argument, or the program name when several workspaces exist.

## Steps

1. **Find the workspace.** `orch.py` searches upward for `orch.yaml`, then `features/*/orch.yaml`.
   With several, ask which program and pass `--workspace <dir>` (before or after the
   subcommand), or set `ORCH_WORKSPACE`. A new orchestrator session can start from
   `orchestration/bootstrap-prompt.md` of the workspace.
2. **Read state.** `status.md` (WP table, owner queue, top of the journal), the tail of
   `decisions.md`, `orch.yaml`. `orch.py queue` lists open owner items.
3. **Reconcile with reality** (concept section 11), read-only, delegated when long:

   | What | How |
   |------|-----|
   | live sessions | `ListAgents` or `claude agents --json` where available |
   | worktrees per repository | `orch.py worktrees`: branch, dirty tree, ahead/behind the base, package |
   | PRs and CI | by branch: `gh pr list --repo <r> --head <branch> --state all`; by package id in the body: `gh pr list --repo <r> --search '"<WP>" in:body' --state all` (the id in quotes: GitHub splits it on hyphens otherwise); then `gh pr view`, `gh pr checks`, `gh run list` |
   | foreign writers | remote branches no package owns (`git -C <repo> branch -r`, for example cloud-session or other-agent branches), worktrees without a package, other sessions in `ListAgents` |
   | the stand | `gh run list --repo <r> --workflow <deploy_workflows entry> -L 5`: which branch deployed last, is it held by the `staging` lock holder |
   | branches of main checkouts | `git -C <repo> rev-parse --abbrev-ref HEAD`, lag behind `origin/<base>` |
   | paths | `orch.py overlap`: files outside allowed paths, undeclared or unlocked shared paths, repository checks |
   | databases | migration journal and object definitions through a read-only tool, SELECT only |
   | deployed versions | version string in the served bundle, not the browser badge |

   A PR that exists for an `IN_PROGRESS` package means READY was lost: treat it as READY. Search
   PRs by branch and by package id: a module's own methodology may name branches and PR titles its
   own way, so the tag alone is not enough.
4. **Record discrepancies first.** For each mismatch: `orch.py journal "<what differs>" --wp <WP>
   --evidence "<command and result>"`, then fix the row with `orch.py set ... --evidence`.
   Owner items whose fact is now verified: `orch.py owner close R-n "<fact>"`.
5. **Pick the next step:** the earliest open item in lifecycle order (owner answers that unblock
   packages, review of arrived PRs, the merge queue, verification after merges and lock releases,
   dispatch of READY packages and of packages waiting for a released lock).
6. **Commit.** `orch.py lint`, `orch.py commit "<program>: resume, reconciled"`.

## Result for the owner

Outcome of reconciliation (what changed since the last journal line), then the next step, then
owner commands if any. Unverified items are named first.
