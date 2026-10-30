# Codex Linux acceptance gate — 30 October 2026

**Plan outcome: BLOCKED at mandatory step 2. Linux autonomy is not accepted.**
Candidate 0.13.1 contains an independently reviewable cancellation/diagnostic safety
fix. No privileged MCP bridge is shipped. No public release, user-program activation,
permission relaxation or PROD/database/deployment operation was performed.
[Russian translation](pepper-orchestrator-0.13.1-linux-gate.ru.md).

Follow-up planning: [private STDIO proposal](../adr/2026-10-30-codex-private-stdio-tools.md)
has only a zero-turn API preflight. Live security/Git/E2E gates remain open;
the results and candidate archive hashes in this report are unchanged.

## Reproduced blocker

A real macOS module shell, CLI 0.154.0, workspace-write/on-request and
network_access=true calls only a read-only metadata tool on another test thread's
MCP connection through `mcpServer/tool/call`. It supplies the coordinator's thread ID
and arbitrary turn/item/call metadata. The MCP tool sees those values from the
correct native App Server, while the caller shell remains the module.

[Native evidence](evidence/orchestrator-linux-gate-20261030/macos-mcp-caller-binding.json)
records `same_native_parent=true`, `thread_turn_binding=true`,
`native_report_matches_file=true`, but `shell_cannot_impersonate_coordinator=false`:
**BLOCKED**. The exact successful native command event and the protected host MCP
log corroborate the counterexample. An editable report is not accepted alone.
Unexpected Python/transport failures never count as proof of isolation.

[Linux CLI 0.165.0 evidence](evidence/orchestrator-linux-gate-20261030/linux-mcp-caller-binding.json)
shows native metadata is available and raw shell RPC is denied. This is a PASS of
a narrow current transport/isolation probe, not of Linux autonomy or common caller
authentication. [ADR and the missing trust boundary](../adr/2026-10-30-codex-stdio-bridge.md).

## Immutable release baseline and candidate matrix

Release commit/tag: `e1134fdf92346a2911163042b74d8a47b7831b46`,
`pepper-orchestrator-v0.13.0`. Downloaded release assets match SHA256SUMS:

```text
4c1e9ace0e0f528df998cadef090ddab17dd091da83aefdc9ed01d9480d37e68  pepper-orchestrator.plugin.zip
b72ade91dae2b05a43ff76b1e48c180783ee05d89985ba2e45af7bf02afcf0d4  pepper-orchestrator.zip
```

| Check | Original 0.13.0 | 0.13.1 safety-fix candidate |
|---|---|---|
| Codex macOS live cycle | [PASS](evidence/orchestrator-linux-gate-20261030/release-0.13.0-macos-live.json): 3 WPs, overlapping turns, reuse after squash merge/deleted branches, compaction | New common E2E is not claimed after the step 2 stop |
| Codex Linux live cycle | [WAIT / safe refusal](evidence/orchestrator-linux-gate-20261030/release-0.13.0-linux-live.json), no assignments | Autonomy remains blocked |
| MCP 0.154.0, macOS | Metadata exists but raw RPC can impersonate the target role | Privileged bridge excluded |
| MCP 0.165.0, Linux | Metadata exists; shell raw RPC is denied | Diagnostic evidence only |
| Cancellation after observation denial | Error became `still_live=False` | Refuses; reservations and unknown outbox remain |
| Claude | Historical Linux live in the 0.13.0 report | All 15 mandatory regressions retained; no replacement claim for a new live run |

An initial macOS baseline stopped on global configuration drift. The accepted
repeat used an isolated CODEX_HOME, copied authentication only, loaded no unrelated
user MCP servers, and removed that auth copy afterward. Release bytes and historical
Linux refusal are unchanged. Current model fixtures explicitly used `gpt-6-astra`.

## Linux localization

[Coordinator and both module shell probes](evidence/orchestrator-linux-gate-20261030/linux-shell-boundary.json)
show socket EACCES/13, hidden host PID ENOENT/2, different PID namespaces, readable
boot_id and EROFS/30 for host-code writes. Host-side observation of that same runtime
works. Owner/consume, compatible/next, transition, watcher/recover and compaction all
need the same runtime/process proof; one successful socket check is insufficient.

The experimental transition also found Git FETCH_HEAD EROFS. Explicit .git and bare
mirror writableRoots did not remove it in the isolated same-policy command/exec.
Project fetch/setup never ran on the host. Intermediate macOS prototype success is
not accepted as a secure bridge result; that code is removed from source/packages.

## Safe implementation and validation

Cancellation now distinguishes live, positively proven exited and unavailable.
Namespace/boot changes, denied access, timeouts and malformed confirmations retain
assignments/outbox/slots/locks. Known stopped processes still permit cancellation
through the existing evidence, idle and CAS gates. Old Linux confirmations need
explicit reattachment. Official npm shims resolve directly to the native App Server
binary; native smoke verifies executable format. Fetch diagnostics redact HTTP
userinfo. The live driver isolates config and records/validates archive provenance.

Verified runtime snapshot: `6d59bfac32da3dd3985ea021b9645d346adad5a0`.
The subsequent report/translation update changes no shipped file.

| Check | Result |
|---|---|
| Full local `scripts/check.sh` | PASS; no source changes |
| Autonomy | 41 tests, including all 15 Claude regressions |
| Read-only probe | Three offline regressions PASS |
| Extracted skill/plugin ZIP and embedded Codex copy | All selftest/runtime/reliability/autonomy suites PASS; identical canonical runtime |
| Native transport | macOS CLI 0.154.0 PASS; executable format verified |
| [CI](https://github.com/ITSalt/PepperSkills/actions/runs/41033211497) | All seven jobs PASS: Linux Python 3.10/3.12, macOS Python 3.12, runtime Linux/macOS/Windows, native Windows/PowerShell and package comparison |
| Reproducibility | Linux/macOS/local hashes match; also equal the [native Windows tested archives](https://github.com/ITSalt/PepperSkills/actions/runs/41033211497/job/123987673786) |
| Privacy/cleanup | User configs contain no test MCPs, no test auth copies remain, all nine disposable GitHub repositories are archived |

A separate isolated shared-proxy check on both versions closed before initialize:
these fixtures have no shared daemon, so proxy ownership of the explicit runtime is
not claimed. Real tests use its exact Unix endpoint.
[Proxy observations](evidence/orchestrator-linux-gate-20261030/shared-proxy.json).

The unreleased candidate archives contain only this safe patch and shared runtime:

```text
8783133d206664931f2478b817e02f05388abe7da11e95e3f81728b6cc8dde2c  pepper-orchestrator.plugin.zip
08cd36def0d0a2885a3c7b639a2dbff08282717047fda3c492ea0d12db104204  pepper-orchestrator.zip
```

These hashes are not a publication or Linux E2E acceptance. Diagnostics are explicit
paid runs, outside CI. Disposable test repositories were archived and only created
processes were stopped. Tests do not mutate user programs, PROD or databases.

## Remaining gate

Steps 3–7 are not declared implemented/accepted as autonomy. Continuation needs a
proven non-forgeable MCP initiator or separately agreed raw-RPC boundary, then Git
preparation and a same-archive Linux/macOS E2E. No fallback changes permissions,
launches another executor or treats lease expiry as authority. #23, mixed clients,
multi-host, early reuse, permanent services, Windows live and PROD remain excluded.
