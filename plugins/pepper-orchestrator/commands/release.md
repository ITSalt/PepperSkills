---
description: Production release by a release sheet - gates P1-P7 by facts, promote, prod deploy, verification (only when the owner handed prod over)
argument-hint: --plan | --check [<sheet>] | --apply [<sheet>]
---

Invoke the `pepper-orchestrator:pepper-orchestrator` skill with the arguments
`release $ARGUMENTS` and follow it: its hard rules, then `references/modes/release.md`.

If the skill cannot be invoked, read `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator/SKILL.md`
and treat `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator` as `SKILL_DIR`. Mode: `release`.

Arguments: $ARGUMENTS
