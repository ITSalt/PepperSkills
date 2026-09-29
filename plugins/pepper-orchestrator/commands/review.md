---
description: Review a module session's pull request - automatic findings, reviewer agent, verdict, report
argument-hint: <WP id> <PR URL> --ref <PR head sha> [--since <previous sha> --round <n>]
---

Invoke the `pepper-orchestrator:pepper-orchestrator` skill with the arguments
`review $ARGUMENTS` and follow it: its hard rules, then `references/modes/review.md`.

If the skill cannot be invoked, read `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator/SKILL.md`
and treat `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator` as `SKILL_DIR`. Mode: `review`.

Arguments: $ARGUMENTS
