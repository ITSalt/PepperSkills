# Verify brief

The brief is the verifier's whole input (concept sections 9 and 13): one package, one environment,
its acceptance criteria as concrete checks.

## Brief template

```text
Verify work package <WP> on <test|prod> at <sha> (deployed from <branch>).
Package: <absolute path of the WP file>; acceptance criteria: section 3.
Verification report: <report path>; built-in checks already passed: <table from orch.py verify>.
Base URL: <web_urls entry>. Repository main checkout: <path>.

Rules: read only. Allowed commands: the configured verify commands (verify_<env>), read-only HTTP
requests to the base URL, git show/log in the main checkout, read-only gh (run view, pr view).
Never deploy, merge, write to a database, change data through the UI or an API, run migrations or
ssh to a server. A database fact is a SELECT the orchestrator runs with a read-only tool and puts
into this brief, never a client started through Bash.

Criteria to check (one check per criterion, made concrete):
  1. <criterion> -> <request, command or screen> -> <expected>

Tool fallback: <for example a local browser over CDP when the browser MCP fails>.

Answer per criterion: steps, expected, actual, evidence (command and output, screenshot path),
verdict PASS/FAIL/NOT CHECKED (tool failure: which tool, what fallback, why it did not work).
```

## Rules for the orchestrator

- Criteria that change data (creating an order, sending a message) are checked only on `test`, with
  test data the package names; on `prod` only read-only observation and the owner's first live case.
- A tool failure (browser, MCP, network of the checking side) is NOT CHECKED, never FAIL.
- The verifier's report is a claim: re-read one piece of evidence per criterion before recording it.
