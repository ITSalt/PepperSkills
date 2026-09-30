# WP-API-01 — Orders export

| Field | Value |
|-------|-------|
| Repository | ~/projects/example-api |
| Base branch | main |
| Work branch | `legacy/wp-api-01-orders-export` |
| PR title | `[LEGACY] WP-API-01: Orders export` |
| Mode | <methodology the session follows in its repository> |
| Session | `legacy-api` |
| Contract | <contract version, or none> |
| Depends on | <WP ids, or none> |
| Size | <S / M / L> |
| Specification | <optional: requirement, use case or task IDs from any source; none> |
| Decisions | <D-n this package relies on, or none> |

## 1. Facts

Why the package is needed: verified facts with `file:line`, SELECT results and report
links. Facts, not retelling.

## 2. Scope

1. <item>

### Not in scope

- merge, deployment, production, database writes
- other modules and the orchestrator workspace
- version bumps and release notes unless listed above

## 3. Acceptance criteria

1. <verifiable: test, measurement, live scenario, SELECT>

## 4. Delivery

- PR from `legacy/wp-api-01-orders-export` to `main`; do not merge.
- PR body = development report + `Deviations` (what differs from this package and why).
- Then send `[LEGACY] READY WP-API-01 :: <sha> :: ref=<PR URL>` to `legacy-coord`.

## 5. Start prompt

```text
Read /srv/owner/orchestrator/features/legacy/work-packages/WP-API-01-orders-export.md and implement it. Branch legacy/wp-api-01-orders-export from main, PR to main, do not merge. When done, send to legacy-coord: [LEGACY] READY WP-API-01 :: <sha> :: ref=<PR URL>
```

### Start command

Start command (for the owner, run in a new terminal):

```bash
cd ~/projects/example-api && claude --name legacy-api "Read /srv/owner/orchestrator/features/legacy/work-packages/WP-API-01-orders-export.md and implement it. Branch legacy/wp-api-01-orders-export from main, PR to main, do not merge. When done, send to legacy-coord: [LEGACY] READY WP-API-01 :: <sha> :: ref=<PR URL>"
```

No `--settings` in this version: settings files are generated only in a later version.

## Resubmissions

<REVISE rounds: date, items, commit.>
