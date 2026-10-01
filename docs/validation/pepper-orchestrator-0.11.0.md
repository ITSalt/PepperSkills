# Pepper Orchestrator 0.11.0: validation

Date: 2026-10-01. Local environment: macOS arm64, Python 3.14, Codex CLI 0.154.0.

## Implemented scope

- Dedicated Codex entrypoint selected by the Codex manifest; build injects canonical
  resources without maintaining another editable core. Claude command/agent/mode
  files retain their methodology and models.
- Sequential program client selection, per-client model assignments, prepared Git
  worktrees, session registry, documented App Server reads and codex queue delivery.
- Common local SQLite reservations, stable request replay, scope bindings, explicit
  legacy migration, rollback journals and short cooperative state transactions.
- Explicit paired project instruction synchronization and CAS; concrete file locks
  and explicit sequence resources after producer migration. No automatic removal
  of old wide locks, stand/port/application locks or push_deploys constraints.

## Evidence

The complete offline release gate `PYTHON=<build-venv>/bin/python bash scripts/check.sh`
passed (exit 0), including extracted packages, deterministic rebuilding, read-only
build checks and the Claude and runtime selftests.

- Existing Claude selftest: local/cloud, legacy programs, models/settings, dispatch,
  locks, review, verification, owner queue, closing/reopening and Windows command
  formatting. This uses local fixtures and stub gh, not production providers.
- Runtime selftest: 16 processes / 1,600 unique reservations plus idempotent replay;
  namespace/count mismatch; death before/after SQLite commit; ten-second busy timeout;
  missing/corrupt connected store; 12 parallel owner updates and 12 direct safe_edit
  updates retained; eight exclusive creates yield one writer; multi-file recovery,
  foreign conflict, interrupted init, paired instructions/CAS/case/CRLF preservation,
  client model restoration and worktree reuse, explicit migration and narrow locks.
- Actual Codex CLI: plugin ZIP extracted, Codex skill installed in fixture project
  .agents/skills; two concurrent read-only CLI sessions in different Git worktrees
  read both CLAUDE.md and AGENTS.md and the Codex adapter (both exit 0).
- Native pepper_scout: a persisted CLI session loaded the native role. App Server
  history records subAgentActivity started and completed for /root/pepper_scout.
  An ephemeral CLI attempt could not spawn a child in this CLI version; real launch
  descriptors do not use --ephemeral. The test parent was archived afterward.
- codex queue accepted a REVISE fixture notification (delivered/queued=true).
  App Server initialize, thread/start, thread/read with turns and thread/archive
  succeeded. Queue acceptance does not prove consumption or completion of that turn.
- Native execpolicy parser returns forbidden for gh pr merge with generated rules.
- Plugin component checks verify the manifest entrypoint, identical injected core,
  sorted/no-duplicate archive members and execution of the extracted common CLI.

## Limits and release gate

Linux and Windows runtime jobs were added to CI; their results are not available
from this local run. Existing Windows command-format fixtures do not certify native
Windows filesystem/locking behavior. No cross-host counter or cloud connectivity
is claimed. A real owner-driven interactive permissions grant, configured MCP/browser
live scenario and full real PR/stand lifecycle remain environment-dependent acceptance
checks. Required MCP configuration is checked at dispatch, while connection/tool
authorization must be verified by the executing role. Project skill installation
from the ZIP was tested; publishing and updating the user's global plugin installation
were not performed. Existing user programs were not automatically migrated.

This is a local preview build. No public release was made.

The unreleased 0.9.0 adaptation was integrated with main's 0.10.0 Claude deliver/release
features. The first public build is 0.11.0; no existing main feature is rolled back.
Windows-specific fixes include consistent UTF-8, native interpreter selection,
PowerShell quoting, and CRLF-preserving exactly-once replacements. Contention can
return the documented retryable error after ten seconds; the process stress test
retries the same request ID and verifies all 1,600 unique reservations and replays.
