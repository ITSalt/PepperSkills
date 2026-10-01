# Windows installation and acceptance — 0.9.0 preview

Native Windows / PowerShell uses its own user profile and local runtime. WSL uses
a separate home directory; do not share one live SQLite store between them or
between machines. Keep repositories and runtime on a local disk. Python 3.12+,
Git, `gh` and Codex CLI are required; CI pins Codex 0.154.0. No extra Python
packages are needed for the Orchestrator runtime.

## Install or update

In PowerShell:

```powershell
python --version
git --version
gh --version
codex --version
codex plugin marketplace add ITSalt/PepperSkills
codex plugin add pepper-orchestrator@pepperskills
codex plugin list --json
```

For an existing marketplace, refresh it with
`codex plugin marketplace upgrade pepperskills`, then run the `plugin add` command
again. Restart Codex and confirm the installed/enabled plugin is version 0.9.0.
Existing customized configuration and old program IDs are retained.

The [public release](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-orchestrator-v0.9.0)
also includes `pepper-orchestrator.plugin.zip`, `pepper-orchestrator.zip` and
`SHA256SUMS`. The `.plugin.zip` contains the Codex adapter; the standalone `.zip`
contains the common/Claude skill. For a manual Codex skill installation:

```powershell
# Download the plugin ZIP and SHA256SUMS from the same release first.
Get-FileHash .\pepper-orchestrator.plugin.zip -Algorithm SHA256
Expand-Archive .\pepper-orchestrator.plugin.zip -DestinationPath .\pepper-release
New-Item -ItemType Directory -Force .\.agents\skills | Out-Null
Copy-Item .\pepper-release\pepper-orchestrator\codex\skills\pepper-orchestrator .\.agents\skills\ -Recurse
```

Compare the hash with SHA256SUMS before copying. Use one installation model for
this skill; avoid discovering the plugin and a manual copy simultaneously. Do not
overwrite an existing customized skill directory. This copy includes all shared
scripts/templates/references and needs no symlinks or Developer Mode.

## First program and owner acceptance

1. Start Codex and say: "Use Pepper Orchestrator. Initialize a program for Codex
   with local module sessions, language Russian and shell powershell. Use my
   repository and two independent module areas." Supply actual repository paths.
   The CLI equivalent is `python <skill>/scripts/orch.py init demo --client codex
   --sessions local --lang ru --shell powershell --dir <coordinator>/features/demo
   --repo app=<repository> --area frontend=app:src/frontend/**
   --area backend=app:src/backend/**` with quoted arguments for paths with spaces.
2. Let the coordinator create two WPs and run dispatch checks. Execute the exact
   commands it prints in separate PowerShell windows. Each should prepare an
   ordinary Git worktree and start Codex with your configured model and approvals.
3. Each module reads both CLAUDE.md and AGENTS.md plus applicable nested rules.
   Preserve existing text. Confirmed shared changes update both marked blocks as
   one change; disagreements go to the owner. Run `instructions check --repo .`
   before READY. Independent concrete paths should run concurrently; a common
   existing file or a test stand must still serialize.
4. Register each module's `/status` thread ID through `session register`. Send a
   scoped REVISE fixture using `session send`; inspect `session read` for actual
   consumption. If queue/App Server is unavailable, relay the printed text
   manually. A failed send is never marked delivered.
5. Complete a small real PR and review. Check any required MCP/browser tools from
   the executing role. A permission denial becomes an exact owner question;
   installation alone proves neither tool authorization nor work completion.
6. Restart the coordinator and run resume. Verify worktree/branch, PR/head and
   session history against the state files. To change clients, stop all writers
   first and run the explicit client-switch command; numbers and branches remain.

The local counter lives in `~/.pepper-orchestrator/runtime/`, outside Git and both
client configuration directories. Back it up alongside program state. Existing
programs migrate only via `id migrate` preview and explicit `--apply`; missing or
corrupt previously connected counters require restoration, never a reset.

## Automated evidence

The repository CI runs real process concurrency and crash recovery on
`windows-latest`, Ubuntu and macOS. Its Windows acceptance step builds/extracts the
ZIP, executes a generated PowerShell launch with spaces, apostrophes and Cyrillic
paths, prepares a worktree, preserves Russian project instructions, installs the
ZIP through native Codex plugin management and initializes native App Server.
It makes no model calls. Interactive account login, permissions, MCP tools and
a real module PR lifecycle are separate checks on the owner's machine.

See [validation](../../docs/validation/pepper-orchestrator-0.9.0.md),
[Codex workflow](skills/pepper-orchestrator/references/codex.md) and
[runtime contracts](skills/pepper-orchestrator/references/runtime.md).
