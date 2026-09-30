# Mode: release

Production by the orchestrator: a batch of packages verified on the stand goes to prod by a release
sheet, through gates by facts, only when the owner handed `prod` over by a decision. Arguments:
`--plan`, `--check [<sheet>]` or `--apply [<sheet>]` (default: the newest sheet not on prod yet).

## Handing production over (once per program)

By default the owner releases; the sheet (`orch.py release --plan`) is useful to the owner as it is.
Production needs `merge` and `stand` handed over first (`deliver` mode). Ask with `decide` (P-n,
owner format), best after two clean batches on the stand:

> Should the orchestrator release to production for you? (a) yes, in batches by a release sheet:
> it promotes the exact SHA that passed the stand, waits for the prod deploy, verifies it and stops
> at the first failure; database migrations stay yours (recommended); (b) yes, migrations included
> (after a first clean prod cycle); (c) no, you release, as now.

Record the answer (`orch.py decide D "..." --closes P-n`), then
`orch.py delivery set prod orchestrator --decision D-n` (and for (b)
`orch.py delivery set prod_migrations orchestrator --decision D-n`), then `orch.py settings
orchestrator` and a restart of the orchestrator with its start command. The settings allow
`verify_prod`, `backup_prod` and `rollback_prod` (`ask` when `rollback` is in `checkpoints`); the
promote PR, its merge and a promote push happen only inside `orch.py release --apply`, never by a
direct call.

Configuration (`orch.yaml`): `delivery.release_policy: batch | per_package` (default `batch`;
`per_package` for projects without a database or a store), `release_window: "Mon-Fri 10:00-18:00
Europe/Berlin"` (days, hours and a zone: an IANA name, `UTC` or an offset such as `+03:00`; days also
`Пн-Пт`; empty = no limit), `max_prod_releases_per_day`. Per repository: `integration_branch` (the
stand), `prod_branch` (production; must differ), `deploy_workflows` (`{test: [...], prod: [...]}` or
one list), `verify_prod` (read-only), `backup_prod` (required before migrations), `rollback_prod`
(`{previous_sha}` is the prod tip before the release; empty = no rollback, the owner gets the
command), `promote: pr | ff` and for `ff` a clean `release_clone`.

## Steps

1. **Sheet.** `orch.py release --plan` writes `release/release-sheet-<date>.md`: the `VERIFIED_TEST`
   packages by repository with the SHA each passed the stand at (the evidence of its verification),
   migrations (the package's Migrations row), the promote SHA per repository (the stand SHA that
   contains the others), open defects and self-contained steps with expectations. With
   `release_policy: per_package` a sheet of one package is written right after its `VERIFIED_TEST`.
2. **Gates.** `orch.py release --check [<sheet>]` prints P1-P7 with facts: P1 the promote SHA is the
   tip of `origin/<integration_branch>` (for `ff`: on it), every package's stand SHA is in it, prod
   has no commit the stand never saw (merge commits of earlier promotes aside; `ff` needs prod to be
   an ancestor), a clean `release_clone` for `ff`; P2 every package of the sheet is `VERIFIED_TEST`;
   P3 no open defect of severity blocker, critical or high in `bugs/`; P4 migrations: with
   `prod_migrations: owner` an owner item `R-n` (once) and stop; with `orchestrator` the review
   report of each package says `migrations: safe, reversible` and `backup_prod` is set; P5 inside
   the release window and under the daily limit (releases in the ledger); P6 `prod: orchestrator`
   and no hold after re-reading `orch.yaml`, configuration valid; P7 after the release. P1 also
   refuses a sheet planned for other branches or another promote method than `orch.yaml` now has,
   and a promote SHA that would ship another package not in the sheet (merged, not on prod yet):
   release such packages together in a batch sheet, or in merge order. With `per_package` and
   `promote: pr` release a package before the next merge into the integration branch (the PR
   promotes the branch tip); `promote: ff` can ship an older stand SHA.
3. **Release.** `orch.py release --apply [<sheet>]` when P1-P6 are green, per repository: runs
   `backup_prod` when the batch has migrations (output in the ledger; a failure stops before
   anything changes), promotes (a PR `integration_branch` -> `prod_branch` titled `[TAG] release
   <date>` with the sheet as body, its checks waited for, merged with `--merge` so prod contains the
   stand SHA (a repository that allows only squash or rebase merges refuses it: use `promote: ff`); or `git push origin <sha>:refs/heads/<prod_branch>` from the clean clone, never
   forced), waits for the prod deploy run (`deploy_workflows`, `run_timeout`), then `orch.py verify
   <WP> --env prod --sha <prod SHA>` for every package; PASS gives `PROD`, a ledger row and an FYI
   item in the owner queue. A run still in progress at verification ends with exit code 2: verify
   again later, no hold.
4. **Failure.** A failed prod run or verification puts every delivery **on hold**, writes a defect
   and runs `rollback_prod` only for a batch without migrations; otherwise (no `rollback_prod`, a
   batch with migrations, or a failed rollback) an owner item with the ready rollback command (a
   revert PR of the promote when no `rollback_prod` is set). The orchestrator never rolls back a
   database. `orch.py unhold "<analysis>"` after the analysis; the defect is closed with a fact first
   (P3 blocks the next release until then).
5. **DONE** stays the orchestrator's after the first live case or log line (`verify` mode).

GitHub refusing the promote (an approval, a red required check) becomes an owner item, never a
bypass; a later successful promote of the same sheet closes it. Every release is a row of
`release/deliveries.md` (backup, promote, prod SHA, run, verification, rollback); `close` puts the
ledger into the closeout. Still never ask a module session to merge, deploy or release.
