# {{WP}} — {{WP_TITLE}}

| Field | Value |
|-------|-------|
| Repository | {{REPO}} |
| Base branch | {{BASE}} |
| Work branch | `{{BRANCH}}` |
| PR title | `[{{TAG}}] {{WP}}: {{WP_TITLE}}` |
| Mode | <methodology the session follows in its repository> |
| Session | `{{SESSION}}` |
| Contract | <contract version, or none> |
| Depends on | <WP ids, or none> |
| Size | <S / M / L> |
| Specification | <optional: requirement, use case or task IDs from any source; none> |
| Decisions | <D-n this package relies on, or none> |

## 1. Facts

Why the package is needed: verified facts with `file:line`, SELECT results and report
links. Facts, not retelling.

## 2. Scope

1. <item>

### Not in scope

- merge, deployment, production, database writes
- other modules and the orchestrator workspace
- version bumps and release notes unless listed above

## 3. Acceptance criteria

1. <verifiable: test, measurement, live scenario, SELECT>

## 4. Delivery

- PR from `{{BRANCH}}` to `{{BASE}}`; do not merge.
- PR body = development report + `Deviations` (what differs from this package and why).
- Then send `[{{TAG}}] READY {{WP}} :: <sha> :: ref=<PR URL>` to `{{COORDINATOR}}`.

## 5. Start prompt

```text
Read {{WP_PATH}} and implement it. Branch {{BRANCH}} from {{BASE}}, PR to {{BASE}}, do not merge. When done, send to {{COORDINATOR}}: [{{TAG}}] READY {{WP}} :: <sha> :: ref=<PR URL>
```

## Resubmissions

<REVISE rounds: date, items, commit.>
