# Linux: explicit Git grants with the sandbox retained

**GIT_APPROVED_FIXTURE_PASS / AUTONOMY_NOT_RUN.**
[Russian report](pepper-orchestrator-git-approved-linux.ru.md).
[Evidence and hashes](evidence/orchestrator-git-approved-linux/README.md).

The owner selected sandbox + explicit Git permissions for a disposable Linux
fixture. Native CLI 0.165.0 successfully applies a restricted filesystem grant
while retaining workspace-write/on-request, user approvals, network=true and
separate module/coordinator runtime roots. No global config, service, installed
CLI, production program or shipped plugin runtime changed.

| Gate | Final verdict |
|---|---|
| Native filesystem request/decision; exactly six roots, turn scope | PASS |
| Fetch genuinely new upstream commit, new branch, module setup | PASS |
| Owner code/state, Git config, sibling metadata and control FDs remain protected | PASS for tested paths |
| New commands in the next turn lack the grant | PASS |
| Sibling command cannot inherit permissions while module grant is active | PASS |
| Same-thread restart does not restore the old grant | PASS |

## Actual permission delta

Only `features.request_permissions_tool=true` was added to the isolated native
fixture config. In the tested version it is under development and defaults off.
The model called native `request_permissions`; the owner validated native
thread/turn/cwd and the exact directory set, observed WAIT, then returned the
filesystem subset with `scope=turn`. The user authorized the fixture mode; the
bounded test controller resolved the native request. This was not a manual native
UI click and is not an auto-approval policy for real programs.

The six write directories are the module's private worktree gitdir, common object
database, its `refs/heads/gate/module` namespace and reflog, and the origin tracking
refs/reflog. Common config, hooks and the coordinator's branch/private HEAD stayed
read-only. The metadata is outside globally writable temporary roots, under the
protected fixture owner; only the selected worktree itself is a runtime root.
There is no umbrella-root workaround or relocated gitdir used to fake acceptance.

Before grant: all six write canaries give EROFS; fetch exits 255. With the grant,
fetch obtains a previously absent upstream commit and `git switch -c` creates
`gate/module/next` at that exact commit. Setup runs in the module shell. Ten
protected write attempts remain EROFS and owner/native control FD paths remain
ENOENT. Protected file hashes match. No native `require_escalated`, session grant,
`acceptForSession` or execpolicy amendment was accepted.

A protected owner barrier keeps the granted helper/turn alive until the sibling's
native command finishes. The event order proves owner grant → module command start
→ sibling command start/completion → module command completion. All six sibling
writes fail; after turn completion and after proven old-runtime termination/resume,
the same module's new commands also fail those writes. All helpers are finite.

## Surface and alternate ingress observations

[Native surface capture](evidence/orchestrator-git-approved-linux/surface-summary.json)
contains 13 tools. No generic owner App Server RPC tool exists. `process`,
`require`, `fetch`, `Deno` and `Bun` are undefined; actual `node:fs` and `node:net`
imports return `unsupported import in exec`. MCP server enumeration is empty,
remote control is disabled, and owner/descendant socket snapshots have no listener.
An actual default `codex queue` targeting the test coordinator, with the correct
isolated CODEX_HOME, fails to start an embedded server with EROFS. It does not use
an intentionally nonexistent explicit endpoint. Five requested native turns are
also exactly five observed starts: no extra executor/model turn was induced.

These facts supplement the earlier
[private-STDIO Linux evidence](pepper-orchestrator-private-stdio-linux-2026-10-30.md).
They narrow its missing code-mode/queue coverage; they do not establish safety of
all future CLI versions, additional tools or arbitrary enabled MCP servers. The
common step 2 gate remains open for macOS and final integration review. No privileged
scheduler, host project runner or general bridge is shipped by these probes.

## Reproduction, source and limits

From a clean source checkout, install both probes into a new protected owner
folder outside model-writable roots and shared temporary roots; run the owner from
an unrelated directory. Use only the host's existing local login. The authorization
flag is appropriate only after an operator has explicitly selected this disposable
fixture experiment. The owner guard rejects other subjects, roots, network/read
requests, special/glob targets and any command-escalation approval.

```bash
install -m 700 scripts/probe-orchestrator-private-stdio.py "$OWNER/"
install -m 700 scripts/probe-orchestrator-git-grants.py "$OWNER/"
python3 -I -S -B "$OWNER/probe-orchestrator-git-grants.py" \
  --run --authorize-fixture-git-turn --owner "$OWNER" \
  --model gpt-6.1-sol --output "$OWNER/report.json"
python3 -B scripts/test-orchestrator-git-grants.py
```

Executed final source: `50552a3`; source/library/native hashes are in the evidence.
The initial source `780cf09` made a harness error: `Client.approvals` is history,
so the next turn encountered the old resolved entry. It never sent a second grant.
That run stays incomplete. A regression now filters by current native subject/turn;
the new fixture independently passed all six gates. Both trials use the same model.
There were eight explicit/native turn starts total (three partial, five final),
two bounded grants and zero unsandboxed command acceptances.

Native terminal permissions retain launch settings: see version-pinned
[stdin review](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/core/src/unified_exec/stdin_approval.rs).
This trial tests new-command expiry, not revocation of a surviving background job.
Production integration must require finite preparation helpers, inspect active
terminals/processes before reuse and handle permission drift. Granted Git metadata
is mutable: host observations must pin registered paths and avoid project hooks,
filters/setup or trusting a writable gitdir pointer. No generic host Git runner is
introduced. macOS, full coordinator/watcher/reuse E2E and same-archive acceptance
remain required; the old unchanged-profile Git refusal is preserved.

Offline validation: 14 Git-grant tests, 11 private-STDIO tests and three MCP tests
pass locally. The Git-grant suite is wired into offline checks and the Linux/macOS/
Windows runtime CI matrix; no paid probe runs in CI. Prior full offline acceptance
and the shipped archive hashes remain unchanged; fresh CI is required for this
new diagnostic/test addition. No new package or full-autonomy release is claimed.

All persisted test threads were archived. The unused first-trial coordinator had
no rollout to archive. Auth copies were removed, known PIDs are gone, no process
with either owned fixture cwd remains, and the cleanup archive run used zero model
turns. No disposable GitHub repository was needed.
