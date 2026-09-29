# Mode: close

Close a program whose goal is reached. One program, one goal: when the completion condition in
`PLAN.md` holds, the program is closed; the next goal is a new program (`init`). Arguments: none,
or a one-line result.

## Steps

1. **Check the completion condition** in `PLAN.md` ("Goal and completion condition") against
   facts (PR states, CI, PROD verification). If it does not hold, say what is missing; do not close.
   `close` refuses while the condition is not written; for an older plan without it, pass
   `--goal-confirmed "<how the goal was verified>"` (recorded in the closeout and the journal).
2. **Check by facts.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py close --check
   ```

   Blockers: a package not in a terminal status (`DONE`, or `CANCELLED (reason)`); an open PR of a
   package (the recorded PR URL via `gh pr view`, and open PRs of the package branch via
   `gh pr list`); a lock still in the lock table; a package still queued for merge; an open owner
   item. Whatever cannot be checked here is a blocker too: a recorded PR URL without `gh`, a
   branch still on origin without `gh`, a failing `git ls-remote`, a module repository not
   available here (typical for a cloud orchestrator). Only `--prs-verified "<evidence>"` clears
   those, and the evidence must be concrete: the output of `list_pull_requests head=<branch>
   state=open` from the session's GitHub tools, or PR URLs with their state (closed/merged) from
   the owner. The evidence is written to the journal and the closeout. The check also lists the
   module sessions the owner can close.
3. **Resolve the blockers.** Finish or cancel packages with evidence; release locks; close owner
   items with verified facts or drop them with a reason; move items that belong to a later goal to
   the backlog: `orch.py owner carry <id> "<reason>"` (appends to `backlog.md`).
4. **Close.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py close --apply --summary "<result against the completion condition>" [--prs-verified "<evidence>"]
   ```

   It checks everything the commit needs first (lint, branch, place, in-repo deploy rules) and
   changes nothing when that fails. Then it writes `reports/closeout-<date>.md` (goal and
   condition, result, packages with PRs and a version column to fill in after checking, checks
   made without full evidence, decisions, backlog, risks, sessions to close, optional lessons),
   sets `state: closed` in `orch.yaml`, puts a banner on top of `status.md`, adds the journal
   lines and commits (and pushes with `push_after_milestone`). If the commit could not be made
   (`--no-commit`, or an interrupted run), a second `close --apply` finishes the commit and the
   archive.
   - **Separate home repository:** the workspace is then moved to `features/_archive/<program>`
     with `git mv`, committed and pushed. A workspace that is the root of its own repository is
     not moved; the owner archives it.
   - **In-repo workspace:** the plugin never tags or deletes branches. It adds an owner item with
     commands that run from any clone and are tied to the closeout commit:
     `git push origin <closeout sha>:refs/tags/orch-<program>-closed-<date> && git push origin
     --delete orch/<program>`, and an optional question whether to keep the workspace as history
     in `docs/` of the base branch through a PR.
5. **Tell the owner:** the result, the closeout report link, the sessions to close, the archive
   commands (in-repo), and that a new goal starts with `init` of a new program.

Never merge, tag, delete branches or push to a base branch, locally or in the cloud.
