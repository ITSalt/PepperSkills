# {{WP}} — {{WP_TITLE}}

| Field | Value |
|-------|-------|
| Stream | {{MODULE}} ({{KIND}}) |
| Repository | {{REPO}} |
| Base branch | {{BASE}} |
| Line | {{LINE}} |
| Work branch | `{{BRANCH}}` |
| Worktree | {{WORKTREE}} |
| PR title | `[{{TAG}}] {{WP}}: {{WP_TITLE}}` |
| Session | `{{SESSION}}` |
| Model | {{MODEL}} |
| Effort | {{EFFORT}} |
| Model reason | {{MODEL_REASON}} |
| Mode | <methodology the session follows in its repository> |
| Methodology commands allowed | {{METHOD_ALLOWED}} |
| Methodology commands forbidden | {{METHOD_FORBIDDEN}} |
| Allowed paths | {{PATHS}} |
| Shared paths touched | <declared in advance: backticked paths from the list below, or none> |
| Migrations | <no, or yes and the numbering rule> |
| Resources (locks) | <backticked resources from the list below, or none> |
| Test DB and ports | {{TEST_ENV}} |
| Merge slot | <position in the merge queue, set when accepted> |
| Contract | <contract version, or none> |
| Depends on | <WP ids, or none> |
| Size | <S / M / L> |
| Specification | <optional: requirement, use case or task IDs from any source; none> |
| Decisions | <D-n this package relies on, or none> |

{{REPO_HINTS}}

## 0. Worktree preparation

{{WORKTREE_SETUP}}

## 1. Facts

Why the package is needed: verified facts with `file:line`, SELECT results and report
links. Facts, not retelling.

## 2. Scope

1. <item>

### Not in scope

- merge, deployment, production, database writes
- other modules and the orchestrator workspace
- files outside the allowed paths; shared paths that are not declared above
- version bumps and release notes unless listed above

## 3. Acceptance criteria

1. <verifiable: test, measurement, live scenario, SELECT>

## 4. Delivery

{{DELIVERY}}

## 5. Start prompt

```text
{{START_PROMPT}}
```

### Start command

Start command (for the owner, run in a new terminal):

```bash
{{START_COMMAND}}
```

{{START_NOTE}}

## 6. If a permission is denied

{{IF_DENIED}}

## Resubmissions

<REVISE rounds: date, items, commit.>
