# Pepper Orchestrator 0.15.0: bounded research, proactive control and local continuation

3 November 2026. Public preview, tag [`pepper-orchestrator-v0.15.0`](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-orchestrator-v0.15.0).
[Русский](pepper-orchestrator-0.15.0-release.ru.md).

## Why

A Codex coordinator ran a research package for six hours without submitting it: every wave
produced an adjacent question, the coordinator's own journal commits woke it again, and the
experimental half of the package blocked the static half that dependents needed. This release
bounds research, makes the owner of every remaining criterion explicit and keeps the timer as the
coordinator's control instrument instead of removing it.

## What changed

- **Research contract** ([research.md](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/research.md)), shared by Claude Code and Codex and by both executors (subagents, launched sessions): at most 8 frozen criteria, one wave and one scoped correction, a verdict on every criterion. `partial` hands each unresolved criterion to its owning WP with a condition; the package becomes ACCEPTED/DONE and dependents continue. `blocked` needs a resolving condition and `unblock` returns only to review.
- **Proactive watcher.** A changed fact wakes the coordinator at once; an unhandled action is raised again after `interval_seconds`, owner-only waits every sixth interval. The coordinator's own commits are not facts. Every wakeup is a control tick: progress against criteria and budget, stalls, then a decision.
- **Stall detection** ([#45](https://github.com/ITSalt/PepperSkills/issues/45)): `stalled` actions for packages waiting on an executor with no file, commit, index or push activity for `--stall-minutes` (45 by default) while the session is not busy, and for research collections whose results were never recorded.
- **Local Codex continuation** ([local-continuation.md](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/local-continuation.md)): a saved automatic/manual choice, inherited coordinator permissions and automatic executor creation for ordinary local sessions.
- **Claude Code:** `/goal`, `/loop`, `ScheduleWakeup` and `CronCreate` are allowed with a measurable condition and a limit taken from the package; resume reconciles them with the registry.

## Validation

Offline, on Linux (Python 3, this tree):

| Suite | Result |
|---|---|
| `research_selftest.py` | 12 tests OK, including the partial-acceptance deadlock regression, re-raise and stall cases |
| `autonomy_selftest.py` | 41 tests OK |
| `continuation_selftest.py` | 10 tests OK |
| `runtime`, `reliability`, `owner` self-tests | 11, 19, 20 tests OK |
| manifest, metadata and skill-version sync; plugin components; private traces; private-stdio and MCP probe tests; deterministic package build | pass |

CI on the pull request covers Linux, macOS and Windows.

**Not repeated in this release:** the live Linux/macOS private-owner acceptance recorded for
[0.14.0](pepper-orchestrator-0.14.0-private-owner.md), and the live local-continuation driver
`scripts/test-orchestrator-local-continuation.py`, which needs a running Codex server. Both runtime
paths use the changed shared scheduler; their behaviour is covered by the offline suites above,
not by a new model-driven run. The release remains a preview.

## Published assets

Hashes are listed in `SHA256SUMS` on the [release page](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-orchestrator-v0.15.0). Builds are deterministic: `bash scripts/build-plugins.sh pepper-orchestrator` on the tagged tree reproduces them.
