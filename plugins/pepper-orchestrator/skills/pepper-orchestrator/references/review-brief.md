# Review brief and risk checklists

The brief is the reviewer's whole input (concept section 13). It is self-sufficient, names the
risks of this package, and asks specific questions. "Check everything" produces long reports
without findings.

## Brief template

```text
Review PR <url> of work package <WP> at head <sha> against <base>.
Package: <absolute path of the WP file>. Repository: <path or URL>. Report skeleton: <report path>.

Rules: read only (git show, read-only gh); do not enter the module session's working directory;
tests only in the disposable clone below; never merge, approve or comment; no database clients or
ssh through Bash; claims of the session are claims to verify.
[Cloud, general subagent with GitHub tools: only get, list and search tools; never
merge_pull_request, update_pull_request_branch, push_files, create_or_update_file, create_branch,
pull request creation or update, reviews or comments.]

Facts collected by the orchestrator with MCP tools (database SELECT results, CI, logs):
  <facts, or "none">

Disposable clone and tests:
  <clone command printed by orch.py review-start>
Mutations: rerun with --keep, change the clone, rerun the tests, then --cleanup.

Automatic findings already found (verify, do not repeat blindly):
  <list from orch.py review-start>

Claims of the session to verify (from the PR body / report):
  1. <claim>

Specific risk questions for this package:
  1. <question from the checklists below, made concrete with names from the diff>

Answer in the reviewer report format: verdict; scope item -> where -> status; answers to the risk
questions; findings by severity with file:line and failure scenario; deviations; CI, size, tests,
mutations; cleanup.
```

## Always ask

- If the package has a Specification or Graph row: did the implementer update the graph (the PR
  report carries the output of the methodology's status command)? Write `graph: checked` in the
  review report, or a finding; a mismatch between the graph and the package is a REVISE item.
  `orch.py deliver` refuses a merge without `graph: checked` (gate G9).
- What did the base allow or show that the change removes? Name each removed branch, state,
  transition, permission, UI action or API field, and whether the package asked for its removal.
- Does every acceptance criterion have a test or a live check, and does the test fail when the key
  line of the fix is removed (mutation)?
- Are the declared deviations acceptable, and are there undeclared ones?
- Did the branch touch files outside its allowed paths, or shared paths without the lock?

## Checklists by change type

Pick the lists that match the diff; turn each item into a question with concrete names.

### State machines and statuses

- List the transitions on the base and after the change: which ones disappeared, which became
  reachable from new states.
- Is any state now terminal that was not, or reachable with no way out (irreversible)?
- Are guards duplicated in several places (database constraint, backend, UI) and still consistent?
- Do existing rows in every state still behave (data written before the change)?

### Database migrations

- Numbering and order against the base at merge time; a migration that the deploy would skip or
  apply out of order.
- Replacing constraints or enums: are all old values still allowed (a full replacement written from
  an old branch drops values added since)?
- Backfill and defaults for existing rows; locks and runtime on large tables; reversibility.
- Functions and views: the live definition after the migration, not only the file.

### Registries and shared types

- Error codes, route registration, generated trees, exports, navigation: duplicates, missing
  entries, ordering conflicts with parallel branches.
- A type declared in several places (backend, shared package, database check): all updated
  together, with a test that they agree.

### UI

- Actions that were available and are now hidden or disabled; empty, loading and error states;
  role-dependent visibility.
- Texts and labels against the package; accessibility of new controls; screenshots or live checks
  when the package asks for them.

### Permissions and data access

- Row-level policies, role checks and API guards: who gained or lost access; server-side checks
  behind every UI restriction.
- Secrets, tokens and personal data in code, logs, fixtures or the PR body.

### Integrations and background work

- Retries, idempotency, timeouts, ordering of events; what happens on partial failure.
- Configuration and environment variables: defaults, missing values, differences between TEST and
  PROD.
