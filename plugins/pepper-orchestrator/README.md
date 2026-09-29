# Pepper Orchestrator

> **Preview (0.5.0).** Modes `init`, `plan`, `dispatch`, `review`, `resume`, `owner`, `decide`,
> `close`, `reopen`;
> streams in one repository with worktrees and locks; cloud sessions.
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
| `/pepper-orchestrator:review <WP> [PR]` | automatic findings, reviewer agent, verdict, report |
| `/pepper-orchestrator:resume` | read state, reconcile with reality, next step |
| `/pepper-orchestrator:owner` | owner queue as commands; on "done" verify and close |
| `/pepper-orchestrator:decide <text>` | record D-n / A-n / Q-n or open an owner question P-n |
| `/pepper-orchestrator:close [result]` | goal reached: completion check, closeout report, archive |
| `/pepper-orchestrator:reopen <reason>` | reopen a closed program whose goal is not reached |

Version 0.5.0 is a preview (stages 2a-2e). Modules can be whole repositories or areas and
domains of one repository: each stream runs in its own worktree (`claude -w`), shared paths and
resources are held by locks, merges into one repository go through a queue. `review` runs a
read-only reviewer agent with a disposable clone on the first submission and reads the revision diff
on resubmissions. Verify, release and retro modes and PreToolUse guards come in later versions;
until then the skill follows the concept for those steps by instructions.

## Typical workflows

Locally use the short commands (`/pepper-orchestrator:plan ...`); in a cloud session, where plugin
commands are not installed, call `/pepper-orchestrator <mode> ...` or use a phrase.

1. **New program, separate home repository.** `init <program>` (answer the session-kind question) -> `plan <task>` -> answer the
   owner questions with `decide` -> `dispatch <WP>` -> the owner starts the module session with the
   printed command or prompt -> the session opens a PR -> `resume` finds it -> `review <WP>` ->
   the owner merges -> "R-n done" to `owner` -> the orchestrator verifies the fact and closes it.
2. **New program in the cloud, one repository.** Start a cloud session on the base branch and run
   `/pepper-orchestrator init <program> --in-repo <repo-id>`: it creates and pushes branch
   `orch/<program>`. From then on **every** orchestrator cloud session starts on
   `orch/<program>` (choose the branch when starting the session).
3. **Every next session.** Run `resume`: locally in the home repository, in the cloud on
   `orch/<program>`. `init` is not needed again; on an existing workspace the skill switches to
   `resume` by itself. The first message for a new session is in
   `orchestration/bootstrap-prompt.md`.
4. **A plan already exists.** Give its text or path to `plan`: it turns it into work packages. Running
   `plan` again is a re-plan: IDs are kept, packages are added or cancelled.
5. **New work in an existing program.** `plan <task>`, not `init`.
6. **Module sessions.** `dispatch` prints a terminal command (`claude -w <slug>` for a stream of a
   shared repository) or a prompt for a new cloud session on the base branch. The module delivers a
   PR with the package id in its body. The orchestrator learns readiness from a READY message
   where messaging works, otherwise from the PR and the pushed branch (`resume`, `orch.py ready`).
7. **Owner queue.** `owner` shows actions and questions as commands; "R-3 done" makes the
   orchestrator verify and close; `decide <text>` records the owner's answers.
8. **Parallel streams in one repository.** Modules can be areas or domains of one repository with
   their own paths; shared paths and resources are taken by locks, merges go through a queue
   (concept, sections 7 and 12).
9. **Update.** Locally in a terminal `claude plugin update pepper-orchestrator@pepperskills`, or in a
   session `/plugin` -> Installed -> the plugin -> Update now; auto-update is off by default for
   third-party marketplaces such as this one. In the cloud change the comment line of the
   setup-script fragment below, so the environment rebuilds.
10. **Goal reached -> `close`.** One program, one goal: when the completion condition in
    `PLAN.md` holds, run `close` (it checks packages, PRs, locks and owner items by facts; carry
    leftovers with `orch.py owner carry <id> "<reason>"`), then start the next goal as a new
    program with `init`. In-repo, the owner runs the printed tag and branch-deletion commands.

## Models and environment

- **Session kind.** `init` asks you whether module sessions run locally (recommended) or in the
  cloud; cloud needs the name of your cloud environment. An orchestrator running in the cloud
  works only with cloud sessions.
- **Implementer model.** Each work package has Model, Effort and Model reason, filled from
  `orch.yaml` (`models.implement`, module `model`/`effort`); the orchestrator recommends `opus` +
  `high` for risky packages (`orch.py model <WP> opus --effort high --reason "..."`). Local start
  commands carry `--model`/`--effort`; cloud packages come with a block naming the environment,
  model and effort and a claude.ai/code prefill link. From review round 3 the orchestrator
  suggests a restart on `models.escalate`.
- **Do not** type `/model <name>` with an argument in a local session to switch a module: it
  becomes your default for every new session. Use the start flags or the `/model` picker with `s`.
  Do not set `ANTHROPIC_MODEL` in a cloud environment shared with the orchestrator, and keep
  secrets out of environment variables.
- Agents: `orchestrator-scout` runs on Opus; `orchestrator-reviewer` runs on the orchestrator's
  model.

## Cloud sessions

Cloud sessions (claude.ai/code) do not install plugins from project settings, and a session must
not write to `.claude/`. Give them the skill through the cloud environment's **setup script**,
which runs before Claude starts; files it writes stay in the environment:

```bash
# pepper-orchestrator skill (PepperSkills); change this comment to refresh the cached environment.
# A failure here must not block the environment: the subshell reports it and setup continues.
(
  set -e
  pepper_dir="$HOME/.cache/pepperskills"
  if [ -d "$pepper_dir/.git" ]; then
    git -C "$pepper_dir" pull --ff-only -q
  else
    git clone -q --depth 1 https://github.com/ITSalt/PepperSkills "$pepper_dir"
  fi
  bash "$pepper_dir/scripts/install-skill.sh" pepper-orchestrator
) || echo "pepper-orchestrator: skill not installed; setup continues" >&2
```

A non-zero exit of a setup script stops every session of the environment from starting, so the
fragment never fails: a clone or install error is printed and setup goes on without the skill.
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
| Agents `orchestrator-reviewer`, `orchestrator-scout` | `agents/` | Claude Code adapter; elsewhere the same brief goes to any subagent |
| Plugin manifest | `plugin.json` | canonical; client manifests are generated |

Clients without cross-session messaging work too: the owner relays the one-line pointers, and
`resume` learns about pull requests from `gh pr list`.

Self-test: `python3 skills/pepper-orchestrator/scripts/selftest.py`.
