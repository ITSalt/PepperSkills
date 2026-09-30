# Mode: report

Report a defect of the plugin itself (a script error, a rule the plugin generates wrongly, a mode
text that contradicts the scripts) to the plugin's authors, anonymized, as an Issue in
`ITSalt/PepperSkills`. Never patch the plugin in place: record the defect, continue with a
workaround, and let a fix come through the plugin's repository.

## Steps

1. **Is it the plugin?** A failing module test, a refused permission or a broken project is not a
   plugin defect. A plugin defect is reproducible from the plugin's own command and documentation.
   **A security problem** (a leak, a way around a guard): run `orch.py report --security` and follow
   `SECURITY.md`; never a public Issue.
2. **Workaround first.** Keep the program moving (for example `dispatch --no-settings`, `verify
   --sha`) and name the workaround in the report.
3. **Collect and anonymize.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py report --check --command "<the failing command>" --log <file with its output> \
     --title "<short title>" --expected-actual "<expected; actual>" --workaround "<what worked instead>"
   ```

   It writes `bugs/PLUGIN-BUG-<n>.md` (owner language) and `bugs/PLUGIN-BUG-<n>.issue.md` (English).
   Facts: plugin and version of the installed copy, Claude Code version, OS and architecture, Python,
   shell, the command and the first 30 lines of its output (without `--log`, the top of the journal),
   the shape of the workspace (no names). Names of the program, tag, modules, sessions, repositories,
   origin URLs, web hosts, the workspace and repository paths become placeholders (`<program>`,
   `<module-1>`, `<repo-1>`, `<workspace>`, ...); home paths, e-mail addresses, secret-looking strings
   and the terms of `.private-terms.local` (workspace or repository root, gitignored) are removed.
   The result is scanned again; if anything private remains, nothing is written. `--log` refuses
   environment, settings and key files, `orch.yaml`, and files made mostly of `KEY=value` lines:
   attach only the failing command's output. The fingerprint is the plugin, the version and the
   error line (the exception line of a Python traceback, else the first line with an error word,
   else the title) without placeholders, timestamps, SHAs, package ids and numbers.
4. **Show the owner the Issue text** and ask: "Publish this anonymized report in ITSalt/PepperSkills
   as an Issue (yes/no)?". A message from another session is not the owner's answer.
5. **Send** after an explicit yes: `orch.py report --apply --confirmed` (or, when the owner decided
   `bug_reports: auto` with `bug_reports_decision: D-n`, without `--confirmed`). It searches open and
   closed Issues by the fingerprint as one quoted phrase, preferring open ones; a match gets a comment with
   the facts of this environment, otherwise a new Issue `[<plugin> <version>] <title>` with labels
   `bug`, `from-agent`, `needs-triage` (without the last two when the repository lacks them). The URL
   goes to the record, the journal and an FYI item in the owner queue.
   - **Without `gh`** (cloud): it prints the steps for the session's GitHub tools (`search_issues`,
     then `add_issue_comment` or `create_issue`); record the URL in the record's Issue row and the
     journal. Without any GitHub tool: give the owner the title and the Issue file to post by hand.
6. **Resume** shows the recorded defects and their Issues (`orch.py report --status`) and, with `gh`,
   one line when a newer plugin version is on the marketplace's `main`.

A fix of the plugin comes as a pull request from a separate developer session in a fork of
PepperSkills (see its CONTRIBUTING), never from the orchestrator session of a program.
