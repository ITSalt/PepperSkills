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

## The owner says an item is done

1. Verify the fact yourself, read-only: `gh pr view`, `gh run view`, SELECT through a read-only
   tool, the version in the served bundle, a log line from the owner.
2. Matches: `orch.py owner close R-n "<verified fact>"`; update affected packages with
   `orch.py set <WP> status <STATUS> --evidence "<fact>"`.
3. Does not match: keep the item open, say what differs and what the owner should check.
4. The owner answered a P-n: record `orch.py decide D "<decision>" --closes P-n`, then update the
   packages that depended on it (point edits, statuses).
5. `orch.py lint` and `orch.py commit "<program>: owner queue <ids>"`.
