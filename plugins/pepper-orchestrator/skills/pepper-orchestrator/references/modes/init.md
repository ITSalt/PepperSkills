# Mode: init

Create the program workspace and `orch.yaml`. Argument: `<program>` (lowercase slug), optionally
a title and modules.

## Steps

1. **Check the place.** The current directory is the orchestrator's home repository (test
   harness, docs repository or a dedicated program repository), not a module repository. If it is
   a module repository, stop and tell the owner where the workspace should live.
2. **Refuse to overwrite.** If `features/<program>/` exists and is not empty, switch to `resume`.
3. **Collect modules.** From the owner's request and a read-only look around (sibling
   repositories, `gh repo list` if available), build the list `id=repo[@base]`. Unknown items
   become an owner question later, not a guess. One module per repository.
4. **Create.** Run:

   ```bash
   python3 SKILL_DIR/scripts/orch.py init <program> --lang <en|ru> --title "<title>" \
     --module <id>=<repo>[@<base>] ...
   ```

   `--lang` is the owner's language for owner-facing documents. Default path:
   `features/<program>/`; override with `--dir`.
5. **Complete `orch.yaml` by point edits** (never rewrite it): per module `tests`, `deploy_test`,
   `deploy_prod`, `release_clone`, `web_urls`; `environments`; `guards`; `push_after_milestone`
   (true if the owner reads from another device); `spec_graph` stays `none` unless the owner asks
   for a specification graph as a source of facts. Use `python3 SKILL_DIR/scripts/safe_edit.py`.
6. **Verify and commit.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py lint
   python3 SKILL_DIR/scripts/orch.py commit "<program>: create orchestrator workspace"
   ```

## Result for the owner

- Outcome line: workspace path and module list.
- Open questions as P-n items (unknown repositories, base branches, deploy commands).
- Next step: `plan <task>`.

Session settings files (`orchestration/settings/<module>.json`) and PreToolUse guards are not
generated in this version; the owner starts module sessions without `--settings` until then, and
the rules of concept section 12 apply as instructions.
