# Codex Linux autonomy and macOS acceptance plan

30 October 2026. **Step 2 remains BLOCKED: live private-channel checks are partial.**
[Russian detailed plan](2026-10-30-orchestrator-codex-linux-acceptance.ru.md).
[Design ADR](../adr/2026-10-30-codex-private-stdio-tools.md).
[Linux agent prompt](2026-10-30-orchestrator-linux-agent.md).
[Linux follow-up](../validation/pepper-orchestrator-private-stdio-linux-2026-10-30.md):
API/caller/host/approval/same-thread recovery checks PASS, RPC/FD INCONCLUSIVE,
Git preparation BLOCKED at unchanged worktree roots. No scheduler integration.

## Scope and existing evidence

Achieve Codex Linux autonomy with the existing sandbox/approval guarantees, then
accept the same candidate archive on macOS. Preserve the portable scheduler,
Claude transport and all its regressions. No public release is authorized.

The immutable 0.13.0 baseline is tag `pepper-orchestrator-v0.13.0`, commit
`e1134fdf92346a2911163042b74d8a47b7831b46`. It has now been rerun: macOS PASS,
Linux WAIT/safe refusal. The
[previous report](../validation/pepper-orchestrator-0.13.1-linux-gate.md) records
versions, archive hashes and native evidence. Do not rerun these just to rediscover
them unless the environment changed. Do not attribute a candidate success to 0.13.0.

Continue branch `codex/orchestrator-linux-acceptance`, draft PR #42, retaining
safety fix `6d59bfa` and report `35b3626`. Verify current HEAD/main before starting;
do not resume the obsolete `abd7016` snapshot. Version 0.13.1 is an unreleased
safety-fix candidate, not an accepted Linux autonomy release.

## 1. Localize the boundary

Record OS/kernel, Python, every Codex PATH entry, actual native executable/version,
RPC schema, selected runtime, model and effective sandbox/approvals/network/roots.
Compare the owner with real coordinator/module shell calls. Preserve exact errno
for socket/proxy/queue access, PID namespace, `/proc`, boot_id, ownership,
compatible/next, transition, cancel, watcher/recover and compaction. A socket check
alone is insufficient. Use disposable fixtures and avoid secrets in evidence.

## 2. Prove the replacement channel before privileged implementation

The [old MCP design remains rejected](../adr/2026-10-30-codex-stdio-bridge.md):
raw `mcpServer/tool/call` could select another role's connection and forge `_meta`.
Parent PID, role tables and signed downstream receipts cannot fix that attribution.

The new candidate is one explicitly owner-launched native App Server over anonymous
STDIO pipes, without Unix/TCP ingress, shared proxy, remote control or a writable
file inbox. Experimental `dynamicTools` registered at thread start cause native
`item/tool/call` server requests to the owner. Role authority comes from protected
registration and the native envelope, never model-supplied IDs or metadata.
Check the matching active native tool item, allowed operation and connection epoch;
deduplicate calls without treating call IDs as credentials.

Local 0.154.0 zero-turn preflight accepted this API and rejected client invocation
of `item/tool/call`. It establishes no live security result. Experimental schema
generation exposes start tools, but not a resume attachment field; persisted-tool
resume must be tested. Check actual 0.165.0 Linux support and later repeat macOS.
Raise a minimum version only with measured capability evidence and an unsupported
diagnostic. Do not silently fall back to the rejected bridge.

The ADR's complete threat matrix is mandatory. Initially expose only read-only
context. With real model turns and unchanged fixture permissions/network=true:

- Verify distinct native coordinator/module contexts; reject forged argument IDs.
  Exercise a valid coordinator operation in the shared authorization dispatcher
  from a module, using a side-effect-free test handler.
- Prove no raw owner RPC through sockets, proxy/queue, remote ingress, inherited
  FDs, proc/dev-fd paths, process inspection/ptrace/pidfd, or other enabled tools.
  Test only disposable processes. A hidden PID is not the complete proof.
- Deny model writes to installed host code/config/role and epoch state, including
  symlink/path/import/restart injection. Run protected archive code with isolated
  imports, never mutable project Python or shared writable temporary code.
- Preserve native approvals: no automatic acceptance, session grants, new rules
  or approval reviewer. Tools cannot grant permissions or change the profile.
- Invalidate epochs on loss/restart, prove old runtime stopped, preserve unknown
  outbox, and test same-thread persisted tools/recovery without a second executor.

Grade every test PASS/FAIL/INCONCLUSIVE with protected native events and exact
commandExecution provenance. Python errors, timeouts and mutable JSON alone do
not pass a test. Only the complete gate permits step 3.

Separately test module Git fetch/branch/setup. Workspace-write protects `.git`
and resolved gitdir recursively; extra roots previously still yielded EROFS.
No host fetch/setup, relocated gitdir bypass, broadened profile, legacy Landlock,
sandbox disabling or automatic escalation is allowed. Preserve a required native
approval as WAIT for a human decision; record the request and any permission
delta. A broader-permission run does not satisfy unchanged-profile acceptance.
Without a compliant preparation path retain BLOCKED_GIT_PREPARATION even after
security PASS. The plan is not advance authorization to grant permissions.

## 3. Implement the narrow owner client and tools

Only after step 2 PASS, adapt `autonomy.py`, `codex_transport.py`,
`codex_adapter.py`, `runtime_commands.py`, the owner launcher and tool handler.
Use one multiplexed reader, serialized writes and independent routing of client
responses, server requests, notifications and human approvals. Avoid nested
synchronous RPC waits and state locks across runtime/model waits.

Reuse the existing scheduler and CLI contracts. Host operations are limited to
registered runtime/process observations, coordinator CAS/state operations, verified
queue delivery and idle compaction. Module authority covers only its assignment
transition. Bind receipts to assignment, worktree, config and generation with
integrity, expiry and replay protection. Collect observations outside short locks,
then revalidate CAS/current generation, pause/close/recover and freshness.

Keep branch/fetch/setup execution in the module command path. Host operations must
not execute project hooks, fsmonitor, setup or arbitrary code/paths. No generic
RPC/shell/filesystem, model/permissions/tool changes, merge/deploy/PROD or session
creation tools. The passive watcher shares the owner client without a new control
endpoint, persistent system service, empty-tick model calls or state churn.

This is explicit owner-launch, not transparent attachment to an existing desktop
runtime. Prove persisted tools before same-thread recovery. Fresh test sessions
are allowed at fixture setup; replacing an old session is not proof of reuse.

## 4. Preserve refusal and recovery guarantees

Retain the already implemented live/exited/unavailable distinction. Unavailable
observations, namespace/boot drift and stale identity cannot release assignments,
slots, locks or unknown outbox. Recheck evidence, runtime idle and CAS for cancel.
Disconnect/config drift blocks new work. Lease expiry does not authorize replay
or handover. Recover explicitly, reconcile unknown deliveries, then continue the
same assignment. Disabled tools give a clear owner-launch/refusal diagnostic,
not timer-driven model polling.

## 5. Regression and packaging gates

Cover forged roles/programs/threads, stale epochs/receipts, host code tampering,
loss/restart/PID reuse, early STARTED, duplicate TASK, outcome_unknown, pause/close
after signal, one restored watcher, idle ticks, dirty/waiting/config drift,
ACCEPTED-before-merge and changed native setup/config. Refusal must retain state.

Run all selftest/runtime/reliability/autonomy suites including all 15 Claude
regressions, `scripts/check.sh`, native smoke, extracted skill/plugin ZIP and
embedded Codex-copy suites. CI must pass Linux/macOS/native Windows/PowerShell
and reproducible archive comparison. Runtime bytes must match all deliveries.
Package owner-launch instructions and measured minimum versions. No Windows
live-cycle claim. Paid live diagnostics stay explicit and outside ordinary CI.

## 6. Same-archive live acceptance

Extend `scripts/test-orchestrator-autonomy-live.py`. Run real coordinator/two
module worktrees from one candidate commit/archive SHA256 on Linux and macOS.
Record each host's effective workspace-write/on-request profile, network and
runtime roots. The disposable private-repository owner driver sets up sessions,
observes facts and performs fixture PR/merge actions; it does not dispatch or
reconcile for the coordinator, approve requests automatically, or run module setup.

Require overlapping native turns for two independent WPs; a third WP reusing the
same thread/worktree with a new branch after squash merge and remote-branch
deletion; watcher → consume → coordinator dispatch without user dispatch; recovery
from lost notification/dependency completion; pause after queued signal; watcher
and owner-client restart without duplicate delivery; waiting/approval preservation;
completed same-runtime contextCompaction; negative sandbox probes; zero idle model
calls/journal/commit/state writes. Test Git preparation under the same permissions.

Save JSON verdicts, sanitized events, commit/archive hashes, launch commands,
approval requests/decisions, results and limitations. Archive disposable test
threads/repos and stop only created processes; remove test auth copies. If shared
changes affect Claude, rerun its Linux live scenario from this candidate too.

## 7. Deliver and report exact limits

Update autonomy/Codex workflow, resume/dispatch/close, EN/RU templates, CHANGELOG
and validation matrix. Explain dynamic tools, owner-launch, opt-in and disabling.
Preserve historical 0.13.0 Linux failure. Separately report API preflight, security,
Git preparation and autonomy E2E. Completion requires same-archive Linux/macOS
PASS and green checks with all original permission guarantees. Otherwise report
the exact reproducible blocker, without redefining PASS. Use the existing branch
and PR; no merge/release without a separate request.

Excluded: #23, early reuse after ACCEPTED, mixed clients, multi-host, permanent
services, automatic session creation, user PROD/databases and deployment.
