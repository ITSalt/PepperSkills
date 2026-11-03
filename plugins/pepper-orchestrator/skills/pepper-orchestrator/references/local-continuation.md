# Local Codex continuation

This contract governs ordinary local Codex sessions. Read it at init, plan and resume.
The separate private-owner runtime is selected only when the owner explicitly asks for it.
Its version pin and isolated permissions apply to that runtime alone.

## Initialize and restore

Ask once, in the owner's language: “After you approve the plan, should I run the ready
packages and continue to the goal automatically, or wait for your launch command?”
An explicit request to enable continuation already answers this question. Use
`init --continuation auto|manual`. For an existing program with no choice, ask on
first resume and record `autonomy configure --continuation auto|manual --evidence
"owner answer"`. A saved choice survives /clear and restart. This setting records
intent. It does not prove that the watcher is running.

Init captures the current Codex turn's permissions, including --yolo. Explicit
`--approval-policy` and `--sandbox-mode` override the captured values. Check the
resulting orch.yaml with the owner. For an existing program missing these keys,
read this coordinator's effective turn policy and record it under codex before
`settings all`. Never silently substitute workspace-write for danger-full-access.
Module sessions use the program's explicit policy, model and reasoning effort.

Claim the actual coordinator thread and live client/server PID with evidence of
their binding, then enable. A coordinator can run in the program checkout or a
configured module's main checkout. Use the local daemon's announced socket. Test
thread observation and use the delivery and start confirmations from the transport.
An installed newer CLI is checked by its operations, not by the private-owner pin.
After /clear, inspect the old coordinator and outstanding assignments. Recover
ownership with evidence that the former coordinator stopped writing, retaining
unknown sends and reservations. Resume the watcher, consume pending signals,
then recompute next. Never erase the registry to restart.

## Plan and execute

A plan-only request ends with a ready-to-paste prompt for this same chat:
“Approve the plan for PROGRAM at ABSOLUTE_WORKSPACE and start its ready packages
with the saved continuation setting.” Substitute real values. If the user already
approved execution, run the available actions immediately.

Mark research packages with `| Execution | research |` ([research contract](research.md)).
After plan approval, set the first eligible packages READY. Research dependencies
are accepted reports (ACCEPTED or DONE). Respect the program's resource limits.

For enabled continuation, execute `next --json` after every lifecycle change.
`continue_research` means resume the named package and its saved progress, using
scoped research agents or `autonomy launch --wp WP --coordinator THREAD
--generation N` for a new local session. `launch` uses that same command for a code
package. The coordinator starts these sessions itself. Do not ask the owner to
open a terminal when the available transport can start the session.

The launch command reserves the package before setup, creates a thread on the
same local runtime, sends the package and records the returned turn ID. A failure
or unknown outcome keeps the launch reserved. Inspect sessions.json and the live
thread before any recovery. Never resend or create a replacement speculatively.
The watcher observes completion and wakes the coordinator. `review_research` and
`review_result` require reading the worker's actual result and checking the package
acceptance criteria. Save the report, request revisions when necessary, mark a
verified research report ACCEPTED then DONE and continue with eligible dependencies.
Research reports do not require fictional PR, merge or production stages.
For code packages follow the established review, delivery and verification gates.
Run next again immediately after acceptance. Stop only at the goal, an actual
owner decision, a resource limit or a demonstrated operation failure. A `stalled`
action is yours to handle: inspect the session, then nudge, restart or reassign it.

## Every response has an operational next step

If work continues, name the active package and say that the owner need do nothing.
If input is needed, ask the concrete question. If a manual launch/restart is truly
required, give one complete command with actual paths, say whether to paste it in
this chat or a terminal, and state the expected result. A phase summary alone is
insufficient. Preserve the selected permission flags in any restart command.
Never say “could not enable” after only reading status or help. Report the exact
operation attempted and its result. Check `autonomy status` after enable/resume.
Claim running continuation only after the watcher is alive and observation succeeds.
Manual mode waits for the requested step and always supplies the next ready prompt.

## Bounded collection and acceptance

Research packages, partial acceptance, the control tick and bounded goals follow the
client-neutral [research contract](research.md). Continue the current turn toward the frozen
deliverable. Elapsed time is a control tick that ends in a decision; it never opens a wave
beyond the recorded budget. A paused owner remains paused until explicit authorization to
resume. No instruction to continue authorizes endless research or spending beyond limits.

A scoped diagnostic request applies to its response. Later owner instructions
update the authorized scope without an additional permission ritual.
