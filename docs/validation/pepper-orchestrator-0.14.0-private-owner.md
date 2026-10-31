# Private owner 0.14.0: Linux/macOS acceptance

31 October 2026. **Runtime PASS (Git-approved, on-request)** on Linux and macOS
from the same immutable archive. This is the pre-release acceptance snapshot. [Public release packaging](pepper-orchestrator-0.14.0-release.md) separately records documentation changes and new ZIP hashes.
[Русский](pepper-orchestrator-0.14.0-private-owner.ru.md).
[Native evidence and executable probes](evidence/orchestrator-private-owner-0140-20261031/README.md).

The implementation connects the existing portable scheduler to a session-owning
App Server through private STDIO. It explicitly launches a fixed coordinator and
two module threads; it does not attach to a desktop runtime. Modules perform Git
preparation inside their native sandbox. Production approvals remain owner console
commands. No privileged MCP bridge, public RPC endpoint, file-command inbox,
detached service or automatic production approval is installed.

## Artifact and measured hosts

Packaged runtime commit: `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d`.
Evidence/test-driver commit ee8a6fc preserved these packaged bytes. Release documentation was updated later; the hashes below identify live acceptance, not the rebuilt public release.

| Artifact | SHA256 |
|---|---|
| Plugin ZIP, 0.14.0 | `57722062c318161abc7e477b9ae06e584289849743e83bd618b76ac8d4a4253a` |
| Standalone skill ZIP, 0.14.0 | `7bc64b887591f175097d3aff2f149d7940403ce71c64fc0dfc64079333d89cab` |

| Host | Native CLI | Python | Native executable SHA256 |
|---|---|---|---|
| macOS 27.0.1 arm64 | 0.165.0, isolated official npm binary | 3.14.5 | `a45099154d7fb4a5ed8a56f40966a95deb938e508bab23e6985035c709e9a85a` |
| Linux 6.8.0-147, x86_64, glibc 2.39 | 0.165.0, native executable | 3.12.3 | `c06a67fd8ac76508dc78bd99ce20c9f317b8d568beda59485f3f4134df9962d5` |

Both ran gpt-6.1-sol/high. Effective profiles retained workspace-write,
on-request, reviewer=user, network=true, no extra base writable roots and one
runtime workspace root per actor. Remote control was disabled and MCP empty.
The macOS global CLI/config and existing Linux checkout were not changed.

## Results

| Gate | Linux | macOS |
|---|---|---|
| Actual native caller roles; module cannot invoke coordinator operation | PASS | PASS |
| Closed tool surface, no Node/process/network globals or fs/net imports | PASS | PASS |
| Owner code/config/roles/program/receipt, foreign Git metadata, FD/process probes | PASS | PASS |
| Hardlink/symlink aliases during a real Git grant | PASS | PASS |
| Exact native permission request, WAIT, six Git roots, turn scope | PASS | PASS |
| Native module fetch/new branch/setup and provenance-bound STARTED | PASS | PASS |
| New-turn and restarted-runtime Git-grant expiry | PASS | PASS |
| Explicit exec workdir outside actor root cannot acquire protected write FD | PASS | PASS |
| Native apply_patch against owner canary is refused | PASS | PASS |
| Watcher → consume → coordinator dispatch; independent turns overlap | PASS | PASS |
| Third WP reuses same thread/worktree after squash merge and remote deletion | PASS | PASS |
| Pause after queued signal; no assignments while paused | PASS | PASS |
| Restart with an actually pending native consume; retire stale wake-up only | PASS | PASS |
| Lost merge notification recovered by fresh scan; no duplicate assignments | PASS | PASS |
| New completed native contextCompaction on the owning loaded server | PASS | PASS |
| Enabled idle ticks: zero model turns and unchanged program/runtime files | PASS | PASS |
| Shipped owner console --resume/status/pause/stop; same threads, generation +1 | PASS | PASS |
| Project MCP startup canary, including redirected commondir, zero models | PASS | PASS |

Each host completed WP-A-02, WP-B-02 and dependent WP-A-03. Review confirmed the
exact head in a private disposable GitHub repository before squash merge; remote
branches were deleted. A's second assignment used its original native thread and
worktree. The driver performed owner bootstrap/review/merge, not coordinator
dispatch or module preparation.

The restart test held an actual native consume request before its handler,
paused the program, stopped the native runtime, and proved descendant exit. The
new owner resumed the same three thread IDs. Only after matching protected
ownership history and positive old-process exit did it retire the stale wake-up
and require a fresh scan. Assignment IDs and unknown delivery outbox were retained;
there was no TASK retry. Exactly three assignments were created.

Native model turns started in the main acceptance: macOS **23**, Linux **28**.
Each shipped-console smoke added three explicit startup context turns and one
coordinator watcher turn; no module replacement or native approval occurred.
Archive/unarchive cleanup helpers used zero model turns.

## Permissions and security corrections

This accepts the owner's selected **Git-approved** fixture mode. Each host had
**three bounded test-controller grants**, each through native request_permissions
for exactly six canonical Git metadata directories and scope=turn. The controller
recorded WAIT before applying the owner's selected fixture policy. Native manual
UI clicks: **0**; these are not claimed as three manual human confirmations.
Each host also recorded one native file-change request and explicit test decline.
Production owner_main never auto-approves; unrelated requests and session grants
are refused. No blanket Git rule or unsandboxed retry was used.

The helper's JSON is not authority: prepared requires the exact completed native
command argv/cwd/turn, protected nonce, assignment/generation, current Git facts,
configuration and helper hash. Expiry/workdir probes also require exact native
command provenance; echoed JSON/path mentions cannot pass the grader.

A zero-model control found a defect after earlier functional PASS runs: effective
config/read omitted an untrusted project layer, but thread/start persisted trust
and started that project's owned MCP canary. Checking effective config alone was
insufficient. The final client pins project_root_markers=[] and untrusted trust
entries for every fixed actor cwd as native session flags, above persisted trust.
Actor-owned config/hooks/exec rules stay disabled before loading; start, resume
and compaction inspect layer metadata and refuse an active project layer. The
final canary remained unstarted on both hosts, also after commondir redirection.
The native filesystem/approval profiles were unchanged. This follows the native
[configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic#configuration-precedence)
and the version-pinned [layer/trust implementation](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/config/src/loader/mod.rs).

Other corrected failures: native failed/exitCode=1 is a finished command, while
missing exit status still blocks reuse/recovery; isolated config is pinned after
native bootstrap trust records rather than compared with the initial template;
Codex entrypoint versions now synchronize from the canonical manifest.
Earlier candidate results do not certify this final artifact.

## Regression, cleanup and limits

Local scripts/check.sh completed from an immutable checkout with protected build
code/temp roots: core selftest, 11 runtime, 19 reliability, 41 autonomy including
15 Claude cases, 20 owner, three adversarial command-provenance regressions,
protocol/grant/macOS suites, extracted ZIP/generated Codex-copy suites, component
checks, deterministic builds and read-only-source checks.
CI status is recorded in `evidence/orchestrator-private-owner-0140-20261031/ci.json`.

Claude Code 2.1.312/sonnet, its existing auto permission mode, also passed the Linux
live scenario from this same archive: parallel work, same-session reuse and
confirmed PostCompact receipt. Its fixture and controller lived outside shared
temporary/model write roots. This is a Claude compatibility result, not an
assertion that its permissions equal Codex's kernel sandbox.

All disposable repositories were archived; known native descendants and Claude
session PIDs exited, native test threads were archived and test auth copies
removed. Raw local logs remain private; exported aliases/hashes preserve the
native authority envelope and event order without reasoning/account telemetry.

Scope is the explicit closed owner mode on native 0.165.0. Actor-owned native
config/hooks/rules and required MCP are unsupported in this mode. Arbitrary host
UNIX services/network connectivity remain outside the private-owner IPC claim;
network=true was preserved. Turn expiry applies to new commands, not revocation
of a surviving background terminal's launch rights. Use finite setup and inspect
retained processes; unknown native command lifetime blocks reuse/recovery.
Windows has offline/native core smoke, no private-owner live acceptance.

The public 0.13.0/e1134fd Linux safe refusal remains historical and unchanged.
This candidate does not turn that old unchanged-profile Git blocker into PASS.
[Owner setup, manifest, opt-in, disabling and recovery](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/private-owner.md).
No PepperSkills PR merge, release, deployment or production change was performed.
