# Mode: deliver

Trusted delivery: the orchestrator merges an accepted package and runs the stand, the way the owner
would, only when the owner handed these levels over by a decision. Argument: `<WP>`, or `--check
<WP>` for the gates only.

## Handing delivery over (once per program)

By default the owner merges and deploys; every workspace before 0.9.0 behaves this way. Ask with
`decide` (P-n, owner format):

> Should the orchestrator merge accepted packages and run the stand for you? (a) merge and stand:
> the orchestrator merges each accepted PR with the repository's method, waits for the stand deploy,
> verifies it by facts and stops at the first failure (recommended for a new program after two clean
> batches); (b) merge only: you deploy and verify the stand; (c) nothing: you merge and deploy, as
> now. Production is a separate decision later (`release` mode).

Record the answer (`orch.py decide D "..." --closes P-n`), then
`orch.py delivery set merge orchestrator --decision D-n` (and `stand`). A level goes back with
`orch.py delivery set <level> owner`. Then `orch.py settings orchestrator` and a restart of the
orchestrator with its start command: the settings follow the levels (run and PR facts, the stand
commands verbatim); the plugin never edits a running session. `gh pr merge` stays denied in every
session: a merge happens only inside `orch.py deliver --apply`, never by a direct call.

The deploy command must be non-interactive: a script that asks for a TTY confirmation fails under
`deliver` (stdin is closed) and the level stays the owner's; never work around the confirmation.

## Steps for a package

1. **Accept the revision.** After a review verdict ACCEPTED:
   `orch.py accept <WP> <PR head sha> --report reports/<wp>-review-<date>.md`. `deliver` merges only
   this SHA; new commits after the review need a new review (gate G2).
2. **Merge queue.** With `merge_policy: sequential`, `orch.py merge add <WP> --pr <url>`; only the head
   of the queue is delivered, and only after the previous merge is `VERIFIED_TEST` (or
   `--after-failure D-n`: a decision recorded in decisions.md, written to the journal and the ledger).
3. **Gates.** `orch.py deliver --check <WP>` prints G1-G10 with facts: G1 accepted with a report; G2
   PR head = accepted SHA; G3 checks green; G4 open, mergeable, base = integration branch, title with
   `[TAG]` and the package id; G5 queue head and locks free; G6 repository `checks`; G7 no owner item
   of the package marked "blocks delivery", referenced decisions recorded; G8 checked by GitHub at
   merge time; G9 "graph: checked" in the review report when the package has a Specification; G10
   delivery still handed over and no hold (orch.yaml re-read before every action).
4. **Deliver.** `orch.py deliver --apply <WP>` when every gate is green: `gh pr merge <n> --repo <origin>
   --<merge_method> [--delete-branch]` (never `--admin`), status `MERGED`, the merge queue row, a row in
   `release/deliveries.md`, the journal. With `stand: orchestrator`: waits for the deploy run of the
   merge SHA (`deploy_workflows`, `gh run watch`, `run_timeout`) or runs `deploy_test`, then
   `orch.py verify <WP> --env test`; PASS gives `VERIFIED_TEST`. Then the live scenario (verify mode).
   A deploy run still in progress at verification ends with exit code 2: the package stays `MERGED`,
   no hold, no rollback; run `verify` again later. When GitHub has not reported the merge commit yet,
   `deliver` stops before the stand with a ledger row "merge SHA unknown".
   An invalid `orch.yaml` (for example a `merge_method` other than merge, squash or rebase, or a
   trusted level without a recorded decision) refuses every delivery.
5. **Refusals and failures.** A red gate refuses and journals the reason. GitHub refusing the merge
   (an approval needed, a red required check) becomes an owner item with the owner's command, never a
   bypass. A failed run or verification puts delivery **on hold** (`delivery.hold`), writes a defect,
   runs `rollback_test` when configured, and prints the REVISE text for the module session; the queue
   stands until `orch.py unhold "<reason>"` after the analysis (the orchestrator or the owner). The
   owner stops everything at any time with `orch.py hold "<reason>"` or `delivery.<level>: owner`.

Everything runs only through the commands of `orch.yaml`; nothing else is started. Still never ask a
module session to merge or deploy.
