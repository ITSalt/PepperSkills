# Mode: dispatch

Hand a READY work package to a module session: checks, locks, the start command for the owner (or
a `TASK` line for a live session), status `DISPATCHING`. Argument: the WP id.

## Steps

1. **Check without changing anything.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py dispatch <WP> --dry-run
   ```

   It refuses when the package is not `READY`; when a dependency (`Depends on`) is not merged;
   when another active package writes in the same repository and one of them is the whole
   repository, or runs in the same stream; when the paths overlap with another active package
   outside `shared_paths`; when a lock the package declares (shared paths touched, resources) is
   held by another package, or overlaps by glob with one (`backend/migrations/**` against
   `backend/migrations/0002.sql`); when a declared resource is not one of the repository's
   `resources` or a declared shared path lies outside its `shared_paths` (typos never create new
   locks); when a released lock still has a queue and the package is not in it.
2. **Refused:** explain each reason to the owner in one line, with what unblocks it (a merge, a
   lock release, an owner answer). Running `dispatch <WP>` without `--dry-run` also records the
   refusal in the journal and queues the package in the `Waiting` column of every busy lock;
   `orch.py lock release` then names the next package in that queue. Do not work around a
   refusal by editing the package's declared paths unless the facts changed.
3. **Allowed:** run it for real.

   ```bash
   python3 SKILL_DIR/scripts/orch.py dispatch <WP>          # prints the start command
   python3 SKILL_DIR/scripts/orch.py dispatch <WP> --live   # prints a TASK line instead
   ```

   It takes the declared locks, sets `DISPATCHING` with evidence and prints what to hand over.
   `--dry-run` never writes anything, for any kind of module.
4. **Hand over.** Give the owner the printed command exactly as written, in its own code block.
   - A stream of a shared repository starts with `claude -w <wp-slug>`: the session gets its own
     worktree and prepares it itself (section 0 of the package: branch from the base, the
     repository's `worktree_setup`, its own test database and ports).
   - A module that is a whole repository starts in the repository checkout, as in 0.1.0.
   - A module with `sessions: cloud` gets a prompt for a **new cloud session** instead of a
     command: open a cloud session on the repository (base branch) and paste it. With an in-repo
     workspace the prompt tells the session to read the package from `orch/<program>`; with a
     separate workspace, or `--inline`, the package text is printed after the prompt. The session
     delivers a PR with the package id in its body and sends no message; `resume` and
     `orch.py ready` find it.
   - **Order for an in-repo workspace:** `orch.py commit` first (the package must be on
     `origin/orch/<program>`); `dispatch` refuses while the package is missing there or differs from
     the local file, then prints the prompt; commit again afterwards to record `DISPATCHING`.
   - In a repository where every push deploys the stand (`push_deploys`), a cloud package takes
     the `staging` lock for its whole life and its prompt says "push only once, when the work is
     complete"; the lock is released after merge and verification (`orch.py lock release`).
   - Never add `--settings` and never invent a settings file in this version.
   - With `--live`, send the `TASK` line through cross-session messaging where the client has it;
     otherwise the owner relays it.
5. **Commit.** `orch.py lint`, then `orch.py commit "<program>: dispatch <WP>"`.

After the session confirms it started (message, branch or draft PR), set `IN_PROGRESS` with that
evidence. Do not poll the session.
