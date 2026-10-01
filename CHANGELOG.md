# Changelog

## 0.9.0 — 2026-10-01, public preview

- Dedicated Codex CLI skill, native scout/reviewer/verifier roles, prepared ordinary
  Git worktrees and documented queue/App Server session transport. Keep Claude
  methodology and per-client models; switch clients only after stopping writers.
- Local SQLite ID reservations with idempotent retries, explicit legacy import,
  short process locks and recoverable multi-file state changes.
- Paired CLAUDE.md / AGENTS.md shared blocks preserve existing instructions and
  check expected versions. Numbering locks narrow only after producer migration.
- Windows UTF-8, interpreter selection, CRLF point edits and PowerShell quoting.
  CI exercises concurrency/recovery on three platforms and installs the built
  plugin with native Windows Codex. Interactive account permissions/MCP/PR lifecycle
  remains a separate owner acceptance check. See [Windows guide](plugins/pepper-orchestrator/WINDOWS.md).

## Unreleased — pepper-orchestrator 0.8.0 (preview)

Plugin defect channel: `report` mode and `orch.py report` (anonymized record, Issue in this
repository after the owner's yes, duplicates commented), an issue form for agent reports,
CODEOWNERS, a merge rule and agent sections in CONTRIBUTING. Also fixes the indentation of the bug
issue form, which GitHub could not parse. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.7.1 (preview)

Windows fix: settings files use the documented Windows form of rule paths (`//c/...`), so
`init`, `settings` and `dispatch` work on Windows again; PowerShell start commands on request.
Preview, not yet released.

## Unreleased — pepper-orchestrator 0.7.0 (preview)

Verification by facts: `verify` mode and `orch.py verify <WP> --env test|prod` (deploy run for the
merge commit, served version, read-only verify commands, report, `VERIFIED_TEST`/`PROD`, defects),
a read-only verifier agent and a live-scenario brief. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.6.0 (preview)

Session permissions: generated settings files for module and orchestrator sessions (narrow allow,
deny for merge, base pushes, releases and production, owner checkpoints, auto mode environment,
cross-session message delivery), the owner's explicit permission mode at init, worktrees without
secrets through `.worktreeinclude`, on-demand locks, and fixes from the first field run. Preview,
not yet released.

## Unreleased — pepper-orchestrator 0.5.0 (preview)

Implementer model and effort per package in start commands, the owner's explicit session-kind
choice at init, cloud environment and prefill links for cloud sessions, escalation after repeated
REVISE rounds. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.4.0 (preview)

Program completion: goal and completion condition in the plan, `close` by facts with a closeout
report, backlog carry-over, archive steps for the owner, `reopen`. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.3.0 (preview)

PR review: `review` mode with a read-only reviewer agent and a disposable clone, automatic findings
from the stream rules and a stale merge-base, a scout agent, and "Typical workflows" in the plugin
README. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.2.1 (preview)

Cloud sessions over one repository: in-repo workspace on `orch/<program>` in a deploy-ignored
directory, cloud-session prompts from `dispatch`, readiness by branches and pull requests, and
`scripts/install-skill.sh` for cloud environment setup scripts. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.2.0 (preview)

Streams in one repository: modules as areas and domains with their own paths, worktree start
commands, locks on shared paths and resources, a merge queue, `dispatch` and `overlap`. 0.1.0
workspaces keep working unchanged. Preview, not yet released.

## Unreleased — pepper-orchestrator 0.1.0 (preview)

New plugin `pepper-orchestrator` (stage 1 core): single-orchestrator method for programs that
span several repositories, with a stdlib-only workspace CLI, English and Russian templates and
Claude Code short commands. The repository scope now admits agent-workflow plugins with a portable
core and client adapters. Preview, not yet released.

## RU Web Compliance 2.2.0 — 2026-09-28

Network observations now retain context without payload values. POST requests
and endpoint names no longer establish form submission or database location.
Reports separate verification from confirmed fixes and use reviewed summaries,
actions, sources and substantive acceptance criteria.
[Validation and release packages](docs/releases/2026-09-28-compliance-2.2.0.md).

## Feedback follow-up — 2026-09-26

Compliance 2.1.0 and listing-only patches Creative Mode 2.0.1 /
Prompt Engineer 2.5.1. Unified uv runtime guidance, added a public legitimate-
interest scaffold and conditional removal/UI guidance, documented Pi, and made
accepted semantic reviews close report actions while preserving machine facts.
Final OpenAI listing limits are now checked offline.
[GitHub release links and validation scope](docs/releases/2026-09-26-feedback.md).
OpenAI marketplace submission and publication remain separate and were not performed.


## 2026-09-26 — repository layout transition

Published Creative Mode 2.0.0, Prompt Engineer 2.5.0 and RU Web Compliance 2.0.0.
[Release links and acceptance record](docs/releases/2026-09-26-transition.md).

| Previous path | Canonical path |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `<name>/chat-prompt.md` | `plugins/<name>/adapters/chat/chat-prompt.md` |
| `pepper-prompt-engineer/chat-prompt.template.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.template.md` |
| `<name>/anthropic/INSTALL.md` | `docs/installation-and-updates.md`, `docs/installation-and-updates.ru.md` |
| Root `RELEASE-NOTES-v1.4.*.md` | `docs/releases/` |
| `docs/modernization-*.ru.md` | `docs/history/` |

The root skill paths remain as transition symlinks during Phase A. Existing user
installations are not rewritten. See the [installation guide](docs/installation-and-updates.md)
and [Russian transition map](docs/installation-and-updates.ru.md).

Root `.skill` files are frozen previous builds from repository revision
`v1.4.1-1-g4128fe6` (commit `4128fe6`). They are not rebuilt and do not represent
current plugin versions; new archives are built in `dist/<name>/<version>/`.

### Chat compatibility corrections after review

At the transition release, chat bodies matched checkpoint `e2c7d4f` (including whitespace), except the rebuild
command and six deliberately repaired local-reference labels. The full prompts
already had dangling Markdown links with Russian appendix labels at that checkpoint;
these now name the included appendix directly (English in Creative Mode, Russian in
Compliance). The compact Creative Mode names the full-skill reference without adding
its 5 KB appendix. Appendix selection is explicit in templates. Golden hashes and
exact allowed replacements are recorded in `scripts/fixtures/chat-goldens.json`.

Compliance 2.1.0 adds separately recorded, intentional text changes for the
reviewer feedback. The original checkpoint remains the comparison baseline.
