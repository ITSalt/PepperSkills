# Pepper Orchestrator

> **Preview (0.2.1).** Modes `init`, `plan`, `dispatch`, `resume`, `owner`, `decide`; streams in one
> repository with worktrees and locks.
> Formats and commands may change before 1.0.0.

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
| `/pepper-orchestrator:dispatch <WP>` | checks overlaps and locks, prints the start command |
| `/pepper-orchestrator:resume` | read state, reconcile with reality, next step |
| `/pepper-orchestrator:owner` | owner queue as commands; on "done" verify and close |
| `/pepper-orchestrator:decide <text>` | record D-n / A-n / Q-n or open an owner question P-n |

Version 0.2.0 is a preview (stage 2a). Modules can be whole repositories or areas and domains of
one repository: each stream runs in its own worktree (`claude -w`), shared paths and resources are
held by locks, merges into one repository go through a queue. Review, verify, release and retro
modes, reviewer and scout subagents and PreToolUse guards come in later versions; until then the
skill follows the concept for those steps by instructions.

## Cloud sessions

Cloud sessions (claude.ai/code) do not install plugins from project settings, and a session must
not write to `.claude/`. Give them the skill through the cloud environment's **setup script**,
which runs before Claude starts; files it writes stay in the environment:

```bash
# pepper-orchestrator skill (PepperSkills); change this comment to refresh the cached environment
pepper_dir="$HOME/.cache/pepperskills"
if [ -d "$pepper_dir/.git" ]; then
  git -C "$pepper_dir" pull --ff-only -q
else
  git clone -q --depth 1 https://github.com/ITSalt/PepperSkills "$pepper_dir"
fi
bash "$pepper_dir/scripts/install-skill.sh" pepper-orchestrator
```

`install-skill.sh` is idempotent: it copies `plugins/<name>/skills/<name>` into
`~/.claude/skills/<name>` (or `--dest`) and prints the version. The environment is cached after
the first run, so the skill is refreshed when the setup script changes or the cache expires.

In a cloud session there are no plugin commands: call `/pepper-orchestrator <mode> <arguments>`
(for example `/pepper-orchestrator resume`) or use a phrase. A cloud program keeps its workspace
in the repository on branch `orch/<program>` (`init --in-repo`), module sessions are cloud sessions
started from the prompt `dispatch` prints, and readiness is found by branches and pull requests.

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
