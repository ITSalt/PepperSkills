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
   `safe_edit.py --stdin`; do not rewrite the file and do not write fragments to temporary files.
   Where the plan depends on an open P-n, say so and reference the P-n; never write its
   recommended option as the plan until the owner's D-n exists.
4. **Separate decisions from work.** Product forks become P-n items with options, consequences and
   a recommendation (`orch.py owner add P ...`). Working assumptions become A-n
   (`orch.py decide A ...`). Packages that depend on an open P-n stay `DRAFT`.
5. **Cut work packages.** One module (stream) and one reviewable PR per package. Packages of
   different repositories run in parallel. In one repository, streams run in parallel when their
   paths do not overlap outside `shared_paths`; a module that is a whole repository has one
   writing session at a time. Contract changes several streams depend on (schema fields, shared
   types) go first, as their own package.

   ```bash
   python3 SKILL_DIR/scripts/orch.py new-wp <module> <slug> --title "<title>"
   ```

   Fill every section of the created file by point edits: header (mode, contract, depends on,
   size, optional specification IDs, decisions), facts, scope, not in scope, acceptance criteria.
   For a stream, also declare in advance, in backticks: **shared paths touched** (from the
   repository's `shared_paths`) and **resources** that need a lock (for example `migrations`),
   the migration rule, the line (base or a backport branch). Keep the generated sections 0, 4 and
   5 (worktree preparation, delivery, start prompt and command).
6. **Promote.** A package whose sections are complete and whose decisions are closed:
   `orch.py set <WP> status READY --evidence "sections complete"`. Fill the Waves table of
   `status.md` by point edit.
7. **Check overlaps.** `orch.py overlap --planned` lists declared overlaps between READY and
   active packages; resolve them by ordering (`Depends on`), by moving work into a contract
   package, or by accepting that the shared path is serialized by its lock.
8. **Verify and commit.** `orch.py lint`, then `orch.py commit "<program>: plan <topic>"`.

## Result for the owner

- Outcome: number of waves and packages, which are READY, which wait for answers.
- P-n questions with recommendations, in the owner format.
- Next step: `dispatch <WP>` for each READY package (it checks overlaps and locks and prints the
  start command). No `--settings` in this version; never invent a settings file.

Do not start sessions, merge, deploy or write to databases in this mode.
