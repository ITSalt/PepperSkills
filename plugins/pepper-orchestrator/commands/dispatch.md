---
description: Dispatch a READY work package - checks dependencies, overlaps and locks, prints the start command
argument-hint: <WP id> [live]
---

Invoke the `pepper-orchestrator:pepper-orchestrator` skill with the arguments
`dispatch $ARGUMENTS` and follow it: its hard rules, then `references/modes/dispatch.md`.

If the skill cannot be invoked, read `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator/SKILL.md`
and treat `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator` as `SKILL_DIR`. Mode: `dispatch`.

Arguments: $ARGUMENTS
