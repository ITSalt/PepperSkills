# ADR: STDIO MCP metadata does not authenticate the caller's role

30 October 2026. **BLOCKED: reject the privileged bridge as proposed.**
[Russian translation](2026-10-30-codex-stdio-bridge.ru.md).

The mandatory step 2 gate requires a supported, reliable caller/session/role binding
before moving coordinator operations outside the shell sandbox. A thread selected
by an RPC parameter cannot serve as that authentication.

## Observed counterexample

Real model calls in Codex CLI 0.154.0 on macOS and 0.165.0 on Linux supply native
thread, turn, call and item metadata to a STDIO MCP process spawned by the same
native App Server. This establishes transport availability, not caller authority.

A second probe runs in the actual module shell with the original fixture profile:
workspace-write/on-request, network_access=true. It uses the supported
`mcpServer/tool/call` endpoint to call only a read-only metadata tool on the
coordinator's MCP connection. It supplies the coordinator thread ID and arbitrary
`_meta` with forged turn/item/call IDs. On macOS the MCP tool receives those values
from its correct native parent, while the shell's real CODEX_THREAD_ID belongs to
the module. Native command stdout and the protected MCP host log corroborate this;
the writable report alone is not evidence.

The App Server schema accepts arbitrary `_meta`. The normal model path's
[metadata insertion](https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/mcp_tool_call.rs)
does not remove the other RPC path. [MCP transport documentation](https://learn.chatgpt.com/docs/extend/mcp)
does not promise an unforgeable per-role caller identity for this local interface.

Linux's tested sandbox denies the raw socket with EACCES. It also hides the live
host PID in a different PID namespace (ENOENT), while boot_id remains readable;
the proposed host-code directory is EROFS. Those denials establish this particular
Linux boundary, not common authenticated caller binding across both required hosts.

## Decision

A protected role table, parent PID/start proof, generations, signed receipts and
replay protection cannot repair a request initially attributed to the wrong role.
Binding a role to the target STDIO connection is insufficient: raw RPC selects that
connection. This is a failed trust assumption in an unshipped design, not a claim
that the host-owner App Server interface is itself a Codex vulnerability.

Step 2 blocks the privileged bridge and host-side scheduler changes. Experimental
bridge code is removed from the delivery. Linux keeps its safe observation refusal
and owner-launch workflow. There is no sandbox relaxation, legacy Landlock,
automatic escalation, raw-RPC capability grant or second resume process.

A separate Linux preparation probe also reports EROFS for the worktree's common
Git FETCH_HEAD. An isolated command/exec with the same workspaceWrite policy
reproduces it even with explicit .git/bare-mirror writableRoots. Fetch/setup was
not moved to the host. Git preparation remains an independent open acceptance item.

Continuation requires a proven authenticated initiator resistant to this RPC route,
or a separately approved and verified raw-RPC boundary. No such binding was proved
for the required 0.154.0/0.165.0 configuration. This says nothing about all future
versions. After resolving it, repeat impersonation/Git preparation probes and
steps 3–7. Independently safe cancellation/native-PID fixes can be reviewed now.

## Reproducer

```bash
python3 scripts/probe-orchestrator-codex-mcp.py --run \
  --skill plugins/pepper-orchestrator/skills/pepper-orchestrator \
  --model TEST_MODEL --output /tmp/pepper-mcp-proof.json
```

This explicit paid test isolates CODEX_HOME and exposes only `context({})` with a
read-only annotation. It never dispatches work, resumes a user thread, reads the
internal Codex database or supplies general host tools. It cleans up only its own
sessions/server/auth copy. Unexpected Python errors and timeouts are inconclusive,
not a PASS. See the [validation report](../validation/pepper-orchestrator-0.13.1-linux-gate.md)
for native evidence, immutable release baselines and the safe patch's checks.
