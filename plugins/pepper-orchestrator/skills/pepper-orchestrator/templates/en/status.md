# {{PROGRAM_TITLE}} — status

The only source of state for program `{{PROGRAM}}`. Written only by the orchestrator,
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

## Waiting for owner

R-n: action with an exact one-line command and the expected output. P-n: question
with options, consequences and a recommendation. A row is closed only after the
orchestrator verified the fact; closed rows are struck through with date and fact.

<!-- orch:owner -->
| ID | What (command ; expected) | Where | Opened | Closed |
|----|---------------------------|-------|--------|--------|

## Locks

Shared paths and resources of a repository; only the holder may change a shared
path, push a migration, verify on the stand or run the dev stack on fixed ports. The
holder releases after merge or verification. Waiting: packages queued for the lock.

<!-- orch:locks -->
| Lock | Repo | Holder | Since | Waiting | Note |
|------|------|--------|-------|---------|------|

## Merge queue

With `merge_policy: sequential`: one merge at a time; after each merge wait for
the green stand deploy and health check, then rebase the next package.

<!-- orch:merge -->
| # | Repo | WP | PR | Rebase after | Status |
|---|------|----|----|--------------|--------|

## Journal

Newest first. One line per event: time (UTC), WP, what happened, evidence.

<!-- orch:journal -->
| Date | WP | Event | Evidence |
|------|----|-------|----------|
