# Single orchestrator (hub-and-spoke): concept and working rules

> Version 1.8 · 2026-09-30 (1.1: streams in one repository, rules P1-P5, section 19; 1.2: cloud sessions, section 20; 1.3: program completion, section 21; 1.4: session kind and implementer model, section 7; 1.5: session settings, permission mode and message delivery, sections 4 and 12; 1.6: verification by facts, section 9; 1.7: plugin defects reported, section 16; 1.8: trusted delivery, sections 1, 2 and 12) · derived from the "Corporate clients (B2B)" program (6 repositories,
> 12 days, about 40 work packages, rolled out to production). The document is methodological and
> stack-independent. Program specifics appear only in examples. Russian original:
> [`concept.ru.md`](concept.ru.md).

## 0. How to use this file

This file ships with the `pepper-orchestrator` plugin; the skill reads it as its rule book.

Start with the phrase "use the single-orchestrator concept" or with the plugin commands:

```text
/pepper-orchestrator:init <program>     program workspace and orch.yaml
/pepper-orchestrator:plan <task>        facts -> plan -> work packages -> owner questions
/pepper-orchestrator:resume             resume: files + reconciliation with reality + next step
```

To resume in a new orchestrator session without the plugin:

```text
You are the orchestrator of program <name>. Read <workspace>/status.md and section 11 of the
single-orchestrator concept, reconcile the state with reality and continue from the first open step.
```

## 1. Essence

1. One agent session, the **orchestrator**, is the owner's single point of entry. It plans, writes
   work packages, tells the owner which sessions to start, talks to them, verifies their results and
   keeps the state in files.
2. Code is written by **module sessions**, each started in the directory of its own repository. Only
   this way does it pick up that repository's `CLAUDE.md` (or equivalent), rules, MCP servers and
   skills.
3. The orchestrator **does nothing irreversible itself and never asks sessions to**: merge, deploy,
   production, database writes, permission changes are done only by the owner, from a ready
   one-line command. By an explicit owner decision (D-n) the orchestrator may carry out delivery by
   the rules - merge of accepted packages and the stand, through gates by facts, a ledger and a stop
   at the first failure; asking another session to merge or deploy stays forbidden.
4. All state lives in files (`status.md`, `decisions.md`, work packages, reports), not in session
   memory. Any orchestrator session can be lost and restored from the files plus reconciliation with
   reality.
5. Verification is the orchestrator's job: every session result is checked against code, tests and
   live on TEST. A "done" message is a claim, not a fact.

## 2. Roles and authority

| Role | Who | Does | Never does |
|------|-----|------|------------|
| **Owner** | human | product and risk decisions; starts module sessions; merges PRs; deploys TEST (where manual) and every PROD; changes permissions, keys, infrastructure; works in store consoles and external systems | does not keep state in their head: everything is visible in `status.md` |
| **Orchestrator** (hub) | agent session in the program's "home" repository | plan, work packages, dispatch, PR review, live checks on TEST, release sheets, owner queue, journal | does not write module code; does not merge, deploy or write to databases (except trusted delivery the owner handed over by a decision: merge and stand through `orch.py deliver`, gates, ledger, hold); does not edit other repositories |
| **Module session** (spoke) | agent session started by the owner in the module directory with its own settings file | implements the package: branch, code, tests, PR, report in the PR body, READY message; deploys TEST only if that is a standard part of its methodology and the owner confirms in its window | does not merge, does not deploy PROD, does not write to the orchestrator repository |
| **Orchestrator subagents** | one-off agents inside the orchestrator session | read-only research across many files, PR review, test runs in a disposable clone, live E2E, documentation checks | do not edit repositories; their report is also a claim the orchestrator verifies |

Delegation rule: **anything that needs reading many files or a long run goes to a subagent**; the
orchestrator keeps conclusions in context, not file dumps.

## 3. When to apply

| Apply | Not needed |
|-------|------------|
| work touches 2 or more repositories or 2 or more roles (database + frontend + mobile) | one change in one repository |
| lasts longer than one session, has PROD and regression risk | prototype without PROD |
| owner product decisions are needed along the way | everything is decided upfront |
| results need verification independent of the implementer | the implementer's self-check is enough |

These are the effectiveness boundaries of the pattern: below them the coordination overhead
outweighs the benefit.

## 4. Program workspace

A directory in the orchestrator's "home" repository (test harness, docs repository or a dedicated
program repository):

```
features/<program>/
  README.md             - what the program is and where things are (one page)
  PLAN.md               - goals, scope, waves, gates, risks (written once, edited rarely)
  status.md             - THE ONLY source of state: waves, WP table, owner queue, event journal
  decisions.md          - decisions D1..., assumptions A..., questions Q... (append-only)
  spec/                 - behavior (if the program is new functionality)
  contract/             - inter-module contract with versions and CCRs (if modules share API/DB)
  work-packages/        - WP-<MOD>-NN-<slug>.md + _TEMPLATE.md
  reports/              - review, live-check and gate reports
  release/              - release sheets, runbook, rollback
  gates/                - gate checklists G0...Gn (if formal milestones are needed)
  orchestration/
    protocol.md         - session and message protocol (this document adapted to the program)
    settings/<name>.json - generated settings of each session (--settings): one per local module,
                           orchestrator.json; <name>.local.json holds the owner's own additions
    hooks/              - PreToolUse hooks (for example "SELECT only" for database MCP)
  bugs/                 - defects found along the way (one file per defect)
```

**Only the orchestrator** writes to this space. Module sessions get a deny rule for editing this
directory in their settings. Settings files are generated from `orch.yaml` (`orch.py settings`),
never written by hand, and passed with the permission mode the owner chose for the program
(`permission_mode`) in every local start command.

**Where the workspace lives (P4).** Not in a module repository. Recommended: a separate "home"
repository of the program; acceptable: branch `orch/<program>` in its own worktree or clone.
Never another branch of a module checkout, worktree or clone: a commit there may deploy the stand.
Not the main checkout either when a whole-repository module's session works in it.

**Modules and streams.** A module is either a whole repository or a logical block inside one: an
**area** (a section of the product) or a **domain**, with its own paths. Modules of one repository
are **streams**; `orch.yaml` describes the repository once (`repos`: base, branch prefix, worktree
root and setup, merge policy, shared paths, resources, checks) and each stream refers to it.

## 5. Work lifecycle

```
owner request
  -> fact finding (code, database SELECT, logs) - subagents
  -> plan and decisions (owner questions P-n with a recommendation)
  -> WP: DRAFT -> READY
  -> DISPATCH: to the owner - session start command + start prompt; to a live session - TASK message
  -> IN_PROGRESS (the session works; the orchestrator does not poll it in a loop)
  -> READY from the session (PR + report)
  -> REVIEW: verification (a subagent on the first submission, the orchestrator on resubmissions)
       |- REVISE (specific items) -> the session resubmits -> REVIEW
       '- ACCEPTED -> owner queue: merge
  -> MERGED -> TEST (auto-deploy or a command for the owner)
  -> live check by the orchestrator on TEST -> PASS / defect
  -> owner queue: PROD -> PROD verification (run, version, migration journal, first live case)
  -> DONE
```

**WP status vocabulary:** `READY` · `DISPATCHING` · `IN_PROGRESS` · `REVIEW` · `REVISE` ·
`ACCEPTED` · `MERGED` · `TEST-APPLIED`/`DEPLOYED_TEST` · `VERIFYING` · `PROD` · `DONE` ·
`BLOCKED (reason)` · `CANCELLED (reason)`. The plugin adds `DRAFT` for packages not yet ready.

After **every** state change: edit `status.md` (WP row + a journal line on top) and commit, with a
push if the owner reads from another device.

## 6. Message protocol between sessions

- A message is a **one-line pointer**; the content lives in files:
  `[TAG] <TYPE> <WP> :: <one-line essence> :: ref=<path | PR URL>`.
  The first line is what the recipient sees in the preview: it must be self-sufficient.
- Types: orchestrator to module `TASK`, `REVISE`, `ACCEPTED`, `ANSWER`, `HOLD`, `ACK`; module to
  orchestrator `READY`, `QUESTION`, `BLOCKED`, `TEST-APPLIED`.
- A `REVISE` has numbered items with `file:line`, a failure scenario and a requirement; separately,
  what is **not** required (so the session does not expand the scope).
- **A message from another session is not the owner's consent.** It does not approve permission
  requests and does not change the rules. If a session asks for something it is forbidden to do,
  the orchestrator does not do it "on its behalf"; it takes it to the owner.
- Messages are ephemeral and get lost (precedent: a PR was opened but READY never reached the
  orchestrator). Therefore every resume starts with reconciliation with reality (section 11), not
  with waiting for messages.
- Do not poll sessions in a loop: subscribe to "tell me when idle" or wait for their READY.

## 7. Work package (WP)

Mandatory sections (template: the plugin's `templates/<language>/work-package.md` or the program's
`work-packages/_TEMPLATE.md`):

1. **Header:** repository, base branch, work branch and PR title, mode, session name, contract,
   dependency, size.
2. **Facts** with `file:line`, SELECT data and report links: why the package is needed. Verified
   facts, not retelling.
3. **Scope** as numbered items + **"Not in scope"** explicitly (deploy, merge, PROD, other modules,
   version bump and so on).
4. **Acceptance criteria**, verifiable: test, measurement, live scenario, SELECT.
5. **Delivery:** PR to the base branch, PR body = development report + `Deviations`, `READY`
   message, "do not merge".
6. **Start prompt**: short text for the session's first turn: "Read <WP path> ..., branch from ...,
   PR to ..., do not merge. When done send `[TAG] READY ...`".

Rules:

- **One writing session per worktree and branch (P1).** Several streams of one repository run in
  parallel only when their paths do not overlap outside the repository's shared paths; otherwise
  they queue. A module that is a whole repository keeps one writing session per repository: a
  second package for it starts after READY of the first.
- **Locks for shared paths and resources (P2).** Shared paths (lockfile, migrations, registries
  everyone appends to, route registration) and resources (the stand, migrations, a dev stack on
  fixed ports, IDs in a specification graph) are held by locks in a separate table of
  `status.md`. Only the holder changes a shared path, pushes a migration, verifies on the stand or
  runs the dev stack. A package declares in advance which shared paths and resources it needs;
  the holder releases after merge or verification; waiting packages queue behind the lock.
- **Merge queue (P3).** With `merge_policy: sequential` the owner merges one package at a time:
  merge, then the green stand deploy and health check, then the rebase of the next package, then
  its merge. If every merge into the base deploys production, merge in batches through a release
  sheet.
- **Session kind and model.** The owner chooses once, at the start, whether module sessions run
  locally (recommended) or in the cloud (with a named cloud environment); an orchestrator running
  in the cloud works only with cloud sessions. Every package carries a recommended implementer
  model and effort: the latest Sonnet for a clear package inside one module, Opus with high effort
  for contracts, data migrations, money and permissions, concurrency, bug hunts without a
  hypothesis and large refactorings, a stronger model after a second failed REVISE round. The
  model goes into the start command as a flag; `/model <name>` with an argument in a local session
  would make it the owner's default for every new session.
- **Stream start.** The session of a stream starts in its own worktree (`claude -w <wp-slug>` in
  Claude Code) and prepares it itself: branch from the current base, the repository's worktree
  setup (a copy of the gitignored env with its own test database and ports, dependency install).
- Product forks are not decided inside a package: a question to the owner (`P-n`) with options and a
  recommendation; the decision (`D-n`) is recorded in `decisions.md` and the package references it.
- If the owner changes a decision along the way, the package is edited before dispatch; after
  dispatch, the session gets a "re-read the WP" message.
- A package found untenable (hypothesis refuted by measurement) is cancelled with the reason
  recorded. That is a normal outcome.

## 8. Result verification (review)

**First submission: a reviewer subagent** with a brief:

- inputs: WP path, PR, base, the session's report; "read only via `git show`/`gh`, do not enter the
  module's working directory";
- **specific questions about this package's risks**, not "check everything" (for example: "a race in
  the shared store: does it affect other tables?", "do font file names match the package convention,
  otherwise a crash on every start?");
- check the session's statements as claims, not facts;
- tests in a **disposable clone** in the task's tmp; mutations (remove the key line -> the test must
  fail);
- output format: verdict, table "item -> where in code -> status", findings by decreasing severity
  with a failure scenario, CI, diff size; delete the clone.

**Resubmissions: the orchestrator itself** reads the revision diff (`compare <rev1>...<rev2>`) and
CI: usually only a few lines.

**Verdict:**

- `ACCEPTED`: everything in scope, findings only low/info (they go to the backlog or the report).
- `REVISE`: a regression against the base, a violated criterion, a PROD risk. **While the PR is not
  merged and the session is alive, one REVISE round beats a follow-up:** a follow-up costs the owner
  another merge and deploy.
- The review report (the orchestrator's decision + the reviewer's verbatim report) goes to
  `reports/<wp>-review-<date>.md`.

## 9. Verification after merge (verify)

- **TEST:** the orchestrator (through a subagent) runs a live scenario: create an order, walk the
  route, count posts in the channel, compare a checkpoint in the database: whatever checks the
  package criterion "in reality". The report goes to `reports/`.
- **PROD:** only the owner deploys. The orchestrator verifies: the deploy run and its steps, the
  version of the served bundle, the migration journal, the function/view definition in PROD
  (`pg_get_functiondef`, `pg_get_viewdef`): **the live object, not the migration file**, and the
  first live case (or asks the owner for a log line).
- Live-check tools degrade (precedent: a Docker Playwright MCP failed with EOF). Keep a fallback in
  the scenario (local Chromium over CDP) and do not treat tool degradation as a product defect.
- **By facts, in a fixed order** (`orch.py verify <WP> --env test|prod`): the deploy run for the
  expected SHA (the merge commit) on the environment's branch finished with success; the served
  version is that SHA; the repository's read-only verify commands pass (health, migration journal,
  smoke); then the live scenario of the package's acceptance criteria. The report goes to
  `reports/verify-<WP>-<env>-<date>.md`. PASS gives `VERIFIED_TEST` (test) or `PROD` (prod); FAIL
  keeps the status, writes a defect to `bugs/`, and asks the owner only when the next step needs
  their rights. This works the same whoever merged and deployed. Only `VERIFIED_TEST` packages go
  into a release sheet.

## 10. Owner queue and talking to the owner

`status.md` has a "Waiting for owner" table:

- **R-n (action):** what to do, **the exact command on one line** (the owner copies it whole), the
  expected output ("Pending: 1 -> Applied: 1, journal 107"), what happens next. Closed only after
  the orchestrator verified the fact.
- **P-n (question):** options with consequences and a **recommendation**; the answer becomes `D-n`
  in `decisions.md`.
- Closed rows are struck through with the date and the verified fact; obsolete ones are dropped with
  a reason.

Answering the owner:

- start with the outcome; if something is unverified, say it first;
- commands in code blocks, one per action, in execution order;
- no internal labels the owner has not seen; keep it short;
- on "done", always verify the fact (`gh pr view`, `gh run view`, SELECT, bundle version) and only
  then "closed".

## 11. Reconciliation with reality (on every start and after events)

| What | How |
|------|-----|
| live sessions | `ListAgents` / `claude agents --json` (where the client supports it) |
| PRs and CI | `gh pr list/view/checks`, `gh run list/view` for each repository |
| branches of main checkouts | `git -C <repo> rev-parse --abbrev-ref HEAD`, lag behind `origin/<base>` |
| database | migration journal and object definitions through MCP, **SELECT only** |
| deployed versions | the version in the served bundle (`curl` + search for the version string), not the badge in the browser (cache) |
| logs | latest service events (MCP logs, a log line from the owner) |

Discrepancies go to the `status.md` journal first, then action.

## 12. Safety and boundaries

- Every session starts with **its own settings file** (`--settings`) and the program's permission
  mode (`--permission-mode`, `auto` recommended): allow the module's standard commands as narrow
  rules (reading, its tests and checks verbatim, commits; pushes are left to the classifier, since a
  `*` tail also matches refspecs to the base); deny
  merge, force pushes and pushes to base branches, `gh workflow run`, releases, PROD MCP and PROD
  deploy commands, ssh and database clients where guards exist, editing the orchestrator
  workspace, forbidden methodology commands; ask for the owner's checkpoints (TEST deploy, and
  optionally pushes and PRs).
- **Auto mode.** Deny rules, explicit ask rules and narrow allow rules are decided before the
  classifier; broad allow rules (`Bash(*)`, interpreters with `*`) are suspended in auto mode. The
  `autoMode` block (trusted environment) is read from user and managed settings and from
  `--settings`, never from project settings, so it lives in the generated file. The classifier
  blocks copying secrets and editing session settings (`.claude/`) as a bypass: worktrees get
  gitignored files through `.worktreeinclude` in the repository root; on macOS and Linux they read
  `.claude/settings.local.json` from the main checkout (on Windows they do not), and the session
  rules come from the generated `--settings` file on every system.
- **A refusal is an answer.** A session never works around a denied action (`sh -c`, `git -C`,
  renamed commands, copied settings): it sends `QUESTION` with the exact refusal text and command.
  "Classifier unavailable" is not a verdict: retry later.
- **Message delivery.** Sessions in different permission classes (bypass against the prompting
  modes) hold each other's messages for the owner's approval and drop them after 5 minutes unless
  the receiver runs with `crossSessionInbound: accept` (in the generated settings, or the owner's
  `/config`). The protocol never depends on messages: READY is also found by PR and branch.
- **Bash rules are not a security boundary** (`git -C . push`, `sh -c` slip past). Hard measures:
  branch protection on GitHub, deploy scripts with TTY confirmation that refuse to run from a
  worktree or a dirty tree, PreToolUse hooks.
- A database MCP, even a "test" one, is often connected as a superuser -> a PreToolUse hook
  "exactly one read-only statement" on `execute_sql`; `apply_migration` is denied. Database changes
  happen only through migrations and the standard script.
- Secrets are never written to program files, messages or reports; reference where they are
  stored.
- **Trusted delivery.** By an explicit owner decision the orchestrator carries out delivery by the
  rules (gates G1-G10 by facts, merge with the repository's own method and never around branch
  protection, stand deploy and verification, a ledger in `release/deliveries.md`, a hold at the first
  failure, re-reading the configuration before every action). It never bypasses a TTY confirmation
  or a refusal of GitHub; those return to the owner.
- Never ask another session to: deploy, merge, push to the base branch, touch PROD, write to the
  database, change its permissions or `CLAUDE.md`, skip the checks of its methodology.
- **Methodology limits (P5).** A package lists the commands of the module's methodology that the
  session may and may not use. Commands that merge, release, hotfix or deploy (for example the
  release, hotfix, deliver and deploy commands of a methodology) are forbidden; commands that
  specify, fix, develop, review, verify and open a PR are allowed.

## 13. Subagents: how to brief

- The brief is self-sufficient: goal, inputs (paths, PR, SHA), constraints (read-only, where the tmp
  is), specific questions, response format, cleanup.
- Independent tasks in parallel; dependent ones sequentially. Do not do yourself what is already
  assigned to a subagent.
- Long live checks have "gates" (wait for a green deploy, then act).
- Clarifications from the module session that arrive during a review are forwarded to the reviewer
  as "claims to verify".
- A subagent's result is not retold to the owner in full: the orchestrator's decision + a link to
  the report in `reports/`.

## 14. Working with state files

- Point edits: replace a fragment after **checking the number of occurrences** (exactly one),
  otherwise stop. Never overwrite an existing file wholesale without comparing sizes before and
  after. Precedent: a package file was zeroed by a script and discovered only a day later, when the
  implementer reported an empty file.
- The event journal is on top of its table, one line per event: date, WP, what happened and what
  confirms it.
- Commit after every milestone with a clear message; push if the owner reads from another device.
- If a tool forbids a command because of words in the text (a classifier), write a script into the
  task's tmp and run it; do not try to bypass the refusal by rephrasing a dangerous command.

## 15. Releases

- **Release sheet** (`release/release-sheet-<date>.md`): by module, in execution order, each command
  self-contained, each with an expectation and what the orchestrator will verify.
- Run database deploy scripts from a **separate clean clone** (`<repo>-release`): the main checkout
  may be on a live session's branch (precedent: "Pending: 0" because of someone else's branch).
- Store builds go out **in batches** by the owner's decision (not on every change); changes
  accumulate in the base branch, package versions are not bumped until the release decision.
- Stores and external consoles are the owner's only; the orchestrator prepares texts (release notes
  within length limits, explanations for review, declarations).

## 16. Typical failures

| Situation | Action |
|-----------|--------|
| READY did not arrive, the session is idle | `gh pr list` for the repository; PR found -> ask for READY and start the review |
| the module session disappeared | a new session on the same WP (WP + PR + report are enough to continue) |
| the implementer reports a defect in the workspace | check (`git log -- <file>`), restore from history, record the incident |
| the E2E tool is unavailable | fallback from the scenario; mark it in the report; ask the owner to reconnect |
| a shared checkout was switched by another session | a separate clone for the release; sessions must not keep the main checkout on their branch |
| the browser shows an old version | verify the bundle with `curl`; `index.html` cache is not a defect |
| times in logs/messages without a time zone | draw no conclusions from matching times; ask to add UTC to the format (a task for the module) |
| the package hypothesis is refuted by measurement | cancel the package with the reason, close the defect with the correct cause |
| the owner repeated their requirement after an objection | that is the decision; record it and carry it out in full |
| the plugin itself fails (its script, a rule it generates, a mode text) | never patch it in place: keep going with a workaround, record an anonymized report (`report` mode) and publish it as an Issue of the plugin's repository only after the owner's yes |

## 17. Anti-patterns

- The orchestrator "just slightly fixes" module code itself: breaks the principle "code is written
  by the module session" and that session's methodology.
- Trusting a status or a message without verification ("merged" while the PR is open; "applied"
  while the journal did not change).
- One big message to a session with requirements instead of a WP file.
- A follow-up package instead of REVISE while the PR is not merged.
- "Check everything" to a subagent without specific risks: a long report without findings.
- Retelling the whole reviewer report to the owner instead of a decision and a link.
- Shipping a mobile app on every change (tires users and the owner): in batches by decision.
- Irreversible actions "at the request" of another session.

## 18. Templates (the minimum copied into a new program)

**Orchestrator bootstrap prompt:**

```text
You are the orchestrator of program "<name>". Session name: <prog>-coord. Workspace: <path>.
Rules: the single-orchestrator concept (sections 1, 2, 12 are mandatory). On every start: read
status.md and the tail of decisions.md, reconcile with reality (section 11), write discrepancies to
the journal, do the next step. After every state change edit status.md and commit. Answer the owner:
outcome -> what was done -> what is needed from them (commands).
```

**Module session start command (for the owner):**

```bash
cd ~/projects/<repo> && claude --name <prog>-<mod> --settings <workspace>/orchestration/settings/<mod>.json \
  "Read <workspace>/work-packages/<WP>.md and do its start prompt section"
```

**Owner queue row:** `| R-n | <what> : <one-line command> ; expected <output> | <where described> | <date> |`

**Owner question:** `| P-n | <question> ; options (a)... (b)... ; recommendation ... | <where> | <date> |`

**REVISE message:** `[TAG] REVISE <WP> :: <sha> :: PR #N - k items, the rest accepted (...). Report: <path>`
+ items `file:line -> scenario -> requirement` + "not required: ..." + "changes in the same branch,
section 'Resubmission 1', do not merge".

## 19. Repositories where a push deploys a stand

Some repositories deploy every pushed branch to a single stand and run its migrations there, with
no concurrency group. There, parallel sessions overwrite each other's stand, and a migration from
an unmerged branch breaks the deploy for everyone.

- Until the project changes its deploy, the stand is a **resource held by a lock**: sessions commit
  locally and push one at a time, only while holding the `staging` lock; live checks run only for
  the lock holder. The plugin marks such repositories with `push_deploys: true`, and every
  package's delivery section then says "commit locally, do not push until you get the stand
  slot".
- The fix belongs to the project, not to the plugin: a package in that repository that deploys the
  stand only on command (manual dispatch or a dedicated branch prefix) and adds a concurrency group
  per environment. The orchestrator raises it as an owner question with a recommendation before
  parallel streams start.
- The same applies to other project changes the plugin does not make (`.worktreeinclude`, mock
  modes of paid external services, the order of a methodology's changelog): the orchestrator finds
  them, asks the owner, and they are done as ordinary packages in the project.

## 20. Cloud sessions

When the orchestrator and the module sessions are cloud sessions over one repository, each session
is its own clone, sees only its own repository, and messages from it do not reach other sessions.
The concept holds because it rests on files and reconciliation, not on messages:

- **The workspace lives in the repository, on its own branch.** Branch `orch/<program>` is
  long-lived and never merged into the base; the workspace directory is one that every push
  workflow ignores (for example under a `paths-ignore` path), so state commits start no deploy.
  The orchestrator cloud session starts on that branch. Nothing is ever committed to the base.
- **Packages are read from that branch.** A module session gets a prompt that tells it to fetch
  `orch/<program>` and read its package from there (or the package text inline), to branch from
  the base and to deliver a pull request with the package id in its body.
- **Readiness is found, not announced.** No READY message arrives from a cloud session: the
  orchestrator finds pushed branches and pull requests (through the GitHub tools of its session
  when there is no `gh`) on every resume.
- **Merge tools stay unused.** Cloud sessions can have tools that merge pull requests; the
  orchestrator and module sessions never call them. Merge remains the owner's action.
- **Configuration is delivered from outside the session.** A cloud session does not install
  plugins from project settings and must not edit `.claude/`; the skill reaches it through the
  environment's setup script (or as a project skill committed by the owner).

## 21. Program completion

One program has one goal. `PLAN.md` states the goal and its completion condition as verifiable
facts. When the condition holds, the program is closed; the next goal is a new program, not more
packages in a finished one.

- **Close by facts:** every package is `DONE` or `CANCELLED (reason)`; no open pull request of a
  package branch; no lock and no queued merge left; every owner item is resolved or explicitly
  carried to the program's backlog; the owner gets the list of module sessions to close.
- **Closeout report:** goal and condition, result, packages with their pull requests, decisions,
  carried backlog, risks after closing, optionally lessons. The program state becomes "closed".
- **Archive:** a separate home repository moves the workspace to an archive directory. An in-repo
  workspace stays on its branch until the owner tags it and deletes the branch; the orchestrator
  only prints those commands. Keeping the workspace as history in the base branch is an owner
  decision, made through a pull request.
- **After closing:** a closed program is not planned or dispatched; resuming it shows only the
  result. It is reopened only when its own goal turns out not to be reached, with the reason
  recorded.
