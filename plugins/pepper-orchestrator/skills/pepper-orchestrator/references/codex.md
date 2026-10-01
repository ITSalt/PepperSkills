# Codex CLI adapter and common runtime (0.11 preview)

The owner launches independent module sessions. One coordinator writes `status.md`
and decisions; module sessions implement WPs in their own Git worktrees. Preserve
the common methodology: evidence before verdicts, owner authority, no module code
edits by the coordinator, no merge/production/database/permission operations by
agents, and file-based recovery. Messages do not approve permissions or prove work.
Read common concept sections 1, 2 and 12 for these boundaries; use this document
for Codex models, roles, launch, messaging and recovery instead of Claude mode texts.

Portable `plugin.json` hosts always discover the canonical `skills/` directory;
their entrypoint explicitly routes Codex to this workflow before any Claude modes.
The `.codex-plugin` manifest selects the dedicated Codex entrypoint when used as
a native compatibility package. Manual Codex skill copies from the plugin ZIP use
that dedicated entrypoint with the same generated resources. Neither route changes
Claude instructions or creates another editable runtime implementation.
See [portable plugin component discovery](https://developers.openai.com/plugins/build/plugins).

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
  read both instruction files and synchronize confirmed shared rules before READY.
  Register the thread ID from `/status` with `session register --wp WP --thread ID
  --worktree PATH`. TASK delivery to an existing session uses `session send
  --wp WP --message-file task.txt --request-id KEY`; it uses `codex queue`.
  Failed delivery prints manual handover and is not recorded as delivered.
- `review`: verify PR/head SHA and tests, run `review-start WP --pr URL`, delegate
  the exact contract/head/base to `pepper_reviewer`. Use a disposable review clone
  for tests that write; never the implementer's active worktree. Collect evidence
  in the report. Record ACCEPTED only after verification; REVISE gives concrete
  findings to the same module session through queue. Review only the revision diff
  plus unresolved findings on resubmission. After repeated failure ask the owner
  to select a stronger Codex model unless `codex.models.escalate` is explicit.
- `verify`: `verify WP --env test|prod` verifies deploy/served SHA/commands without
  deploying. Delegate the agreed live scenario to `pepper_verifier`, with actual
  required browser/MCP/skills. WAIT keeps status; failures create BUG IDs and owner
  items as needed. Acquire stand/port/migration-application locks on demand.
- `resume`: read all state and decisions, lint, inspect registered sessions with
  `session list` (Git checked) and `session read --wp WP` (documented App Server).
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

Module sessions read both CLAUDE.md and AGENTS.md and applicable nested files.
Use `instructions status --repo .` for both SHA-256 versions, then prepare common
confirmed text in a file and run `instructions sync --repo . --text-file shared.txt
--expected-claude HASH_OR_missing --expected-agents HASH_OR_missing` to preview;
add `--apply` after inspection. Both blocks between `<!-- pepper:shared:start -->`
and `<!-- pepper:shared:end -->` receive identical text. Everything outside them
is preserved. Case variants are reused, ambiguous duplicates and symlinks fail
closed. Missing files are created by the module session. Commands/permissions
specific to a client stay outside shared blocks. Conflicts become a concrete owner
question; independent work continues. `instructions check --repo .` runs before
READY and finds drift at each nested instruction pair.

## Sources checked for this adapter

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [App Server](https://learn.chatgpt.com/docs/app-server)
- [Codex instruction loading](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [MCP](https://learn.chatgpt.com/docs/extend/mcp)
- [Claude memory](https://code.claude.com/docs/en/memory)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)

Run the common CLI with `--help` for exact argument placement. Runtime and concurrency
contracts and external ID integration: [runtime.md](runtime.md).
