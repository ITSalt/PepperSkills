# Local runtime contract

Markdown remains the source of program state. SQLite stores only allocated numbers;
session JSON is technical routing/outbox data. Runtime lives outside Git in
`~/.pepper-orchestrator/runtime/`. `ORCH_RUNTIME_DIR` is an explicit override for
tests or a backed-up local runtime; all processes must use the same value.

## Numbers

New local programs register a UUID program scope. Old programs migrate explicitly:

```bash
python3 scripts/orch.py --workspace /path/program id migrate --scope program --json
python3 scripts/orch.py --workspace /path/program id migrate --scope program --apply --json
python3 scripts/orch.py id migrate --scope repo:/path/repo --namespace FR --seed 0 --json
python3 scripts/orch.py id migrate --scope repo:/path/repo --namespace FR --seed 0 --apply --json
python3 scripts/orch.py id reserve --scope repo:/path/repo --namespace FR --request-id feature-x:requirement-a --count 2 --json
```

Repository worktrees resolve to their Git common directory. A local binding in
`info/pepper-orchestrator-scope.json` keeps the scope across worktrees and clients.
Migration imports Markdown ID maxima including archives and available Git refs;
external namespaces also scan supported text files. For an external generator,
audit all its active/local/remote branches and archive formats and supply the
confirmed high-water mark with `--seed N`. No fetch happens implicitly; fetch
available branches before migrating. Existing IDs are never rewritten.

Each namespace is independent; WP uses `WP-MODULE` and preserves two-digit minimum
format, R/P/D/A/Q/B/BUG/PLUGIN-BUG preserve their existing format. MERGE is technical.
The returned numbers are committed before stdout. Reusing a request ID returns the
same range; changing its namespace/count is an error. Request IDs are unique within
the scope. Use a stable entity key, not a fresh random value on retry. Gaps are
expected and numbers never return to the pool. There is no unsafe fallback after
an error. Busy waits last at most ten seconds. Back up the entire runtime with its
SQLite journal at rest (or use SQLite's backup API); do not copy an active DB file
alone. Lost/corrupt previously connected stores require restoration; never delete
the binding/config to pretend it is a new store.

External generator (stdlib only):

```python
import json, subprocess
result = subprocess.run([
    'python3', '/installed/skill/scripts/orch.py', 'id', 'reserve',
    '--scope', 'repo:/absolute/repo', '--namespace', 'MIGRATION',
    '--request-id', 'billing-v2:create-ledger', '--json',
], check=True, text=True, capture_output=True)
number = json.loads(result.stdout)['first']
# Format the tool-specific filename, then create it exclusively (mode 'x').
# Validate migration dependencies and application order separately.
```

Local Claude and Codex call this same CLI. Cloud Claude keeps its existing path:
this local database is not reachable from an independent cloud environment.
Old local programs remain compatible and serialize their max+1 operation until
explicit migration; no numbering locks are automatically removed.

## Short writes and recovery

All local state commands and direct safe_edit calls share OS process locks. The
read/check/change operation is held under one lock; direct safe_edit clients should
wrap multi-file or read-derived changes in `state_io.transaction(root_for(path))`.
CAS fragments/hashes reject stale expectations. New files use exclusive creation.
Backups, single-match replacements, size checks and nonempty checks remain.
Undo journals are written/fsynced before each changed file; normal completion removes
the journal. After death the next operation rolls back the incomplete compatible
transaction before applying new work. If a foreign edit matches neither the old nor
new versions, recovery stops with exact file and journal paths. Preserve these files
and reconcile explicitly. Multiple os.replace calls do not make a multi-file edit
atomic; readers outside this cooperative mechanism can see intermediate versions.
Network, tests, agent waits, push and setup run outside state locks. Slow workflows
CAS-check state before recording their results, and ask to retry if it changed.

## Explicit narrowing

For distinct new files use concrete WP Allowed/Shared paths with separately
reserved numbers. Existing shared files/indexes stay locked through integration.
Do not remove shared-directory globs automatically. On-demand resources retain
locks for fixed ports, stands and applying migrations; push_deploys retains its
special stand constraint. A timeout alone never transfers a long lock.

Only after **all** number producers have migrated and the high-water mark has been
imported may the owner classify a number-only resource explicitly:

```yaml
resources:
  - name: requirement-numbers
    mode: sequence
    namespace: FR
    producers_migrated: true
```

Repository scope is default; `scope: program` selects program numbering. Dispatch
requires the connected namespace and refuses an old lock still held by another
WP. A sequence resource is not held for the duration of a WP. This classification
does not change shared path locks or waive migration format/order validation.

## Validation

Run `scripts/selftest.py` for the Claude compatibility baseline and
`scripts/runtime_selftest.py` for process concurrency, reservations, crash recovery,
paired instructions, client changes, dispatch and lock classification. Built archive
tests are separate from source checks. Actual CLI smoke results and untested
platforms are recorded in the repository validation report; local macOS success
does not certify Linux/Windows or cloud behavior.
