# Mode: dispatch

Hand a READY work package to a module session: checks, locks, the start command for the owner (or
a `TASK` line for a live session), status `DISPATCHING`. Argument: the WP id.

## Steps

0. **Check the session name first.** Compare this session's name (`ListAgents`: "This session is
   ...") with `coordinator_session` in `orch.yaml`; if they differ, `/rename <coordinator_session>`
   before any message or dispatch: packages tell sessions to report to that name.
1. **Check without changing anything.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py dispatch <WP> --dry-run
   ```

   It refuses when the package is not `READY`; when a dependency (`Depends on`) is not merged;
   when another active package writes in the same repository and one of them is the whole
   repository, or runs in the same stream; when the paths overlap with another active package
   outside `shared_paths`; when a lock the package declares (shared paths touched, resources) is
   held by another package, or overlaps by glob with one (`backend/migrations/**` against
   `backend/migrations/0002.sql`); when a released lock still has a queue and the package is not in
   it; when the module's settings file `orchestration/settings/<module>.json` is missing (run
   `orch.py settings <module>`; a workspace from before 0.6.0 can pass `--no-settings` for the old
   start command). A declared name that is not one of the repository's `resources` and lies outside
   its `shared_paths` is not a lock: dispatch warns and ignores it (typos never create new locks;
   `lint` warns too). On-demand resources are not taken at dispatch: the session asks with `LOCK`
   (step 6).
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

   It takes the declared locks, sets `DISPATCHING` with evidence (including the model and effort)
   and prints what to hand over. The package header is the source of truth for the model: the
   printed command carries `--model <m> [--effort <e>]` from the header at dispatch time, and for
   a local module `--permission-mode <permission_mode> --settings <absolute path of the module's
   settings file>` (a warning says when the file is older than `orch.yaml`: run `orch.py settings`
   first).
   `--dry-run` never writes anything, for any kind of module.
4. **Hand over.** Give the owner the printed command exactly as written, in its own code block.
   - A stream of a shared repository starts with `claude -w <wp-slug>`: the session gets its own
     worktree and prepares it itself (section 0 of the package: branch from the base, the
     repository's `worktree_setup`, its own test database and ports).
   - A module that is a whole repository starts in the repository checkout, as in 0.1.0.
   - A module with `sessions: cloud` gets a block for a **new cloud session** instead of a
     command: environment, repository and starting branch, model and effort (choose them in the
     lists next to the send button; in a browser without the lists send `/model <m>` and
     `/effort <e>` as the first messages), a claude.ai/code link that prefills repository,
     environment and prompt (without the prompt when the link would be too long; the branch is
     chosen in the form), then the prompt. A cloud module without `cloud_environment` is refused:
     ask the owner and record it with `orch.py cloud-env "<name>"`. Never set the model through an
     `ANTHROPIC_MODEL` variable of the environment (it would switch the orchestrator in the same
     environment too), and never put secrets into environment variables.
   - Locally never tell the owner to type `/model <name>` with an argument: it saves the model as
     the owner's default for every new session. Use the start flags, or the `/model` picker with
     `s` (this session only), or a restart with `--model`.
   - In a cloud session (`CLAUDE_CODE_REMOTE=true`) a local module is refused: a cloud orchestrator
     works only with cloud sessions. With an in-repo
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
   - Never edit a settings file or hand-craft `--settings`: the printed command already carries
     the generated one. The owner's own additions go to `<module>.local.json`, never passed by
     `dispatch`.
   - With `--live`, send the `TASK` line through cross-session messaging where the client has it;
     otherwise the owner relays it.
5. **Commit.** `orch.py lint`, then `orch.py commit "<program>: dispatch <WP>"`.
6. **LOCK and UNLOCK.** On `[TAG] LOCK <WP> :: <resource>` run
   `orch.py lock acquire <resource> --wp <WP> --note "LOCK message"`: held -> answer `ACK`; busy ->
   the package waits in the queue, answer `HOLD`. On `UNLOCK` run `orch.py lock release <resource>
   --wp <WP>` and dispatch or `ACK` the next package in the queue. READY (status `REVIEW` through
   `review-start` or `set`) releases the package's on-demand locks by itself.
7. **Denied permissions.** A `QUESTION` with a refusal text is answered on the facts: a missing
   narrow rule goes into `orch.yaml` (for example a test command) and `orch.py settings <module>`;
   the owner restarts the session with the same command (or answers the prompt in its window). Never
   tell a session to work around a refusal.

After the session confirms it started (message, branch or draft PR), set `IN_PROGRESS` with that
evidence. Do not poll the session.
