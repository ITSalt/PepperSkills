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

## Journal

Newest first. One line per event: time (UTC), WP, what happened, evidence.

<!-- orch:journal -->
| Date | WP | Event | Evidence |
|------|----|-------|----------|
