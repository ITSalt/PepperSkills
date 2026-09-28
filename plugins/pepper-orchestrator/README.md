# Pepper Orchestrator

Portable Agent Plugin for the single-orchestrator (hub-and-spoke) method: one orchestrator
session plans work that spans several repositories, writes work packages for module sessions,
verifies their results and keeps all state in versioned Markdown files. Merge, deploy, production
and database writes stay with the owner, as ready one-line commands.

Installation and update models: [English guide](../../docs/installation-and-updates.md) ·
[Русская версия](../../docs/installation-and-updates.ru.md).

```text
/plugin marketplace add ITSalt/PepperSkills
/plugin install pepper-orchestrator@pepperskills
```

## Use

Say "plan X by the single-orchestrator concept", or use the short commands:

| Command | What it does |
|---------|--------------|
| `/pepper-orchestrator:init <program>` | workspace `features/<program>/` and `orch.yaml` |
| `/pepper-orchestrator:plan <task>` | facts -> plan -> work packages -> owner questions |
| `/pepper-orchestrator:resume` | read state, reconcile with reality, next step |
| `/pepper-orchestrator:owner` | owner queue as commands; on "done" verify and close |
| `/pepper-orchestrator:decide <text>` | record D-n / A-n / Q-n or open an owner question P-n |

Version 0.1.0 is the core (stage 1). Dispatch, review, verify, release and retro modes, reviewer
and verifier subagents, and PreToolUse guards come in later versions; until then the skill follows
the concept for those steps by instructions.

## When it fits

At least two repositories or roles, more than one session of work, production and regression risk,
owner decisions along the way. For one change in one repository it is overhead. Details and
boundaries: [concept](skills/pepper-orchestrator/references/concept.md).

## Layout

| Surface | Location | Portability |
| --- | --- | --- |
| Skill (core) | `skills/pepper-orchestrator/` | any agent that reads files and runs Python 3 |
| Workspace CLI | `skills/pepper-orchestrator/scripts/orch.py`, `safe_edit.py` | standard library + git |
| Templates (en, ru) | `skills/pepper-orchestrator/templates/` | portable |
| Short commands | `commands/` | Claude Code adapter |
| Plugin manifest | `plugin.json` | canonical; client manifests are generated |

Clients without cross-session messaging work too: the owner relays the one-line pointers, and
`resume` learns about pull requests from `gh pr list`.

Self-test: `python3 skills/pepper-orchestrator/scripts/selftest.py`.
