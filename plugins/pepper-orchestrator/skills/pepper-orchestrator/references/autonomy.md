# Opt-in local Codex autonomy (0.13 candidate)

One coordinator chooses work; independent module sessions implement it. `next` is
read-only. A local watcher observes facts and wakes the existing coordinator; it
never dispatches, creates an executor, merges or deploys. Claude transport autonomy
is not part of this candidate. Existing programs remain disabled after upgrade.

## Enable and resume

Run from the program's coordinator session. Bind its actual thread ID and the PID
of its live client/server process, with evidence that they belong together:

```bash
python3 scripts/orch.py --workspace /absolute/program autonomy claim \
  --coordinator THREAD --pid PID --evidence 'verified this client/server owns THREAD'
python3 scripts/orch.py --workspace /absolute/program autonomy enable \
  --coordinator THREAD --generation GENERATION
```

Use the generation returned by claim. Defaults: `session_reuse=auto`, two active
or reserved module slots, a 600-second action recheck. Overrides on enable/resume:
`--session-reuse auto|ask|never`, `--max-parallel-sessions N`, `--interval-seconds N`.
Review/scout/verifier subagents do not occupy module slots. Ordinary observation
samples every five seconds without model calls. A repeated actionable condition
may wake the coordinator again after the recheck deadline; empty ticks stay quiet.

The transport must observe the same live runtime that owns the thread. By default
it connects to the running Codex CLI daemon with `codex app-server proxy`; it does
not start a replacement daemon. If sessions use an explicit local App Server,
set `codex.remote: unix:///absolute/server.sock` (macOS/Linux) or loopback
`ws://127.0.0.1:PORT` in orch.yaml. Queue and observation use that same endpoint.
Only local endpoints are supported. A separate stdio server reading stored history
cannot prove that another server's thread is idle and is not used for autonomy.

`autonomy resume --coordinator THREAD --generation N` restores a missing watcher.
Only one watcher per program runs. After machine reboot, resume is required; no
system service is installed. Inspect `autonomy status` for pending signals/errors.
`autonomy pause` stops new assignments/wakeups; it does not stop existing workers.
Close and client switching also stop autonomous continuation.

## Discover, attach and reuse

`session discover` reads live thread candidates in repository worktrees. Names
and cwd help locate candidates but never authorize them. Attach one explicitly:

```bash
python3 scripts/orch.py --workspace /absolute/program session attach \
  --wp WP-APP-01 --thread MODULE_THREAD --worktree /absolute/worktree \
  --pid CLIENT_OR_SERVER_PID --evidence 'verified launch settings and process binding'
```

The PID confirmation records host and precise process start identity. Thread
creation identity, observed model/effort, program configuration, launch descriptor
and config-file hashes are bound to it. Unknown launch permissions/MCP settings
must be checked and confirmed once for that process; the API does not expose all
of them. Model/effort metadata is configured state, not per-turn execution proof.
Invisible in-session changes remain a limitation. Changed process, cwd, settings,
model/effort or configuration requires reconfirmation. Legacy `register` remains
available but does not make an old session trusted for automatic reuse.

Reuse requires a loaded idle session (approval/input waits are busy), its own
clean linked worktree in the configured Git checkout, no other registered writer,
and the previous package merged. The exact local HEAD must match the full accepted
PR head and live merged PR facts; a squash merge or deleted remote branch does not
make `HEAD...base` a lost-work test. Held locks/mandatory integration work still
block reuse. ACCEPTED alone is insufficient.

## Coordinator continuation

On resume, READY, review/verification results, lock/dependency changes and watcher
signals, run `next --json`. Use its compatible wave, then re-evaluate before every
assignment. Perform existing review/verify/delivery gates first where required.
Do not ask the owner to type `/dispatch`.

```bash
python3 scripts/orch.py --workspace /absolute/program next --json
python3 scripts/orch.py --workspace /absolute/program dispatch WP-APP-02 --dry-run --json
python3 scripts/orch.py --workspace /absolute/program dispatch WP-APP-02 --json \
  --coordinator THREAD --generation N
```

Results distinguish blocked, reuse candidate, needs new terminal, assigned,
queued, started and unknown outcome. For a new terminal, the coordinator invokes
`dispatch WP --owner-launch --coordinator THREAD --generation N` to reserve the
slot/locks and print the final owner launch command. The owner runs only that
command. `ask` leaves reuse for an explicit policy decision; `never` always uses
the new-terminal path. Do not silently change the owner's selected policy.

Dispatch atomically reserves the session, slot, locks and stable assignment ID,
then queues TASK outside the state transaction. Queue success is not start.
The recipient reads the full WP and instructions, preserves a short handover,
then runs the supplied `session transition` command **in its current worktree**.
It verifies the old HEAD, fetches the base, switches to the new branch and prepares
it. It writes only a technical runtime receipt, not coordinator documents. The
recipient echoes `STARTED assignment_id=...`. The coordinator runs
`session started --assignment ID --coordinator THREAD --generation N`; this reads
the assistant acknowledgement, receipt and actual branch before IN_PROGRESS.
Repeated TASK/transition continues the same assignment, not a new job.

For split preparation use `session assign --wp WP`, then `session send
--assignment ID`, with coordinator/generation flags. A read-only scout may gather
heavy environment/MCP facts; its report cannot override current CLI checks.

## Recovery and context

`session reconcile --assignment ID --coordinator THREAD --generation N` checks
recipient output and Git. A user-message echo is not an acknowledgement. Unknown
sends retain reservation and locks; neither automatic retry nor OWNER HANDOVER is
safe. A sender returning after an early STARTED never lowers the assignment state.
A reserved assignment with no send intent may transfer to the new coordinator.

`autonomy release` ends coordinator ownership. `autonomy recover` requires a new
process/session binding plus `--previous-stopped` with concrete owner-confirmed
recovery evidence. Lease expiry alone never authorizes takeover. Old generations
cannot allocate/send. Reconcile their pending sends before replacement work.

For a not-yet-started assignment, `session cancel --assignment ID --evidence ...`
with coordinator/generation flags requires the confirmed recipient process to be
gone and its thread idle/notLoaded. It marks the assignment cancelled, preserves
the outbox, releases its locks and returns DISPATCHING to READY. Do not use it to
discard work from a started package. Stale queued TASK fails its cancelled-ID check.

A crash during branch switching resumes actual Git facts. A crashed setup command
is not replayed blindly. Inspect effects, then use `session recover-transition
--assignment ID --evidence ...` with coordinator/generation flags while the
recipient is idle, and send a targeted instruction to retry that same transition.
Do not create a replacement assignment.

`session compact --thread MODULE_THREAD --coordinator THREAD --generation N`
uses `thread/compact/start` on the owning server and requires a completed
contextCompaction event. It subscribes only to an already-loaded idle runtime,
without model/permission overrides. Unknown completion blocks reuse until checked
and explicitly reconfirmed with attach. Never send literal `/compact` as proof,
never automate `/clear`; prepare a new owner-launched session if context is unsafe.

Watcher signals contain a stable ID. The coordinator runs the provided
`autonomy consume --signal ID --coordinator THREAD --generation N` before acting.
It checks current pause/closed state; a stale signal grants no authority. Busy
coordinators accumulate one coalesced signal, not repeated turns. A crash after
send intent keeps the pending signal; inspect recipient history and consume that
ID on resume rather than sending another wakeup blindly.

Periodic Git/PR/CI/file/session observation is allowed. Empty “how is it going?”
messages are not. Report owner decisions, permission waits, observation failures,
real deadlocks and completion; ordinary pending CI is a wait, not a deadlock.
Merge/stand/PROD delegation, database restrictions, sandbox and approvals remain
unchanged. No new product initiatives or automatic terminal creation are allowed.
