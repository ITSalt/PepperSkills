# Private STDIO Linux gate evidence

Source HEAD: `1776a223f977d40e10da45d1b59147f1a0ab54e6`.
[Detailed report](../../pepper-orchestrator-private-stdio-linux-2026-10-30.ru.md).

**BLOCKED / AUTONOMY_NOT_RUN; independently BLOCKED_GIT_PREPARATION.**

- `linux-private-stdio.json`: final unchanged worktree-root profile, owner send/receive,
  native dynamic lifecycle, exact commandExecution/stdout, pending approval, recovery.
- `api-preflight.json`: zero model turns, CLI/schema/native API evidence only.
- `bootstrap-error.json`: fixture configuration failure, zero turns; not sandbox evidence.
- `different-roots-excluded.json`: four exploratory turns with an umbrella root;
  its Git success is explicitly ineligible for acceptance.
- `cleanup.json`: all known owned PIDs absent and all test auth copies removed.
- `run-index.json`: exact source/OS/ancestor/model counts and remaining blockers.

Private paths use consistent `/PROTECTED/OWNER`, `/OPT/CODEX/codex`,
`/FIXTURE/WORK`, `/REDACTED/HOME` aliases. Server name/installation ID are aliases;
account telemetry and socket peer addresses are omitted. Native IDs, epochs,
PIDs, errno, commands and output relations remain. Each export records its raw
report SHA256. These are owner-captured logs, not cryptographic attestation or
permission to trust an arbitrary model-writable JSON file.

Model fixed to gpt-6.1-sol, high: eight explicit turn/start requests (four excluded,
four final), eighteen native token-usage notifications. Provider-internal inference
and HTTP request counts were not instrumented. No models were switched for success.

Offline validation:

```bash
python3 -B scripts/test-orchestrator-private-stdio.py  # 11 tests PASS
python3 -B scripts/test-orchestrator-mcp-probe.py      # 3 tests PASS
PYTHON=/tmp/pepper-stdio-check-venv/bin/python bash scripts/check.sh
```

Full-suite result: **NOT PASS / environment blocked**, exit 1 at
`scripts/test-install-links.sh`: `missing shell: zsh`. No global shell/CLI was installed.
The initial system-Python attempt stopped at missing `h11`; pinned build dependencies
were installed into an isolated temporary venv and that failure was resolved.
Global packages and native gate permissions were unchanged.

The venv run passed the main orchestrator selftest, 11 runtime tests, 19 reliability
tests, all 41 autonomy tests (including the Claude regressions), 3 historical MCP
tests and 11 new private-STDIO tests. Submission scenarios also passed. The full
suite stopped before the later install-docs/install-skill/build/archive/component
checks. No new package-validation claim is made. Rerun in an environment with zsh
to finish this independent offline-suite requirement.

`offline-checks-system-python.log` and `offline-checks-venv.log` preserve sanitized
output and exact exit codes. `offline-environment.json` records dependency versions
and raw-log hashes. `SHA256SUMS` covers the sanitized evidence files, including this
manifest; the live probe/native source hashes are also inside the main report.
