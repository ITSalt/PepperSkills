# Mode: decide

Record a decision `D-n`, an assumption `A-n`, a research question `Q-n`, or open an owner
question `P-n`. Argument: free text, optionally starting with the kind.

## Classify

| Text | Kind | Command |
|------|------|---------|
| the owner decided, or answered an open P-n | `D` | `orch.py decide D "<decision>" [--closes P-n] [--source "<where>"]` |
| we proceed as if something is true until disproved | `A` | `orch.py decide A "<assumption>"` |
| something to find out (by us, not the owner) | `Q` | `orch.py decide Q "<question>"` |
| a product fork that needs the owner | `P` | `orch.py owner add P "<question ; options ; recommendation>" --where <file>` |

A repeated owner requirement after an objection is a `D`: record it and carry it out in full.

## Then

1. Find the work packages affected (search the workspace for the P-n or the topic). Packages not
   yet dispatched are edited by point edits; dispatched ones get a "re-read the package" pointer
   (`[TAG] ANSWER <WP> :: re-read, see D-n :: ref=<path>`), relayed by the owner where the client
   has no cross-session messaging.
2. A package that becomes untenable: `orch.py set <WP> status "CANCELLED (<reason>, D-n)"`.
3. `orch.py lint` and `orch.py commit "<program>: record <ids>"`.
