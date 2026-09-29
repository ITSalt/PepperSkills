# Mode: review

Verify a module session's delivery (concept section 8): automatic findings, a reviewer on the first
submission, the orchestrator itself on resubmissions, a verdict, the report and the message to the
session. Arguments: the WP id, optionally the PR URL and `--since <previous reviewed sha>`.

Never merge, approve or comment on the PR, in any client. In cloud sessions the GitHub tools can
merge (for example `mcp__github__merge_pull_request`): never call them.

## Steps

1. **Find the delivery.** PR head SHA, base, CI state and the session's report (PR body):
   `gh pr view <n> --json headRefOid,baseRefName,body,statusCheckRollup` and `gh pr checks`, or
   the session's GitHub tools when there is no `gh`. `orch.py ready` shows pushed branches.
2. **Start the round.**

   ```bash
   python3 SKILL_DIR/scripts/orch.py review-start <WP> --pr <url> [--ref <sha>] [--since <old sha> --round <n>]
   ```

   It sets `REVIEW`, writes the report skeleton `reports/<wp>-review-<date>[-rN].md`, and prints
   the automatic findings (files outside the allowed paths, shared paths undeclared or without the
   lock, a stale merge-base and which of the branch's files the base changed since, the
   repository's `checks`), the diff size, the disposable clone command, and for a resubmission
   the revision diff command (`git range-diff` after a rebase, `git diff old new` otherwise).
3. **First submission: the reviewer.** Build the brief from
   [../review-brief.md](../review-brief.md): package path, PR, SHA, base, clone command,
   automatic findings, the session's claims, and **specific risk questions** from the checklists
   that match the diff. Send it to the `orchestrator-reviewer` agent where the client has plugin
   agents; otherwise to a general subagent with the same brief, or do the review yourself in the
   same order. Forward clarifications from the session as claims to verify.
4. **Resubmission: yourself.** Read the revision diff and CI; they are usually a few lines. Check
   each REVISE item against the new code and that nothing else changed unexpectedly. Delegate
   only when the revision is large.
5. **Decide.**
   - `REVISE` when there is a regression against the base, a violated acceptance criterion, a
     production risk, or an automatic finding that matters (outside paths, shared path without
     the lock, stale merge-base with overlapping files). While the PR is open and the session is
     alive, one REVISE round beats a follow-up package.
   - `ACCEPTED` when everything in scope holds and remaining findings are low or informational;
     they go to "Accepted as is / backlog".
6. **Write the report** by point edits of the skeleton: decision line, REVISE items
   (`file:line` -> failure scenario -> requirement), "Not required", accepted and backlog, and the
   reviewer's report verbatim below the line. Do not retell the reviewer's report to the owner.
7. **Record and hand over.**
   - REVISE: `orch.py set <WP> status REVISE --evidence reports/<file>`; message line
     `[TAG] REVISE <WP> :: <sha> :: PR #N - k items, the rest accepted. Report: <path>` with the
     items, "not required", and "changes in the same branch, section 'Resubmission n', do not
     merge". Send it where messaging reaches the session; for a cloud session or without
     messaging, give the owner the text to paste into that session.
   - ACCEPTED: `orch.py set <WP> status ACCEPTED --evidence reports/<file>`,
     `orch.py merge add <WP> --pr <url>`, and an owner item with the merge command
     (`orch.py owner add R "Merge: gh pr merge <n> --repo <owner/repo> --merge ; expected: merged"`).
     The owner merges; `owner` mode verifies and runs `merge done`.
   - `orch.py lint` and `orch.py commit "<program>: review <WP> <verdict>"`.

## Result for the owner

The decision in one line, the REVISE items or the merge command, and the report link. Nothing
unverified is presented as verified: if tests could not run, say so first.
