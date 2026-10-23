# Shared delivery and live acceptance contract

Applies to local Codex CLI and Claude Code. The coordinator alone writes program
state and invokes delivery. Module sessions and native review/verification roles
never merge, deploy, change permissions or write to databases. All delivery levels
default to `owner`. Existing native sandbox/approval policy remains in force; a
refusal is an owner item, not a reason to bypass the policy. Production MCP stays disabled.

## Delegation and preflight

Record the owner's actual decision D-n, then use `delivery set merge|stand|prod|prod_migrations
orchestrator --decision D-n`. Changing clients revokes all four levels, journals
the old configuration and requires fresh explicit delegation. `hold` stops new
operations. Settings are regenerated for the active client; no running session
or user configuration is silently weakened.

Use `deliver --check WP` before `deliver --apply WP`. The accepted full head SHA
is passed to GitHub as `--match-head-commit`; another head needs review. GitHub
merge queues and successful command exit do not prove a merge: wait for the
actual merged PR and merge commit. Never pass `--admin` or set auto-merge.
One WP supplies one PR/merge. Expand and contract are dependent separate WPs;
status correction after a real regression remains possible.

Repository/module `deploy_test_mode` is `command`, `workflow`, `automatic` or `owner`:

- `command`: nonempty `deploy_test`, executed in the program's `shell` (`bash` or
  `powershell`). Text beginning `owner-confirmed` is not executable configuration.
- `workflow`: `deploy_workflows` for test must be configured; wait for the exact SHA.
- `automatic`: requires `base_deploys: staging`; verify the served SHA rather than
  claiming a missing deploy command proves automatic deployment.
- `owner`: stop after merge and give the owner the deployment step.

Old configurations infer a mode only from existing workflows, recognized command
strings, the documented `owner-confirmed` description, or `base_deploys: staging`.
Anything else requires explicit configuration before merge. For a command starting
with `git`, explicitly set `deploy_test_mode: command`. `deploy_prod` retains its
owner-only meaning; PROD uses the existing promote workflow and release sheet.

## CI policy

All reported checks must pass or skip by default. Network/authentication/decoding,
incomplete responses and unknown check states are blocking facts, never empty success.
An explicitly verified absence of checks is different from a failure to read them.
The same implementation governs stand PRs and promote PRs.

Optional repository/module configuration:

```yaml
nonblocking_checks:
  - name: Preview
    source: app:preview-provider
    decision: D-7
```

`source` is the exact GitHub App slug (`app:<slug>`) or commit-status creator login
(`status:<login>`), verified on the current PR head. Name matching is exact.
D-n must exist. Required checks cannot be excluded. Missing required-check facts,
ambiguous provider names or incomplete source pagination prevent an exception.
Excluded results remain visible in the gate; no branch protection is changed.

## Delivery outcomes and recovery

A separate per-program OS workflow mutex serializes deliver/release apply, client
switching and reconciliation. It does not hold the state transaction lock: hold
and short state updates remain available. Process death releases only the mutex,
not the obligation to reconcile an uncertain persisted outcome.

`delivery show` includes per-WP delivery phase records under `release/` and the
Markdown journal records every change. Phases include not-started, started,
completed and unknown. A failure before starting deployment does not run rollback.
A timeout, lost response or interrupted process does not authorize retry/rollback.

Read the actual PR, merge commit, workflow runs and served version first. When a
prior request is confirmed unmerged and not queued, an owner decision can authorize
`delivery reconcile WP --decision D-n`. This only records read facts and enables a
new gated attempt. A merged/queued/unknown PR is refused; queue absence is read through GitHub mergeQueueEntry, not inferred from mergeability. For a merged PR continue
verification at its actual SHA; do not repeat merge or deployment blindly. Recover
an interrupted deployment through the owner's narrowly scoped command after
reconciliation. Automatic rollback is allowed only for a completed stand deployment
whose verification failed and whose delegation remains valid. Database rollback
is never automatic. PROD migrations retain their separate authorization and backup.

## Final acceptance

`verify WP --env test|prod [--sha <prefix>]` resolves a unique local commit before
writes. Fetch unavailable revisions explicitly. Automatic PASS records checks and
leaves `VERIFYING`, not `VERIFIED_TEST`/`PROD`. It writes a report and a `.checks.json`
evidence record containing the full SHA, WP, environment and numbered acceptance
criteria from section 3 of the WP. Historical reports are not silently upgraded.

Fill the generated live table for every criterion: Expected, Actual, Evidence,
Verdict. Use tangible command output, browser screenshots or read-only query
results. Missing tools are WAIT, not synthetic PASS or a product defect. Then:

```bash
python3 SKILL_DIR/scripts/orch.py verify finalize WP-APP-01 --env test \
  --sha <full-40-character-SHA> --report reports/verify-WP-APP-01-test-DATE.md --verdict PASS
```

`PASS` requires automatic PASS and concrete evidence for every unchanged criterion.
`FAIL` requires concrete evidence of a failed criterion, records a defect and holds delivery.
`WAIT` keeps downstream gates closed without inventing a product defect.
Final acceptance binds the complete report digest to the revision; editing a report
invalidates it. Evidence JSON files are recoverable report metadata; `status.md`
remains program state. They are not a security boundary against a malicious
coordinator with write access.

Only finalized stand acceptance opens the next sequential merge and the release
sheet. After promote, automatic PROD checks likewise wait for each package's live
`verify finalize --env prod`. Preserve old statuses; supply missing evidence before
a new automated delivery. Explicit status correction never substitutes for evidence.

## Instruction files and locks

Ordinary prompts read both instruction files and report advisory pairing drift.
They do not create a missing paired file or synchronize rules. Explicit
`instructions check` retains its nonzero diagnostic. Contradictions go to the owner.
`instructions sync --apply` requires `--workspace`, `--wp`, declared instruction
paths, required shared locks and expected file hashes. Existing client text remains.

`lock cancel NAME --wp WP` removes only a waiting request. Terminal-package waits
are cleared with journal entries, never releasing a real holder. Planning checks
shared globs with the same conservative intersection as dispatch; dry-run diagnoses
READY-wave collisions without taking locks. Existing shared files remain locked
through integration. On-demand shared paths and automatic session reuse are deferred.
