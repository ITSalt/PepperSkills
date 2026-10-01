# Pepper Orchestrator 0.11.0: validation and release gate

Date: 2026-10-01. Local environment: macOS arm64, Python 3.14, Codex CLI 0.154.0.
[Release](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-orchestrator-v0.11.0).
[Final PR checks](https://github.com/ITSalt/PepperSkills/pull/28/checks).

## Implemented scope

- Portable `plugin.json` hosts discover fixed `skills/` components. The common
  entrypoint explicitly routes Codex to its own governing workflow before Claude
  instructions. The native compatibility manifest selects `codex/skills/`; the
  ZIP supplies its canonical resources without another editable runtime. Native
  Windows installation tests check the instructions actually discovered by Codex.
- Sequential client selection, per-client models, prepared Git worktrees, session
  registry, documented App Server reads and codex queue notification delivery.
- Common local SQLite reservations, stable request replay, scope bindings, explicit
  legacy import, rollback journals and short cooperative state transactions.
- Explicit paired project instruction synchronization and expected versions;
  concrete file locks and sequence resources only after producer migration. Old
  wide locks, stand/port/migration locks and push_deploys constraints remain.
- Main's Claude 0.10.0 deliver/release and conditional escalation are retained.
  Codex v1 keeps irreversible operations in the owner queue, as its workflow states.

The unreleased 0.9.0 adaptation was integrated with main's 0.10.0 development;
0.11.0 is the first public preview. Existing programs are not migrated automatically.

## Automated release gate

Publication requires the final PR's complete check matrix to be green:

- Full offline suite on Ubuntu/Python 3.10, Ubuntu/Python 3.12 and macOS/Python 3.12.
  It exercises source and extracted packages, deterministic rebuilding, read-only
  builders, private traces and blocked network access. Claude fixtures cover
  local/cloud, legacy programs, permissions/models, dispatch, review/verification,
  owner queue, close/reopen, trusted deliver/release and UTF-8 output under cp1252.
- Real process runtime tests on Windows, Ubuntu and macOS: 16 processes / 1,600
  unique reservations and stable replays; namespace/count mismatch; death before
  and after SQLite commit; configured ten-second busy timeout; missing/corrupt
  connected stores; 12 parallel state updates and 12 direct safe_edit updates;
  eight exclusive creates / one writer; recovery and foreign-edit conflict;
  interrupted init; instruction versions/case/CRLF; client model restoration and
  worktree reuse; migration and concrete shared file/stand serialization.
- Busy reservations can return the documented retryable error after ten seconds.
  The stress test retries that same request ID within a bounded budget, rather
  than assuming fair scheduling or using unsafe max+1. No number is recycled.
- Native Windows / Python 3.12 / Codex CLI 0.154.0: build/extract the plugin ZIP;
  execute its PowerShell launch with spaces, apostrophes and Cyrillic paths;
  prepare ordinary Git worktrees; preserve Russian instruction text; install and
  enable version 0.11.0 through native Codex plugin commands; initialize App Server
  and check the loaded skill's Codex routing via skills/list. No model call or
  account credential is required. The npm transport resolves the native exe
  without cmd.exe message parsing; Windows path case shares one state lock.
- Package hashes must match across the three full-suite jobs. Release downloads
  must match the distributed SHA256SUMS. The release contains the plugin ZIP and
  the common/Claude standalone ZIP; use the plugin ZIP's Codex skill for manual
  installation. Test runtime stores are disposable and separate from user state.

## Native macOS baseline

Before integration with main's 0.10.0 features, the 0.9.0 adaptation also passed:

- Two concurrent actual Codex CLI sessions in separate worktrees, using the Codex
  skill from the extracted ZIP; both read CLAUDE.md and AGENTS.md and exited 0.
- A persisted native pepper_scout role, with App Server history recording start
  and completion. An ephemeral parent could not spawn a child in this CLI version;
  generated launches do not use --ephemeral. The test parent was archived.
- codex queue accepted a REVISE fixture notification; App Server initialize,
  thread/start, thread/read with turns and thread/archive succeeded. Acceptance
  into the queue does not prove consumption or completion.
- Native execpolicy parsing forbids gh pr merge with generated module rules.

These model-backed observations are baseline evidence, not a new interactive
Windows model run. Final native Windows checks cover installation and transport.

## Remaining owner acceptance

Interactive Windows account login/permissions, authorized MCP/browser tools and
one full real module PR/stand lifecycle are checked on the owner's machine using
[the Windows checklist](../../plugins/pepper-orchestrator/WINDOWS.md). Installation
alone is not evidence that MCP tools are connected or authorized. No cross-host
counter, shared WSL/native database, cloud counter connectivity or power-loss
filesystem certification is claimed. The user's global installation and existing
program instructions are not overwritten by these tests.

[Portable plugin format and component discovery](https://developers.openai.com/plugins/build/plugins)
explains why a compatibility `skills` path cannot replace the portable root's
fixed components; client routing is explicit in both supported entrypoints.
