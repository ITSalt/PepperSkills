# Mode: verify

Verify a package on the stand (`test`) or in production (`prod`) by facts, after a merge or a
deploy, whoever made it (the owner, or a delivery mode later). Arguments: `<WP> --env test|prod
[--sha <sha>]`, or nothing: then list what waits (`orch.py verify --list`).

## Steps

1. **Plan.** `python3 SKILL_DIR/scripts/orch.py verify <WP> --env <env> --dry-run` prints the checks
   in order, the expected SHA (the merge commit of the package PR through `gh`, or `--sha`), the
   branch and the target status; it runs nothing and writes nothing. No checks configured: ask the
   owner for the read-only commands (P-n) and add them to `orch.yaml` by point edit:
   - `deploy_workflows` (a list, or `{test: [...], prod: [...]}`): the deploy run for this SHA on
     the environment's branch (`integration_branch` or the base for test, `prod_branch` or the base
     for prod) must have finished with `success`.
   - `version_url` (optionally `{base_url}`, `{env}`, or per environment) and `version_pattern` (a
     regular expression with one group): the served version must be the SHA (prefix of 7 or more
     characters) or `--expect-version`.
   - `verify_test` / `verify_prod`: read-only commands (health endpoint, migration journal through a
     SELECT-only client, smoke). They run in the repository's main checkout through the shell with
     `ORCH_ENV`, `ORCH_SHA`, `ORCH_WP`, `ORCH_BASE_URL` (from `web_urls`), with a timeout of
     `verify_timeout` seconds (default 300); a non-zero exit or a timeout is a failure. Secrets only
     as a reference to an environment variable of the owner (`$STAND_TOKEN`), never literally: `lint`
     refuses secret-looking strings, and output lines that look like secrets are redacted in the
     report.
2. **Run.** `orch.py verify <WP> --env <env> [--sha <sha>]`. Without `gh` it refuses when it needs a
   workflow run or a merge commit: read the run with the session's GitHub tools and pass `--sha`,
   or ask the owner. It writes `reports/verify-<WP>-<env>-<date>.md` (table: check, command or target,
   exit, first lines of output, verdict).
   - **PASS:** status `VERIFIED_TEST` (test) or `PROD` (prod); a package already past it keeps its
     status. `DONE` stays the orchestrator's decision after prod.
   - **FAIL:** the status stays, a journal line, a defect file `bugs/BUG-<n>-verify-<wp>-<env>.md`
     with the failed checks. An owner item is opened only when the next step needs the owner's
     rights (no successful deploy run: a deploy or a re-run). A failing command or a wrong served
     version goes to the module session as `REVISE` with the facts, or to a bug package.
3. **Live scenario** (after PASS of the checks above). Walk the package's acceptance criteria on
   the environment, as the concept section 9 describes, with the brief in
   [../verify-brief.md](../verify-brief.md):
   - command checks: the `orchestrator-verifier` agent (read-only, the configured verify commands
     and read-only queries only);
   - browser checks (`e2e: playwright`): a general subagent with the browser tools and the same
     brief;
   - record the result in the report's "Live scenario" section by point edit (`safe_edit.py`).
     A failure of the checking tool is not a product defect: use the fallback of the scenario, mark
     it; when nothing can check the criterion, the package stays without `VERIFIED_TEST` and does not
     go to production. A real mismatch: set the status back with `orch.py set <WP> status VERIFYING
     --evidence "<report>"`, write the defect, send `REVISE`.
4. **Commit.** `orch.py lint`, `orch.py commit "<program>: verify <WP> on <env>"`.

## Result for the owner

Verdict per environment with the report path; for FAIL, the defect and what happens next (REVISE,
a bug package, or the owner item with its command). Packages without `VERIFIED_TEST` are never
proposed for a release sheet.
