---
description: Show the owner queue as ready commands, or verify and close an item the owner reports done
argument-hint: "[R-n|P-n and the owner's report]"
---

Invoke the `pepper-orchestrator:pepper-orchestrator` skill with the arguments
`owner $ARGUMENTS` and follow it: its hard rules, then `references/modes/owner.md`.

If the skill cannot be invoked, read `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator/SKILL.md`
and treat `${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator` as `SKILL_DIR`. Mode: `owner`.

Arguments: $ARGUMENTS
