# Owner format: answers, R-n, P-n, D-n

Condensed from [concept.md](concept.md) section 10. Owner-facing files use `owner_language`
from `orch.yaml`; answers in chat use the owner's language.

## Answer shape

1. **Outcome first.** If something is not verified, say that first.
2. What was done, in two to five lines, with links to files (not retold reports).
3. What is needed from the owner: commands in code blocks, one block per action, in execution
   order, each copyable whole.

No internal labels the owner has not seen (explain a WP id once or name the change). Short.

## R-n: owner action

```text
<what> : <exact one-line command> ; expected: <output> ; then: <what happens next>
```

- The command runs as is: absolute paths or a leading `cd`, no placeholders left.
- Irreversible actions are always R-n items: merge, deploy, production, database writes,
  permissions, keys, infrastructure, store consoles.
- Add with `orch.py owner add R "<text>" --where <file>`.
- Close only after verifying the fact yourself: `orch.py owner close R-n "<verified fact>"`,
  for example `gh pr view 83: MERGED at 2026-09-27 14:02Z`.

## P-n: owner question

```text
<question> ; options: (a) <option and consequence> (b) <option and consequence> ; recommendation: (x) because <reason>
```

- Always give a recommendation. Product forks are never decided inside a work package.
- Add with `orch.py owner add P "<text>" --where <file>`.

## D-n, A-n, Q-n: decisions file

- Owner answer -> `orch.py decide D "<decision>" --closes P-n` (closes the question too).
- Working assumption -> `orch.py decide A "<assumption>"`; research question -> `decide Q`.
- A repeated owner requirement after an objection is a decision: record it and carry it out.
- Changed decisions are new entries naming the replaced one; old entries are never edited.

## On "done" from the owner

Verify by facts (`gh pr view`, `gh run view`, SELECT through a read-only tool, served bundle
version) before closing anything. If the fact does not match, say so and keep the item open.
