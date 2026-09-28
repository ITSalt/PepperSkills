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
   | PRs and CI per module | `gh pr list --repo <r> --search "<TAG>"`, `gh pr view`, `gh pr checks`, `gh run list` |
   | branches of main checkouts | `git -C <repo> rev-parse --abbrev-ref HEAD`, lag behind `origin/<base>` |
   | databases | migration journal and object definitions through a read-only tool, SELECT only |
   | deployed versions | version string in the served bundle, not the browser badge |

   A PR that exists for an `IN_PROGRESS` package means READY was lost: treat it as READY.
4. **Record discrepancies first.** For each mismatch: `orch.py journal "<what differs>" --wp <WP>
   --evidence "<command and result>"`, then fix the row with `orch.py set ... --evidence`.
   Owner items whose fact is now verified: `orch.py owner close R-n "<fact>"`.
5. **Pick the next step:** the earliest open item in lifecycle order (owner answers that unblock
   packages, review of arrived PRs, verification after merges, dispatch of READY packages).
6. **Commit.** `orch.py lint`, `orch.py commit "<program>: resume, reconciled"`.

## Result for the owner

Outcome of reconciliation (what changed since the last journal line), then the next step, then
owner commands if any. Unverified items are named first.
