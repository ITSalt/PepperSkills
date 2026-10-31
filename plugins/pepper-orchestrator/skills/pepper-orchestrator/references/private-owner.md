# Explicit private owner for Codex (0.14.0 candidate)

This opt-in Linux/macOS mode connects the portable scheduler to its own Codex
App Server through private STDIO. It creates only the fixed coordinator/module
threads declared by the owner at startup. It cannot attach transparently to a
desktop session or discover another server's live state. Existing CLI/manual and
Claude workflows remain available. Native Codex **0.165.0** is the initially
supported version; another version fails explicitly rather than using a bridge.

Install the verified standalone skill or canonical plugin skill in an owner-held
directory outside Git worktrees, actor roots and shared temporary directories.
Use Python's isolated imports (`-I -S -B`); never import owner code from a module's
checkout. Preserve the downloaded archive and its independently obtained SHA256.
The launcher compares the archive hash and every installed canonical skill file,
rejects extra Python imports, symlinks and hardlinks. The native executable,
Python/Git executables, configuration, program documents, runtime and role state
must also remain outside actor writable roots. No listener, public RPC/MCP
endpoint, file-command inbox, global config edit or system service is installed.

Prepare the separate program workspace and existing linked module worktrees as
the owner. Each module must have a clean last completed WP with accepted exact
head, confirmed merge and removed work branch before reuse; normal scheduler
checks still apply. Declare disjoint branch namespaces (for example `orch/a/`
and `orch/b/`) in the upcoming WP branch headers and manifest. Main worktrees,
overlapping roots/namespaces, remote sessions and required MCP are rejected.
The coordinator has a separate working directory; protected program documents
are read through tools and written by the portable core.

Create an owner-held JSON manifest (all paths absolute):

```json
{
  "version": 1,
  "model": "gpt-6.1-sol",
  "workspace": "/absolute/program-home/features/example",
  "coordinator": {"cwd": "/absolute/coordinator"},
  "modules": [
    {"module": "a", "wp": "WP-A-01", "cwd": "/absolute/module-a",
     "branch_prefix": "orch/a"},
    {"module": "b", "wp": "WP-B-01", "cwd": "/absolute/module-b",
     "branch_prefix": "orch/b"}
  ]
}
```

`wp` identifies the module's last completed package at fresh bootstrap. Optional
`instructions` in a role entry add owner-supplied project instructions. The owner
explicitly selects the model; the launcher uses high reasoning effort and checks
that native responses did not substitute a model. Use an empty, separate owner
state directory on first launch. Preflight makes no model call:

```sh
python3 -I -S -B /absolute/installed-skill/scripts/owner_main.py \
  --manifest /absolute/owner-manifest.json --directory /absolute/owner-data \
  --native /absolute/native/codex --archive /absolute/candidate.zip \
  --sha256 ARCHIVE_SHA256 --preflight
```

Remove `--preflight` to launch explicitly. The launcher copies only local
`auth.json` into a private isolated Codex home with mode 0600 and removes that
copy on exit; `--auth-home` can select its local source. Never transfer auth to
another machine or include it in evidence. The owner's ordinary Codex config
and sessions are not modified. Native bootstrap may add project trust records
inside the isolated home; the exact resulting config hash is pinned before work
and required on recovery. Subsequent config drift blocks operation. One process
holds the program identity lock.
Only one private server and one fixed executor per module are active.

The effective profile is workspace-write/on-request, reviewer=user, network=true,
one actor runtime root, no additional base writable roots, MCP or remote ingress.
Apps, remote plugins, browser/computer use, hooks, automatic daemon and additional
agents are disabled in this explicit mode. Normal network connectivity remains;
this is not a promise that arbitrary host UNIX services are unreachable. The
owner's control channel has no socket to reach. Actor-owned `.codex/config.toml`, hooks and exec-policy rules are disabled by
immutable native session flags: `project_root_markers=[]` and untrusted trust
entries for every fixed actor cwd. This outranks thread/start's persisted trust;
checking only effective config before that call is insufficient. Owner settings
come from the protected isolated home, not mutable project layers. Configuration
checks inspect layer metadata before start/resume/compaction and reject an active
project layer or missing isolation flags. This does not broaden filesystem or
approval permissions.

The passive watcher calls the existing deterministic scheduler without model
polling. It queues a signal; the real coordinator invokes `consume`, `dispatch`
and `reconcile` through the typed `pepper_orchestrator` tool. Modules can invoke
only `context`, `prepare` and `prepared`. Caller role, program, thread, active
turn/tool item and connection epoch come from protected registration and the
native envelope, never arguments or message text. There is no generic RPC,
shell/path, approval, merge/deploy or session-creation tool.

On a module's `prepare`, the owner validates the current assignment and returns
an exact finite sandbox command and six Git metadata write roots: its private
gitdir, shared objects, its own branch/ref-log namespace, origin refs/ref-logs.
Native `request_permissions` remains **WAIT**. The console displays the actual
request; inspect assignment, cwd, turn, roots and intended command before typing
`grant ID`. Only the matching six-root filesystem request for the active
preparation can be granted, for **one turn**. Network/read additions, unrelated
requests, session scope and repeated grants are rejected. `deny ID` refuses a
pending native request. There are no automatic production approvals or blanket
Git rules. The fixture acceptance controller is separate test-only code and
reports each human-selected bounded decision and its zero native UI clicks.

Git fetch, branch creation and configured setup execute in the module's native
sandbox command, never on the host. `prepared` accepts only the exact completed
native command/turn, nonce, assignment, generation, config, helper hash and
current Git facts, and then records STARTED. Missing/expired/unknown setup is
retained for owner reconciliation; never blindly retry. The host observer pins
Git metadata paths and reads with a finite whitelist, disabled hooks, filters,
fsmonitor, external diffs and implicit fetch. Granted Git metadata is mutable;
JSON written by a module is not host authority.

Console commands are `status`, `pause`, `resume`, `grant ID`, `deny ID`, `stop`.
Pause prevents fresh assignments even after a queued signal. Resume uses the
same fixed coordinator and registry. Stop pauses and closes only this server,
preserving native histories. No persistent service or detached watcher remains.
To restart, use the same command with `--resume`: the launcher requires positive
exit of the previous native identity, identical code/native/config, no unknown
command lifetime, and persisted tools in the exact same thread IDs. It reattaches
those threads, recovers the generation and rescans current state. It never
replaces an executor or silently retries unknown deliveries. A lease timeout or
inaccessible process is insufficient. Code/config upgrades require explicit
owner migration, not `--resume` over changed bytes.

Turn expiry applies to new commands. It does not revoke permissions already
held by a surviving background terminal. Use finite setup, wait for native
command completion and inspect retained processes before recovery/reuse; an
unresolved native command blocks observation as idle, preparation and compaction.
Native compaction must produce a new completed contextCompaction item on this
same loaded server; an RPC acknowledgement or old completion is insufficient.
Merge, deployment, production and review decisions stay with the owner.

The acceptance target is **PASS (Git-approved, on-request)**: autonomous scheduling
with ordinary permission pauses. It is not the earlier unchanged-profile Git
preparation PASS or a zero-approval unattended claim. See repository validation
reports for measured host/version/archive scope. This candidate is unreleased;
Windows retains offline/native core smoke only, without this live mode.
