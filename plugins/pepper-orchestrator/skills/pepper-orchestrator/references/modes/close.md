# Mode: close

Close a program whose goal is reached. One program, one goal: when the completion condition in
`PLAN.md` holds, the program is closed; the next goal is a new program (`init`). Arguments: none,
or a one-line result.

## Steps

1. **Check the completion condition** in `PLAN.md` ("Goal and completion condition") against
   facts (PR states, CI, PROD verification). If it does not hold, say what is missing; do not close.
2. **Check by facts.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py close --check
   ```

   Blockers: a package not in a terminal status (`DONE`, or `CANCELLED (reason)`); an open PR of a
   package branch (listed with `gh`; without `gh`, a branch still on origin blocks until you check
   its PRs with the session's GitHub tools or get the owner's link, then pass
   `--prs-verified "<evidence>"`); a lock still in the lock table; a package still queued for
   merge; an open owner item. It also lists the module sessions the owner can close.
3. **Resolve the blockers.** Finish or cancel packages with evidence; release locks; close owner
   items with verified facts or drop them with a reason; move items that belong to a later goal to
   the backlog: `orch.py owner carry <id> "<reason>"` (appends to `backlog.md`).
4. **Close.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py close --apply --summary "<result against the completion condition>" [--prs-verified "<evidence>"]
   ```

   It writes `reports/closeout-<date>.md` (goal and condition, result, packages with PRs,
   decisions, backlog, risks, sessions to close, optional lessons), sets `state: closed` in
   `orch.yaml`, puts a banner on top of `status.md`, adds the journal line and commits.
   - **Separate home repository:** the workspace is then moved to `features/_archive/<program>`
     with `git mv` and committed.
   - **In-repo workspace:** the plugin never tags or deletes branches. It adds an owner item with
     the commands (tag `orch-<program>-closed-<date>` on `orch/<program>`, push the tag, delete
     the branch) and an optional question whether to keep the workspace as history in `docs/` of
     the base branch through a PR.
5. **Tell the owner:** the result, the closeout report link, the sessions to close, the archive
   commands (in-repo), and that a new goal starts with `init` of a new program.

Never merge, tag, delete branches or push to a base branch, locally or in the cloud.
