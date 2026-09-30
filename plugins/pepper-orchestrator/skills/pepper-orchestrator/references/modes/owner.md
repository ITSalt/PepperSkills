# Mode: owner

Show the owner queue as ready commands; on "done", verify by facts and close. Argument: none
(show the queue), or an item id with the owner's report (`owner R-3 done`).

## Show the queue

1. `python3 SKILL_DIR/scripts/orch.py queue`.
2. Answer in the owner format ([../owner-format.md](../owner-format.md)): outcome line (how many
   actions and questions wait), then R-n items in execution order, each command in its own code
   block with the expected output, then P-n questions with options and the recommendation.
3. Items that are stale (the fact already happened, or superseded) are verified and closed or
   dropped with a reason before showing the queue.
4. **Merges** (only with `delivery.merge: owner`; with `merge: orchestrator` the `deliver` mode merges
   and the owner gets FYI lines, not merge blocks) come from the merge queue (`orch.py merge list`),
   in its order, one block per merge:
   the merge command, then the wait before the next one. With `merge_policy: sequential`:
   "merge -> green stand deploy and health check -> rebase of the next package (a `REVISE`-style
   pointer to its session) -> its merge". Never print two merges of one sequential repository as
   one step.
5. If each merge into the base deploys production (`base_deploys: prod`), recommend releasing in a
   batch through a release sheet instead of merging package by package, and say why (every merge
   is a production release and a new tag).

## Archive items of a closed in-repo program

When the owner reports the archive R-n done: verify with `git ls-remote --tags origin
orch-<program>-closed-*` (tag present at the closeout commit) and `git ls-remote --heads origin
orch/<program>` (branch gone), then `orch.py owner close R-n "<facts>"` and `orch.py commit`.
The commit stays local: a closed in-repo program whose branch is gone from origin is never
pushed again (the branch would come back).

## The owner says an item is done

1. Verify the fact yourself, read-only: `gh pr view`, `gh run view`, SELECT through a read-only
   tool, the version in the served bundle, a log line from the owner.
2. Matches: `orch.py owner close R-n "<verified fact>"`; update affected packages with
   `orch.py set <WP> status <STATUS> --evidence "<fact>"`. A verified merge also runs
   `orch.py merge done <WP> --evidence "<fact>"`: it releases the package's path locks and names
   the next package to rebase; resource locks (the stand, migrations) are released with
   `orch.py lock release` after verification.
3. Does not match: keep the item open, say what differs and what the owner should check.
4. The owner answered a P-n: record `orch.py decide D "<decision>" --closes P-n`, then update the
   packages that depended on it (point edits, statuses).
5. `orch.py lint` and `orch.py commit "<program>: owner queue <ids>"`.
