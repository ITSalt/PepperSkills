# Linux Git-approved fixture evidence

**GIT_APPROVED_FIXTURE_PASS / AUTONOMY_NOT_RUN.**
[Detailed report](../../pepper-orchestrator-git-approved-linux.md).

- `git-approved-final.json`: five real turns, exact native command/stdout provenance,
  one scoped native filesystem decision, active sibling overlap, expiry/restart.
- `partial-before-harness-fix.json`: three requested turns; incomplete because the
  harness misread a resolved approval history entry as a new pending request.
  Its original BLOCKED verdict is retained. Executed source: `780cf09`.
- `surface-summary.json`: code-mode globals/tool inventory/import results derived
  from the final native raw custom-call/output pair, not an assistant summary.
- `cleanup.json`: both auth copies absent, known PIDs gone and no remaining owned
  fixture-cwd processes; archive responses and a zero-model cleanup run.
- `run-index.json`: exact refs, environment, model and interaction counts.

Final executed probe source: `50552a30cf299ce9ed6bcbac4a37c9c6d207fd21`.
Native CLI 0.165.0; Python 3.12.3; Ubuntu 24.04.5 LTS; kernel 6.8.0-147-generic.
Model fixed to gpt-6.1-sol, high. Eight explicit/native turn starts across both
trials, five in the final trial. Provider-internal inference/HTTP calls were not
instrumented. No native manual-UI approval clicks are claimed.

The human selected sandbox + explicit Git permissions for a disposable fixture.
The test owner used `--authorize-fixture-git-turn` to answer exactly one native
permissions request per fixture, only for its six pre-registered Git directories,
with `scope=turn`. This bounded test decision is not a production auto-approval
rule. No command `accept`, `acceptForSession`, rule amendment, session grant or
unsandboxed execution was authorized by the controller.

Each report uses `/PROTECTED/OWNER`, `/FIXTURE/WORK`, `/OPT/CODEX/codex` and
`/REDACTED/HOME` aliases. Cleanup distinguishes `/PROTECTED/TRIAL1` and `TRIAL2`.
Host/installation/account identifiers, reasoning content, verbose usage metadata
and socket peer addresses are omitted. Native thread/turn/call IDs, PIDs, epochs,
errno, tools, commands and output relations remain. Raw report hashes are recorded.
These are owner-captured observations, not cryptographic attestation for an
arbitrary untrusted JSON file. SHA256SUMS covers the canonical LF text exports.

The complete grant helper finished before its turn ended. Expiry proves that new
commands lack the previous grant; it does not prove revocation of an already-running
background process's sandbox. Background terminal lifecycle still needs explicit
integration checks before production session reuse.
