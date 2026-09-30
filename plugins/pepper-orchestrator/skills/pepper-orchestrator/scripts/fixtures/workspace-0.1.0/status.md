# Legacy program — status

The only source of state for program `legacy`. Written only by the orchestrator,
through `orch.py` and point edits, after every state change.

## Waves

| Wave | Goal | Gate | Status |
|------|------|------|--------|

## Work packages

Statuses: DRAFT, READY, DISPATCHING, IN_PROGRESS, REVIEW, REVISE, ACCEPTED, MERGED,
TEST-APPLIED / DEPLOYED_TEST, VERIFYING, PROD, DONE, BLOCKED (reason),
CANCELLED (reason).

<!-- orch:wp -->
| WP | Module | Title | Status | Session | PR | Updated |
|----|--------|-------|--------|---------|----|---------|
| [WP-API-01](work-packages/WP-API-01-orders-export.md) | api | Orders export | READY | legacy-api | — | 2026-09-28 |
| [WP-WEB-01](work-packages/WP-WEB-01-export-button.md) | web | export button | DRAFT | legacy-web | https://github.com/example/web/pull/7 | 2026-09-28 |

## Waiting for owner

R-n: action with an exact one-line command and the expected output. P-n: question
with options, consequences and a recommendation. A row is closed only after the
orchestrator verified the fact; closed rows are struck through with date and fact.

<!-- orch:owner -->
| ID | What (command ; expected) | Where | Opened | Closed |
|----|---------------------------|-------|--------|--------|
| ~~P-1~~ | ~~Export format? (a) CSV (b) XLSX ; recommendation (a)~~ | PLAN.md | 2026-09-28 | 2026-09-28: answered by D-1 |
| R-1 | Merge: gh pr merge 7 --repo example/web --merge ; expected: merged | — | 2026-09-28 |  |

## Journal

Newest first. One line per event: time (UTC), WP, what happened, evidence.

<!-- orch:journal -->
| Date | WP | Event | Evidence |
|------|----|-------|----------|
| 2026-09-28 10:00Z | — | P-1 closed | answered by D-1 |
| 2026-09-28 10:00Z | — | D-1 recorded | answer to P-1 |
| 2026-09-28 10:00Z | — | R-1 opened for owner | — |
| 2026-09-28 10:00Z | — | P-1 opened for owner | PLAN.md |
| 2026-09-28 10:00Z | WP-API-01 | WP-API-01: DRAFT -> READY | sections complete |
| 2026-09-28 10:00Z | WP-WEB-01 | WP-WEB-01 created (DRAFT) | work-packages/WP-WEB-01-export-button.md |
| 2026-09-28 10:00Z | WP-API-01 | WP-API-01 created (DRAFT) | work-packages/WP-API-01-orders-export.md |
| 2026-09-28 10:00Z | — | workspace created (en) | orch.py init |
