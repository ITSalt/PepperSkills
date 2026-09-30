---
description: Verify a package on the stand or in production by facts - deploy run, served version, verify commands, live scenario
argument-hint: <WP id> --env test|prod [--sha <sha>]
---

Invoke the `pepper-orchestrator:pepper-orchestrator` skill with the arguments
`verify $ARGUMENTS` and follow it: its hard rules, then `references/modes/verify.md`.

If the skill cannot be invoked, read `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator/SKILL.md`
and treat `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator` as `SKILL_DIR`. Mode: `verify`.

Arguments: $ARGUMENTS
