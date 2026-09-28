---
description: Resume an orchestrator program - read state files, reconcile with reality, do the next step
argument-hint: "[program]"
---

Invoke the `pepper-orchestrator:pepper-orchestrator` skill with the arguments
`resume $ARGUMENTS` and follow it: its hard rules, then `references/modes/resume.md`.

If the skill cannot be invoked, read `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator/SKILL.md`
and treat `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator` as `SKILL_DIR`. Mode: `resume`.

Arguments: $ARGUMENTS
