# Linux agent prompt: private STDIO security and Git preparation gates

[Russian translation](2026-10-30-orchestrator-linux-agent.ru.md).
Copy the text below into a Linux coding-agent chat. This task does not yet
authorize privileged scheduler implementation or declaring Linux autonomy PASS.

---

Investigate PepperSkills Codex Linux autonomy without weakening sandbox/approvals.
Use repository `ITSalt/PepperSkills`, branch `codex/orchestrator-linux-acceptance`,
draft PR #42. Locate the existing checkout, inspect instructions and git status;
preserve user changes. Fetch the branch and record exact HEAD; required ancestors
are `6d59bfa` (safe cancellation) and `35b3626` (gate report). Read these updated
files from the branch; if absent, request the updated files before testing:

- `docs/plans/2026-10-30-orchestrator-codex-linux-acceptance.md`
- `docs/adr/2026-10-30-codex-private-stdio-tools.md`
- `docs/adr/2026-10-30-codex-stdio-bridge.md`
- `docs/validation/pepper-orchestrator-0.13.1-linux-gate.md`

The old design is disproved: a real module shell on macOS could call another
thread's MCP connection through `mcpServer/tool/call` with forged `_meta`.
Linux socket EACCES alone did not establish common caller authentication. Do not
reinstate that bridge. Test the new candidate: an owner client owns anonymous pipes
to one native App Server `--listen stdio://`, no owner socket/proxy/remote ingress,
and receives native dynamic-tool `item/tool/call` requests. Role comes from protected
thread registration and native envelope, not tool arguments. This is a hypothesis
pending live isolation evidence, not a claim that dynamic tools authenticate callers.

Allowed: disposable local fixtures and explicit minimal model-backed probes needed
for this gate, using an available frontier model; record the exact model and call
count. Do not change the model midway to hide failure. Use a throwaway CODEX_HOME
without unrelated tools; use only existing local login credentials, never ask to
transfer secrets. Remove any test auth copy afterward. Do not alter global config,
installed CLI, services, user sessions/projects, PROD/DB, release or merge anything.
No disposable GitHub repo is needed for these first probes: a local bare remote
and two worktrees suffice. Do not create separate chats or delegate this task.

1. Record OS/kernel/Python, every PATH Codex executable, actual native binary/hash,
   version and effective permissions. Previous Linux was CLI 0.165.0, not a promise
   about this machine. Generate `app-server generate-json-schema --experimental`
   and inspect help/schema for initialize experimentalApi, dynamicTools, native
   server requests, approval handling, remote control and persisted-tool resume.
   Start with a no-model preflight. Do not assume current docs imply old support.
2. Build a minimal reproducible read-only probe, not a production bridge. Its owner
   code/imports/config/role table/logs must be outside model-writable roots; use
   isolated imports, no project hooks. Run one App Server over private STDIO, one
   coordinator and one module. Register only `pepper_context({})`. Preserve actual
   workspace-write/on-request and the prior fixture's network_access=true, with
   runtime writable roots recorded. Do not obtain a PASS by restricting network
   compared with that fixture. Disable/verify alternate ingress to this server.
3. Have both real model turns call context. Save native item-start/request/completion
   envelopes and correct distinct actor mappings. From the module try forged IDs
   in arguments and a coordinator-only operation through the shared dispatcher
   with a side-effect-free handler. Authorization must reject before any mutation;
   testing only JSON schema rejection is insufficient.
4. From real module shell commands, probe owner RPC and descriptor acquisition:
   sockets/CLI queue/proxy/remote ingress, inherited FDs, `/proc`, `/dev/fd`, other
   accessible proc roots and ptrace/pidfd access where supported. Target only your
   disposable processes with read-only identity operations. Test any other enabled
   tool that could reach owner RPC. Show no control listener for this runtime;
   localhost assumptions and chmod are insufficient. Test host code/state write,
   symlink/path/import/restart injection. Do not weaken sandbox for these probes.
5. Verify native approvals wait without an owner response. Never auto-accept,
   acceptForSession, amend rules or grant permissions. Unknown server requests
   fail closed. Disconnect/restart: invalidate epochs, prove old runtime stopped,
   resume only the same test thread without a second executor, verify persisted
   tools and stale-call rejection. Report unsupported resume honestly.
6. Independently reproduce Git fetch/new-branch/setup in the module shell with the
   same profile, using the local bare fixture. Record exact `.git`/resolved-gitdir
   paths, write denial and any native approval request. `.git` was EROFS even with
   extra writable roots. Do not move gitdir, fetch/setup on host, alter protected
   paths, change roots/profile to bypass denial, disable sandbox or grant requests.
   If approval is needed, preserve WAIT for the human and report its exact scope;
   this prompt is not authorization to approve it. No broader-permission run can
   close unchanged-profile acceptance.

Save a small reusable probe, offline tests for its verdict/provenance logic, and
sanitized evidence under `docs/validation/evidence/`. Owner-native events plus the
exact successful/failed commandExecution are authoritative; model-written JSON
alone is not. Timeout, Python exception or unsupported syscall is INCONCLUSIVE
for that probe, not a security PASS. Give separate verdicts for API availability,
caller binding, RPC/FD isolation, host integrity, approvals, recovery and Git.

Stop before production integration. If every security subgate passes, report
`LINUX_SECURITY_GATE_PASS / AUTONOMY_NOT_RUN`; recommend implementation steps 3–7 and
explicitly note that macOS negative probes are still required before common host
operations ship; the common step 2 gate is not closed by Linux alone.
If Git has no compliant path, report BLOCKED_GIT_PREPARATION
independently. Any security FAIL/INCONCLUSIVE keeps §2 BLOCKED. Never label this work Linux autonomy
PASS: that requires same-archive Linux/macOS full acceptance from the plan.

Run relevant offline checks, clean up only your processes/threads/auth copies,
keep sanitized logs, and provide the patch/commit with launch commands and a concise
report I can relay to the planning agent. No push, merge, release or external
messages are needed. In your report answer: which assumptions were proved, which
failed, exact native policy/approval state, remaining blocker and next safe action.
