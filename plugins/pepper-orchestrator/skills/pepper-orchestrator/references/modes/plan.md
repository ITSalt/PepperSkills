# Mode: plan

Turn a request into facts, a plan, work packages and owner questions. Argument: the task in
free text. Requires a workspace; if none exists, run `init` first and say so.

## Steps

1. **Read state.** `status.md`, the tail of `decisions.md`, `PLAN.md`, `orch.yaml`. If the plan
   already exists, this is a re-plan: keep existing IDs, add or cancel, never renumber.
2. **Find facts, delegated.** Anything that needs many files or long runs goes to read-only
   subagents where the client has them (otherwise do it yourself, read-only). Brief each one per
   concept section 13: goal, inputs, constraints (read-only, no edits, database SELECT only),
   specific questions, answer format. Collect facts with `file:line`, SELECT results, log lines.
   A `spec_graph` other than `none` is only another read-only source of facts.
3. **Write `PLAN.md` by point edits.** Goal, scope and not in scope, modules, facts, waves with
   verifiable gates, risks. Replace the template placeholders section by section with
   `safe_edit.py`; do not rewrite the file.
4. **Separate decisions from work.** Product forks become P-n items with options, consequences and
   a recommendation (`orch.py owner add P ...`). Working assumptions become A-n
   (`orch.py decide A ...`). Packages that depend on an open P-n stay `DRAFT`.
5. **Cut work packages.** One module and one reviewable PR per package; independent packages
   of different modules can run in parallel; one writing session per repository at a time.

   ```bash
   python3 SKILL_DIR/scripts/orch.py new-wp <module> <slug> --title "<title>"
   ```

   Fill every section of the created file by point edits: header (mode, contract, depends on,
   size, optional specification IDs, decisions), facts, scope, not in scope, acceptance criteria,
   delivery. Keep the generated start prompt.
6. **Promote.** A package whose sections are complete and whose decisions are closed:
   `orch.py set <WP> status READY --evidence "sections complete"`. Fill the Waves table of
   `status.md` by point edit.
7. **Verify and commit.** `orch.py lint`, then `orch.py commit "<program>: plan <topic>"`.

## Result for the owner

- Outcome: number of waves and packages, which are READY, which wait for answers.
- P-n questions with recommendations, in the owner format.
- Next step: dispatch of the READY packages (start commands come from the `Start prompt` section
  of each package; concept section 18 has the command shape).

Do not start sessions, merge, deploy or write to databases in this mode.
