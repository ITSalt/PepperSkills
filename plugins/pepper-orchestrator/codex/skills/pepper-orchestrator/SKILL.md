---
name: pepper-orchestrator
description: Coordinate owner-launched Codex CLI module sessions, work packages, independent review and verification, and the owner queue across repositories or Git worktrees. Keep state in files; preserve Claude programs and project instructions.
metadata:
  version: 0.9.0
---

# Pepper Orchestrator for Codex CLI

Read [the Codex workflow](../../../skills/pepper-orchestrator/references/codex.md)
before acting. Its launch, role and messaging rules apply to Codex. The common
program methodology remains the same: only the orchestrator writes program state,
only module sessions write module code, and irreversible actions remain owner items.

Use the bundled common CLI at `../../../skills/pepper-orchestrator/scripts/orch.py`.
In an installed archive the build supplies the same scripts, templates and
references inside this skill directory; no separate editable core exists.

Modes: `init`, `plan`, `dispatch`, `review`, `verify`, `resume`, `owner`, `decide`,
`close`, `reopen`, `report`. Select the mode from the user's intent or arguments.
Create Codex programs with `init --client codex --sessions local`. Missing `client`
in existing programs means Claude: use explicit sequential client switching.

Do not use Claude model aliases, `claude` flags, Claude settings files or SendMessage
for Codex sessions. Independent module sessions are started by the owner. Use native
subagents only for scoped research, review and verification; they do not replace
those module sessions. Read both CLAUDE.md and AGENTS.md, including actual case
variants and nested rules. Never edit another module's files or resolve conflicting
project instructions silently.
