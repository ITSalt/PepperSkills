# Legacy program

Program `legacy`, run by the single-orchestrator method (pepper-orchestrator).
Created 2026-09-28. Tag in messages and PR titles: `[LEGACY]`.

## Where things are

| Path | What |
|------|------|
| `status.md` | the only source of state: waves, work packages, owner queue, journal |
| `PLAN.md` | goals, scope, waves, gates, risks |
| `decisions.md` | decisions D-n, assumptions A-n, research questions Q-n (append-only) |
| `work-packages/` | one file per work package, `_TEMPLATE.md` for new ones |
| `bugs/` | one file per defect found along the way |
| `reports/` | review, live-check and gate reports (created on demand) |
| `release/` | release sheets, runbooks, rollback (created on demand) |
| `orchestration/protocol.md` | session and message protocol for this program |
| `orch.yaml` | modules, sessions, environments, guards |

## Rules in one paragraph

Only the orchestrator session (`legacy-coord`) writes here. Module sessions write
code in their own repositories and report through PRs. Irreversible actions (merge,
deploy, production, database writes, permissions) are done only by the owner, from
ready one-line commands in the owner queue of `status.md`.
