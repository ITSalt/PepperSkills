# Mode: init

Create the program workspace and `orch.yaml`. Argument: `<program>` (lowercase slug), optionally
a title and modules.

## Steps

1. **Choose the place (P4).** The workspace lives in the orchestrator's home repository: a
   separate repository for the program (recommended), a docs or test-harness repository, or
   branch `orch/<program>` in its own worktree or clone of a module repository. Any other branch
   of a module checkout, linked worktree or clone is refused by `orch.py init` and
   `orch.py commit` (they compare the git common directory and the origin URL): a commit there may
   deploy the stand. `orch/<program>` in the main checkout of a repository that also has a
   whole-repository module gets a warning: that module's session switches branches there. If the current directory is a module checkout, stop and propose the home
   repository to the owner.
2. **Refuse to overwrite.** If `features/<program>/` exists and is not empty, switch to `resume`.
3. **Ask the owner's language explicitly** (`en` or `ru`) for owner-facing files. Do not infer it
   from the language of the request.
4. **Find the modules.** From the request and a read-only look around:
   - **Whole repositories** (0.1.0 form): one module per repository, `--module id=PATH[@BASE]`.
   - **One repository with several streams** (monorepo, or areas and domains of one product):
     one `--repo id=PATH[@BASE]` and one `--area` or `--domain id=REPO_ID:GLOB[,GLOB]` per stream
   (globs: `*`, `**`, `?`, `{a,b}`; commas inside braces are kept).
     Propose areas and domains from the directory structure and from changes made together
     (`git -C <repo> log --name-only --since=3.months`), and give the owner the proposed paths to
     confirm as a P-n item. Paths are never a guess.
   - Shared files that every stream appends to (lockfile, migrations, error-code registries,
     route registration, generated route trees, changelogs of the repository's own methodology)
     are `shared_paths`; things that cannot be shared at the same time (the stand, migrations,
     a dev stack on fixed ports, IDs in a specification graph) are `resources`.
5. **Take the repository's conventions.** `init` reads `git.branch_prefix` from the repository's
   `config.yaml` when present; otherwise it sets `<program>/` and prints a note: ask the owner and
   fix `branch_prefix` by point edit. Also ask for the worktree preparation commands (copy of the
   gitignored env with the stream's own test database and ports, dependency install) and whether
   each merge into the base deploys production (`base_deploys`).
6. **Cloud program in one repository?** Use `--in-repo <repo-id>` from the repository checkout of
   the orchestrator's cloud session: it switches to `orch/<program>`, finds a directory every push
   workflow ignores (`paths-ignore`, branch filters) and puts the workspace there, marks module
   sessions as `cloud` and turns on `push_after_milestone`. The check reads the workflows of the
   ref that will be pushed (`origin/orch/<program>` if it exists, else `origin/<base>`), never
   the working tree; hidden directories are never candidates and `docs/` comes first. It refuses
   when a workflow uses a form it does not understand, when no safe directory exists, when the
   only candidates are outside `docs/`, or when `--dir` points outside the safe directories: ask
   the owner (P-n), record the answer (D-n), then pass `--dir` or `--deploy-override D-n`. The
   override is written to `orch.yaml` (`deploy_check_override`) and the journal; `commit` refuses
   while the check fails without it. Streams are added with `--area`/`--domain <id>=<repo-id>:<glob>`.
7. **Create.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py init <program> --lang <en|ru> --title "<title>" \
     --module <id>=<path>[@<base>] ... \
     --repo <id>=<path>[@<base>] --area <id>=<repo-id>:<glob>[,<glob>] --domain <id>=<repo-id>:<glob>
   ```

   Default path: `features/<program>/`; override with `--dir`.
8. **Complete `orch.yaml` by point edits** (`safe_edit.py --stdin`, never a rewrite): per repo
   `worktree_setup`, `merge_policy` (`sequential` if merges deploy the stand without CI),
   `shared_paths`, `resources`, `checks` (read-only commands; contract in `SKILL.md`),
   `deploy_workflows`, `base_deploys`, `push_deploys: true` when a push of any branch deploys the
   stand (packages then tell sessions to push only with the stand slot); per module
   `test_db`, `ports`, `tests {scoped, full}`, `methodology {name, allowed, forbidden}` (for a
   methodology whose commands merge or deploy, list those commands as forbidden); per 0.1.0
   module `tests`, deploy commands; `push_after_milestone`; `spec_graph` stays `none`.
9. **Verify and commit.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py lint
   python3 SKILL_DIR/scripts/orch.py commit "<program>: create orchestrator workspace"
   ```

   `lint` refuses module paths that overlap outside `shared_paths` and several whole-repository
   modules on one repository.

## Result for the owner

- Outcome line: workspace path, repositories, modules and their kinds.
- Open questions as P-n items: proposed stream paths, branch prefix, worktree setup, merge
  policy, unknown repositories. Repository changes the plugin does not make (deploy only on
  command, `.worktreeinclude`, test database templates) are P-n questions with a recommendation.
- `orchestration/bootstrap-prompt.md`: the first message for a new orchestrator session.
- Next step: `plan <task>`.

Session settings files and PreToolUse guards are not generated in this version. The owner starts
module sessions with the `Start command` of each package, without `--settings`; never write or
reference a settings file by hand. The rules of concept section 12 apply as instructions.
