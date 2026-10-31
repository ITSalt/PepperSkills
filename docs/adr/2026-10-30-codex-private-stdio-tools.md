# Owner-held App Server STDIO and native dynamic tools

30 October 2026, completed 31 October. **IMPLEMENTED AND RUNTIME-ACCEPTED IN THE
0.14.0 PREVIEW (Git-approved, on-request), LINUX/macOS.**
[Final same-archive acceptance and limits](../validation/pepper-orchestrator-0.14.0-private-owner.md). This supersedes the
implementation direction, not the evidence or rejection, in the
[MCP metadata ADR](2026-10-30-codex-stdio-bridge.md). See the
[execution plan](../plans/2026-10-30-orchestrator-codex-linux-acceptance.md) and
[Linux agent handoff](../plans/2026-10-30-orchestrator-linux-agent.md).

[Linux live follow-up](../validation/pepper-orchestrator-private-stdio-linux-2026-10-30.md)
verifies API, caller binding, fixture host integrity, pending approvals and
same-thread persisted tools on CLI 0.165.0. RPC/FD remains INCONCLUSIVE, Git
preparation BLOCKED for that unchanged-profile run.
The [selected Git-approved fixture](../validation/pepper-orchestrator-git-approved-linux.md)
now passes six native grant/Git/lifetime/isolation checks and adds actual tool
inventory/default queue evidence. The [macOS gate](../validation/pepper-orchestrator-private-stdio-macos.md)
now passes the measured threat matrix with the closed tool set and CLI 0.165.0.
Those are historical component results. The final linked report independently
accepts the integrated tools, Git-granted profile and lifecycle from one archive.
Native startup is additionally fenced by fixed actor project trust/discovery
session flags: module-controlled config/hooks/rules remain disabled even when
thread/start persists trust. Checking only the prior effective config was unsafe.
A stale wake-up is retired only during explicit recovery with matching protected
ownership history and positive previous-runtime exit; assignments are not replayed.

## Why this changes the trust boundary

The rejected design exposed an owner App Server endpoint. A module shell could
select the coordinator's MCP connection using `mcpServer/tool/call` and forge
`_meta`. Restricting MCP arguments, signing the resulting receipt, checking its
parent PID, or storing a role against that connection cannot fix this attribution.

Instead, an explicitly launched owner client holds anonymous stdin/stdout pipes
to one native `codex app-server --listen stdio://`. It receives experimental
`item/tool/call` **server requests** directly. There is no owner Unix/TCP listener,
shared-proxy attachment, file-based RPC inbox, or generic host RPC tool. Remote
control must be disabled and its effective state verified. Startup must reject
additional ingress into this same runtime. This explicit mode uses a separate protected CODEX_HOME; the user's global
configuration is not replaced or edited.

The owner registers a small dynamic tool set at `thread/start`, and records each
returned thread's role and allowed program/worktree in protected host state.
`threadId` and `turnId` come from the server-request envelope, never arguments,
environment variables, MCP `_meta`, stdout, or an editable JSON file. A matching
native `item/started` event, active turn, known tool and connection epoch are
required. Call IDs scope deduplication; they are not secrets or authentication.
Unknown roles, stale epochs, duplicate calls and unregistered threads fail closed.

The authority is the private channel plus runtime-generated context. Dynamic
tools by themselves are not an authentication mechanism. If a model can obtain
the pipes or another owner API connection, this proposal also fails the gate.

## Evidence available now

- Official [protocol](https://learn.chatgpt.com/docs/app-server#protocol) documents
  STDIO. [Dynamic tools](https://learn.chatgpt.com/docs/app-server#dynamic-tool-calls-experimental)
  are experimental, including `dynamicTools` and the server-request flow.
- In version-pinned 0.154.0
  [event handling](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/app-server/src/bespoke_event_handling.rs),
  `DynamicToolCallParams` uses the owning conversation ID and event turn ID,
  separately from tool arguments. The
  [handler](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/handlers/dynamic.rs)
  registers a pending native tool item. The
  [STDIO transport](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/app-server-transport/src/transport/stdio.rs)
  reads stdin; the App Server's transport match selects this instead of the Unix
  or WebSocket listener. None of this proves descriptor isolation on a host.
- A local **zero-model-turn** 0.154.0 preflight accepted experimental initialize
  and ephemeral `thread/start` with a read-only dynamic tool, workspace-write and
  on-request. An incoming client `item/tool/call` was rejected with -32600.
  [Sanitized result](../validation/evidence/orchestrator-linux-gate-20261030/private-stdio-preflight.json).
  Its default network=false is not the original live fixture's network=true;
  this result makes no sandbox-isolation or live-tool-call claim.
- Experimental schema generation is necessary:
  `codex app-server generate-json-schema --experimental --out SCHEMA_DIR`.
  In the tested 0.154 schema, `thread/start` has `dynamicTools`, while
  `thread/resume` has no field for attaching them. Persisted-tool resume still
  needed a real test. The follow-up above now verifies persisted-tool resume on
  Linux 0.165.0; it does not close the overall security gate.

## Required security gate before privileged operations

Initially expose only `pepper_context({})`, returning nonsecret identity facts.
Use real coordinator and module turns with the original effective permissions,
including fixture network=true. A module must not acquire coordinator authority:

1. Forge nested thread/turn/role/call fields; request coordinator-only operations
   from its own native tool call. Reject without writes. Schema rejection alone
   does not test authorization: test the shared dispatcher with a valid operation
   name assigned to the wrong actor, while keeping its handler side-effect-free.
2. Try raw owner RPC, CLI queue/proxy and reachable alternate transports for this
   runtime. Check no listener and remote ingress; unrelated existing services do
   not prove access to this server. Do not weaken the sandbox to run a probe.
3. From actual model shell commands, try own inherited descriptors, host-process
   descriptors through `/proc`/`/dev/fd`, accessible proc roots, `pidfd_getfd` or
   ptrace-equivalent access where available. Never write arbitrary RPC to a user
   process. Target only the disposable owner/native server, using read-only
   identity operations. Preserve errno and native command events. A host PID
   hidden in one namespace is useful evidence, not the whole test.
4. Try writes to installed host code, configuration, role/epoch tables, receipt
   state and restart inputs. Check symlink/path traversal and import/environment
   injection. Default shared temporary directories are not protected code roots.
5. Verify native approval requests remain pending without a human decision;
   tools and watcher cannot grant them. Test disconnect, old-epoch replay, and
   restart without a concurrent second executor of any persisted thread.

Host code runs from an owner-installed verified archive outside writable model
roots, with an isolated interpreter/import path. It never executes code imported
from a mutable worktree. Owner state and role/path registration live outside
those roots. Readable state is not treated as a secret capability. `chmod 0600`
and a token in environment or a readable file are not sufficient isolation.

Approval handling is a separate owner UI path. It must not default to `accept`,
`acceptForSession`, permission grants, rules amendments or automatic review.
Dynamic tools cannot change approvals, sandbox, model, tools, hooks or sessions.
Only explicitly opted-in coordinator state operations and registered queues are
eligible; module operations are limited to their current assignment transition.
No arbitrary method, command, path, shell, setup, merge or deployment tool exists.

## Lifecycle and implementation consequences

The host client needs a single multiplexed reader and serialized writer, bounded
request queues and no global lock held during model/RPC waits. Notifications,
server requests, approval prompts and outstanding client responses must progress
independently. The existing synchronous transport cannot simply call itself from
a tool callback. All tools reuse the portable scheduler and its CAS/outbox logic;
the host adds observation/validation, not another scheduler. The watcher is passive
and uses this owner client, without a new public control endpoint or empty ticks.

This is an explicit owner-launch mode. It cannot silently attach private pipes
to an existing desktop/Unix server. Start test threads once; reuse them in that
same runtime. Recovery must prove the old runtime stopped, verify persisted tool
availability, invalidate epochs and reconcile unknown outbox before continuing.
If attaching tools to old threads is unsupported, report that limit; creating a
new thread is not acceptance of same-thread recovery/reuse. No automatic session
creation or second resume process is introduced by the scheduler.

After security PASS, wire host observations, `next`, consume/dispatch, transition,
cancel, recover and compaction to this same runtime. Protect host execution from
project Git hooks, fsmonitor, configurable setup, arbitrary paths and mutable
configuration. Keep all actual project preparation in the module's native command
path and all existing cancellation/outbox retention guarantees.

## Independent Git gate and honest acceptance

The default workspace-write policy
[protects `.git` and resolved gitdir recursively](https://learn.chatgpt.com/docs/agent-approvals-security#protected-paths-in-writable-roots).
Adding a writable root is not proof that fetch/index/ref writes are allowed.
Do not move Git state to evade protection, fetch on the host, broaden a profile,
disable sandboxing, or auto-approve a request to make a test green.

Test module fetch, branch preparation and setup separately. If the native client
requires owner approval, preserve WAIT and report the exact request. A genuine
human decision through the normal on-request mechanism is distinct from automatic
approval; record any permission delta and decision, and do not infer authorization
from this plan. A run requiring broader permissions cannot satisfy the original
unchanged-profile gate. If no compliant path exists, retain BLOCKED_GIT_PREPARATION.

Only live negative probes can close step 2. Only all Git/lifecycle/E2E gates and
same-archive Linux/macOS acceptance can establish autonomy PASS. Security PASS,+API availability and autonomy PASS must remain separate verdicts.
