# Codex CLI adapter and common runtime (0.14.0 candidate)

For explicit private-STDIO owner launch on Linux/macOS, follow
[private owner setup and recovery](private-owner.md) ([Русский](private-owner.ru.md)).
Use its typed tools rather than detached shell commands for active owner operations.
This candidate remains unreleased; host acceptance is recorded separately.

The owner launches independent module sessions. One coordinator writes `status.md`
and decisions; module sessions implement WPs in their own Git worktrees. Preserve
the common methodology: evidence before verdicts, owner authority, no module code
edits by the coordinator, no merge/production/database/permission operations by
module sessions or reviewer roles; coordinator delivery only under an explicit D-n, and file-based recovery. Messages do not approve permissions or prove work.
Read common concept sections 1, 2 and 12 for these boundaries; use this document
for Codex models, roles, launch, messaging and recovery instead of Claude mode texts.

Portable `plugin.json` hosts always discover the canonical `skills/` directory;
their entrypoint explicitly routes Codex to this workflow before any Claude modes.
The `.codex-plugin` manifest selects the dedicated Codex entrypoint when used as
a native compatibility package. Manual Codex skill copies from the plugin ZIP use
that dedicated entrypoint with the same generated resources. Neither route changes
Claude instructions or creates another editable runtime implementation.
See [portable plugin component discovery](https://developers.openai.com/plugins/build/plugins).

## Autonomous continuation

Follow [local autonomy](autonomy.md) (Codex transport) for ownership, discovery/attachment,
reuse, automatic dispatch, observation, start acknowledgements and recovery.
Existing programs remain opt-out until the owner enables autonomy. When enabled,
resume and lifecycle events run `next --json`; dispatch eligible packages yourself.
For a new terminal, reserve through `dispatch --owner-launch` and give the owner
the generated launch command. Do not ask the owner to invoke /dispatch.

## Modes

- `init`: confirm the owner's language and program scope. Run `orch.py init NAME
  --lang ru --client codex --sessions local --repo app=/absolute/repo@main
  --area frontend=app:src/frontend/** --area backend=app:src/backend/** --dir
  /absolute/coordinator/features/NAME`. The coordinator is in its own repository
  or an explicit `orch/NAME` worktree. Generated launch descriptors override only
  explicit Codex launch settings, keep the user's model by default and do not edit
  user configuration. `codex` settings (`approval_policy`, `sandbox_mode`,
  `required_mcp`, `models`) are separate from `permission_mode` and Claude `models`.
  Owner choices can set Codex settings in orch.yaml. Do not translate Claude rules
  into assertions of equivalent Codex protection. Native rules are additive;
  repository branch protection is still required.
- `plan`: inspect repositories and both project instruction files; delegate scoped
  evidence gathering to `pepper_scout`. Record dependencies, completion criteria,
  module paths, tests, resources, rollback and evidence in WPs. Product forks
  become P-n with options; answers become D-n. Use `new-wp`, not hand-generated IDs.
- `dispatch`: `orch.py dispatch WP --dry-run` checks paths, dependencies, locks,
  CLI capabilities, launch descriptors and configured required MCP. Installation
  alone does not prove a required tool is available or authorized. `prepare WP`
  fetches and creates an ordinary Git worktree and branch; the owner runs the
  printed start command. It never relies on `codex --worktree`. Module sessions
  read both instruction files; paired-file drift is advisory unless instruction synchronization is explicit WP scope.
  Register the thread ID from `/status` with `session register --wp WP --thread ID
  --worktree PATH`. TASK delivery to an existing session uses `session send
  --wp WP --message-file task.txt --request-id KEY`; it uses `codex queue`.
  Only proven non-delivery permits manual handover. Unknown outcomes retain the
  reservation and require recipient/Git reconciliation. With autonomy enabled use
  structured dispatch and assignment IDs from the autonomy protocol.
- `review`: verify PR/head SHA and tests, run `review-start WP --pr URL`, delegate
  the exact contract/head/base to `pepper_reviewer`. Use a disposable review clone
  for tests that write; never the implementer's active worktree. Collect evidence
  in the report. Record ACCEPTED only after verification; REVISE gives concrete
  findings to the same module session through queue. Review only the revision diff
  plus unresolved findings on resubmission. After repeated failure ask the owner
  to select a stronger Codex model unless `codex.models.escalate` is explicit.
- `verify`: `verify WP --env test|prod` verifies deploy/served SHA/commands without
  deploying. Delegate the agreed live scenario to `pepper_verifier`, with actual
  required browser/MCP/skills. Automatic PASS remains VERIFYING until `verify finalize`; WAIT keeps status; failures create BUG IDs and owner
  items as needed. Acquire stand/port/migration-application locks on demand.
- `deliver` / `release`: use the shared trusted-delivery CLI and gates, following
  [delivery safety](delivery-safety.md). Merge/stand/prod/prod_migrations default to owner
  and require explicit owner decisions. Only the coordinator invokes these commands;
  native roles and module sessions never deliver. A pending live scenario blocks the
  next merge and PROD. Never use direct merge tools, bypass approvals, change the
  user sandbox or enable production MCP. A permission refusal becomes an owner item.
- `resume`: read all state and decisions, lint, inspect registered sessions with
  `session list` (Git checked) and `session read --wp WP` (documented App Server).
  For enabled autonomy also run `autonomy resume` with the current coordinator
  identity/generation, then `next --json`; consume pending signals before acting.
  Compare thread history with PR/head/CI and Git; do not derive state from messages,
  a TUI screen or Codex's internal database. Queued messages may be notifications
  for an idle thread; verify consumption with history before relying on them.
- `owner`: show open items via `queue`; provide exact command and expected result.
  Verify facts before closing an item. Only the owner's actual answer is consent.
- `decide`: use `decide D|A|Q TEXT`; assumptions have validation and questions stay
  unresolved until answered. `owner add R|P` creates actions/questions.
- `close`: `close --check`, verified completion/closed PRs, closeout/backlog report,
  then `close --apply`; retain existing archive behavior. Stop writing sessions.
- `reopen`: record reason; preserve branches, IDs and decisions.
- `report`: anonymize plugin defects; public Issue still requires the owner's yes
  or the existing explicit auto-report decision. Never patch an installed plugin.

## Roles, skills and tools

`settings all` adds native `.codex/agents/pepper_{scout,reviewer,verifier}.toml`
to the coordinator workspace. Existing customized role files are preserved and
require explicit review. Roles have no hardcoded model; they inherit the user's
model, MCP and skills unless explicitly configured. Each has read-only sandbox
and behavioral limits; the parent's live permission policy still constrains them.
Role-specific MCP/skills can be configured in the native role files by the owner.
Missing tools are a reported limitation, never synthetic evidence. Required MCP
IDs in `codex.required_mcp` must be configured/enabled before dispatch; connection
and authorization must also be checked by the session before the relevant task.
Production MCP servers explicitly declared under environments.prod are disabled
at launch for all generated Codex sessions.

## Sequential client switch

One program has one active client. Stop old writers, use `session stopped --wp WP
--evidence "owner stopped PID/session ..."`, then `client switch --target codex
--stopped-evidence "owner stopped all previous writers"`. Unregistered old sessions
must also be stopped: the owner statement covers them. `--target claude` restores
Claude. Per-client WP model assignments are preserved separately; no automatic
mapping of Sonnet/Opus to an OpenAI model. Existing WP text/branches/decisions/IDs
remain. New launch commands are generated for the active adapter. V1 is local and
sequential; mixed clients, multiple hosts and Claude cloud counter access are excluded.

## Shared project instructions

Module sessions read both project instruction files and applicable nested rules.
Missing files or unmatched shared blocks do not authorize creation or synchronization.
`instructions status/check` gives a read-only diagnostic; an explicit check stays strict.
Contradictory rules become an owner question. Ordinary packages report advisory drift
without expanding their scope.

Only a WP explicitly covering both files and holding their shared locks may call
`instructions sync --workspace <program> --wp <WP> --repo <checkout> --text-file <file>
--expected-claude <hash|missing> --expected-agents <hash|missing>`. Preview first;
`--apply` preserves existing client-specific text, expected hashes and case/symlink guards.

Switching clients returns every delivery level to owner and journals the previous
configuration. Explicitly delegate again after the switch; never inherit consent
from an old client or another session's message.

## Sources checked for this adapter

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [App Server](https://learn.chatgpt.com/docs/app-server)
- [Codex instruction loading](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [MCP](https://learn.chatgpt.com/docs/extend/mcp)
- [Claude memory](https://code.claude.com/docs/en/memory)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)

Run the common CLI with `--help` for exact argument placement. Runtime and concurrency
contracts and external ID integration: [runtime.md](runtime.md).


## Historical Linux observation and rejected MCP bridge

Legacy Linux autonomy remains unavailable in the historical workspace-write/on-request observation profile; the explicit private owner is a separate mode.
A hidden PID namespace can report ENOENT for a live host process; denied access is
not evidence of exit. Cancellation now distinguishes live, positively proven exited
and unavailable observation. The last state retains the assignment, outbox, slot and
locks. Old Linux confirmations lack PID-namespace evidence: reattach/recover explicitly;
do not force-cancel or use lease expiry as a substitute for observation.

A maintainer's isolated STDIO prototype found thread/turn metadata in CLI 0.154.0 and
0.165.0, but that metadata is not a session credential. In the macOS test profile a
module shell could reach the same App Server and use `mcpServer/tool/call` with forged
metadata naming the coordinator. The MCP process still had the correct native parent.
No privileged bridge is shipped. A safe caller-binding API/boundary must be proven
before host operations are implemented. Do not relax sandbox/approvals, enable legacy
Landlock, expose raw RPC, or start a second resume process to work around this refusal.
The explicit paid repository probe is `scripts/probe-orchestrator-codex-mcp.py`;
it exposes only a read-only metadata tool and never dispatches work.
