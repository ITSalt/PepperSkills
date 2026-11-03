# Research packages and the control tick

This contract applies to every client (Claude Code and Codex) and to both executors of
research: the coordinator's own subagents and a separately launched session. It makes the
coordinator manage research to a decision: collect within a budget, decide after every wave,
hand the result over and move on. Proactive control comes from the timer; a tick ends in a
decision, never in another open-ended investigation.

## Bounded collection and acceptance

Mark research packages with `| Execution | research |` in their first metadata table,
including older programs whose prose already defines research. Research dependencies are
accepted reports (ACCEPTED or DONE).

Every research package has one question, the reader's decision, one primary artifact and at
most 8 criteria, each with the evidence that is sufficient and whether an unknown is allowed.
Each requirement has one owning WP. Corpus, oracle, baseline and experiment preparation budgets
belong to the experimental package, never to the static findings that precede it. A package
that would need more criteria is several packages.

Use `orch.py research EVENT --wp WP --file JSON_PATH`; `research status --wp WP` is read-only.
The sessions registry keeps contracts, rounds, outstanding tasks, returned results and verdicts
across /clear and restart. The JSON input file may be temporary.

* `contract`: question, decision, artifact and criteria (`evidence_standard`, boolean
  `unknown_allowed`). The contract is frozen; a scope change is a separately planned package.
* `start`: stable id and tasks, each with id, criterion, `missing_fact` and the `decision` the
  answer changes. Record the tasks before starting subagents. Native `autonomy launch` records its
  collection itself. One initial wave and one scoped correction are the maximum.
* `result`: stable id, task and an evidence path inside the workspace. Save the subagent answer or
  the session transcript first, then record it the same way for either executor. Once every task
  has returned, `next` proposes `review_research`, not another investigation.
* `verdict`: stable id, verdict and an assessment of every frozen criterion (`satisfied`,
  `unknown` or `blocked`, with reason and evidence). Unknown is acceptable only where the
  contract allows it. Review may ask for corrections only against frozen criteria.
  * `accepted`: every criterion resolved. Set the WP ACCEPTED, then DONE.
  * `revise`: one scoped correction, only in round 1.
  * `partial`: at least one criterion resolved. `remainder` names, for every unresolved
    criterion, the other WP that owns it (`owner_wp`) and the `condition` that resolves it.
    The coordinator sets the WP ACCEPTED, then DONE: dependents continue on what was resolved,
    the remainder lives in its owner.
  * `blocked`: nothing usable yet; `remainder` names the `condition` for every criterion.
    `unblock` with new evidence returns it to review, never to a new open collection.

The decision whether evidence is sufficient belongs to the coordinator, not to the owner.
Record it with the verdict and its reasons; the owner may challenge it later but is not asked to
make it. Owner items stay for product forks and irreversible actions.

After every wave decide. An interesting adjacent question becomes a note in the WP that owns it
and does not extend the current collection. Create a new research package for it only when its
answer changes a decision of the program goal; record that reason in `decisions.md`. A graph
outage or an unknown experimental budget limits that experiment: submit the static conclusions
with their limits. Do not claim acceleration without measurement.

## The control tick

The watcher raises a signal at once when a fact changes (a session result, a PR, CI, a status,
an owner answer). An action that stays unhandled is raised again after `interval_seconds`
(600 by default); items waiting only on the owner are raised every sixth interval. The
coordinator's own commits, journal lines and cosmetic report edits are not facts and raise
nothing. A Monitor expiry or a `CronCreate` fallback tick is the same control tick.

On every tick, in this order:

1. **Progress.** For each active package compare its state with its criteria and round budget.
2. **Stalls.** `stalled` actions (no file change, commit, index update or push for
   `stall_minutes`, 45 by default, while the session is not busy, or a research collection whose
   results were never recorded) need a step: inspect the session and its processes, nudge, restart
   or reassign it, or record the returned results.
3. **Decide.** Accept, accept partially, send a scoped REVISE, launch or dispatch the next
   compatible READY package, or tell the owner about a real deadlock.

A tick opens collection only as `continue_research` inside the recorded budget. When there is
nothing to decide, end the turn without writing anything.

## Goals and loops (Claude Code)

`/goal`, `/loop`, `ScheduleWakeup` and `CronCreate` are management tools of the coordinator.
Use them with bounds:

- the completion condition is measurable and taken from the package contract or acceptance
  criteria (`research status` phase `accepted`/`partial`, the artifact at its path, the WP status
  in `status.md`, a merged PR), never "until nothing useful remains";
- the iteration or time limit equals the round budget (two waves for research), or the review
  escalation for code packages (round 3);
- every iteration ends with a verdict. When the limit is reached, submit the available result as
  `partial` or `blocked` yourself and clear or reset the goal.

A module session may get a `/goal` from the coordinator on the same terms: the condition comes
from its acceptance criteria and the limit is stated. On resume, list active goals and
`CronList` and compare their conditions with the registry; drop the ones whose package is done.
