# Pepper Orchestrator

> **Preview (0.9.0).** Modes `init`, `plan`, `dispatch`, `review`, `verify`, `resume`, `owner`, `decide`,
> `close`, `reopen`, `report`;
> streams in one repository with worktrees and locks; cloud sessions; generated session settings.
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
| `/pepper-orchestrator:verify <WP> --env test\|prod` | deploy run, served version, verify commands, live scenario |
| `/pepper-orchestrator:resume` | read state, reconcile with reality, next step |
| `/pepper-orchestrator:owner` | owner queue as commands; on "done" verify and close |
| `/pepper-orchestrator:decide <text>` | record D-n / A-n / Q-n or open an owner question P-n |
| `/pepper-orchestrator:close [result]` | goal reached: completion check, closeout report, archive |
| `/pepper-orchestrator:reopen <reason>` | reopen a closed program whose goal is not reached |
| `/pepper-orchestrator:report [what]` | report a defect of the plugin: anonymized record, Issue after your yes |

Version 0.9.0 is a preview (stages 2a-2e, 3a, 3b, 3e). Modules can be whole repositories or areas and
domains of one repository: each stream runs in its own worktree (`claude -w`), shared paths and
resources are held by locks, merges into one repository go through a queue. `review` runs a
read-only reviewer agent with a disposable clone on the first submission and reads the revision diff
on resubmissions. `verify` checks the stand and production by facts. Release and retro modes and
PreToolUse guards come in later versions; until then the skill follows the concept for those steps
by instructions.

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
11. **Checking the stand and production by facts.** After you merge (and the stand or production
    deploys), `verify <WP> --env test` checks the deploy run for the merge commit, the version the
    environment serves (`version_url`) and the repository's read-only `verify_test` commands, then
    walks the package's acceptance criteria as a live scenario. PASS gives `VERIFIED_TEST` (after a
    release, `--env prod` gives `PROD`); FAIL keeps the status and writes a defect to `bugs/`.
    `orch.py verify --list` shows what waits; only `VERIFIED_TEST` packages go into a release.
12. **A stream got a refusal.** The session does not work around it: it sends
    `QUESTION <WP> :: denied: <exact text> :: ref=<command>`. The orchestrator answers on the facts:
    a narrow rule that is missing (a test command, a generator) goes into `orch.yaml` and
    `orch.py settings <module>`, then the session is restarted with the same command (or you answer
    the prompt in its window); an action only the owner does (merge, deploy, production) becomes an
    owner item. "Classifier unavailable" is not a verdict: the session retries later.
13. **The plugin broke - report it.** When the plugin itself is wrong (a script error, a wrong
    generated rule), the orchestrator keeps the program going with a workaround and runs `report`:
    `orch.py report --check` writes an anonymized `bugs/PLUGIN-BUG-<n>.md` (names of your program,
    modules, sessions and repositories, paths, addresses, e-mails, tokens and the terms of your
    gitignored `.private-terms.local` become placeholders) and shows the Issue text. After your
    explicit yes, `orch.py report --apply --confirmed` comments on a matching Issue in
    ITSalt/PepperSkills or opens a new one (labels `bug`, `from-agent`, `needs-triage`); with
    `bug_reports: auto` and your decision D-n it sends without asking. Security problems go through
    SECURITY.md. `resume` lists the reports and says when a newer plugin version is available.

## Session permissions and permission mode

- **Permission mode.** `init` asks which mode the program's sessions run in (`auto` recommended,
  or `acceptEdits`, `default`, `dontAsk`, `bypassPermissions`) and writes `permission_mode`.
- **Settings files.** `orch.py settings all` writes `orchestration/settings/<module>.json` for every
  local module and `orchestrator.json`: narrow allow rules (reading the repository and the
  workspace, `cat`/`grep`/`rg`/`sed -n`/..., git status/diff/log/add/commit/switch, `gh pr
  create`, the module's tests, checks and worktree setup verbatim), deny rules (merge, force
  pushes and pushes to the base in their usual forms, `gh workflow run`, `gh release`, production
  MCP servers and deploy commands, editing the orchestrator workspace, forbidden methodology commands as
  `Skill(<name>)`), owner checkpoints as ask rules (`checkpoints`, default `deploy_test`),
  `autoMode.environment` (`$defaults` plus the trusted repository) and
  `crossSessionInbound: accept`. There is no allow rule for `git push`: a `*` tail would also match
  `<branch>:<base>` and force flags, so pushes go to the classifier (or ask you with the `push`
  checkpoint). The command is idempotent; your own additions go to
  `<name>.local.json`, which it never touches and `dispatch` never passes.
- **Start commands.** `dispatch` adds `--permission-mode <mode> --settings <absolute path>` to every
  local start command and refuses while the file is missing; `init` prints the orchestrator's
  command: `cd <workspace> && claude --name <program>-coord --permission-mode <mode> --settings
  orchestration/settings/orchestrator.json`. Cloud sessions take their permissions from the cloud
  environment.
- **Message delivery.** Without `crossSessionInbound: accept`, messages between sessions of
  different permission classes (bypass against auto, acceptEdits, dontAsk, default) wait for your
  approval in the receiver's window and are dropped after 5 minutes. Alternative for all your
  sessions: `/config` -> "Messages from your other sessions" -> accept. The protocol never relies on
  messages: READY is also found by the PR and the pushed branch.
- **Worktrees without secrets.** `worktree_setup` holds dependency installs and generation only.
  The gitignored files a worktree needs go into `.worktreeinclude` in the repository root (Claude
  Code copies them into each new worktree; `init` proposes its content as an owner question), and
  on macOS and Linux `.claude/settings.local.json` is read from the main checkout by every worktree (on
  Windows it is not; the session rules always come from `--settings`). `lint` warns about
  `cp`/`rsync`/`ln` of `.env*`, secret, key or certificate directories and `.claude/`.
- **On-demand locks.** A resource `{name: ci-gate, mode: on-demand}` is not held for the whole
  package: the session sends `LOCK ci-gate`, the orchestrator takes it with `orch.py lock acquire`
  (or queues the package), and `UNLOCK` or READY gives it back; `lint` warns about a lock held longer
  than `lock_stale_hours` (default 4).
- Rules are guard rails for the usual command forms (`git -C . push` is not `git push`), not a
  security boundary: branch protection and hooks are.

## Windows

- **Rule paths.** Settings files use the form Claude Code documents for Windows: paths are normalized
  to POSIX before matching, so `C:\projects\x` becomes `//c/projects/x` in `Read`/`Edit` rules.
  Network (UNC) paths are refused: map the share to a drive letter or work from a local clone.
- **Commands.** Bash rules match the command text, so run the scripts with forward slashes, exactly
  as the rules write them: `python3 C:/.../scripts/orch.py ...`; the orchestrator's settings also
  allow `python ...` and `py -3 ...` (on Windows `python3` may be missing).
- **Shell.** `init` asks on Windows whether you start sessions from PowerShell or bash and writes
  `shell: powershell` for PowerShell; `init` and `dispatch` then print `cd "<dir>"; claude ...`.
- **Worktrees.** On Windows a worktree does not read `.claude/settings.local.json` of the main
  checkout; the plugin passes every session's rules with `--settings`, so nothing is to be copied.
- Not yet: a Windows runner in CI and PowerShell-specific forms of Bash rules (backlog).

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
- Agents: `orchestrator-scout` runs on Opus; `orchestrator-reviewer` and `orchestrator-verifier`
  run on the orchestrator's model.

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
| Verification | `scripts/verification.py`, `templates/<lang>/verify-report.md` -> `reports/verify-*.md` | standard library + git; gh for runs |
| Session settings | `scripts/session_settings.py`, `templates/settings/*.json` -> `orchestration/settings/*.json` | Claude Code settings format |
| Short commands | `commands/` | Claude Code adapter |
| Agents `orchestrator-reviewer`, `orchestrator-verifier`, `orchestrator-scout` | `agents/` | Claude Code adapter; elsewhere the same brief goes to any subagent |
| Plugin manifest | `plugin.json` | canonical; client manifests are generated |

Clients without cross-session messaging work too: the owner relays the one-line pointers, and
`resume` learns about pull requests from `gh pr list`.

Self-test: `python3 skills/pepper-orchestrator/scripts/selftest.py`.

## Codex CLI and shared local runtime

Codex uses its own skill entrypoint, native roles, launch arguments and Git worktree
preparation. Claude commands and agent methodology remain supported. Both clients
share atomic local ID reservations and recoverable state writes. See the
[Codex workflow](skills/pepper-orchestrator/references/codex.md) and
[runtime and migration guide](skills/pepper-orchestrator/references/runtime.md).
The same program switches clients sequentially; mixed writers and distributed
numbering are outside this preview.
