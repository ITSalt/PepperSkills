# Private owner 0.14.0 native evidence

31 October 2026. Runtime source `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d`.
Linux/macOS used exactly the same plugin ZIP:
`57722062c318161abc7e477b9ae06e584289849743e83bd618b76ac8d4a4253a`.
Standalone skill: `7bc64b887591f175097d3aff2f149d7940403ce71c64fc0dfc64079333d89cab`.
No public release. [Report](../../pepper-orchestrator-0.14.0-private-owner.md).

- `linux/`, `macos/`: final result, fixed-role manifest, shipped-console smoke,
  two native epochs, console/archive cleanup events, zero-model project canary
  and export provenance. Native event ordinals and request/response envelopes
  retain role binding, profiles, actual commandExecution and permission decisions.
- `startup-control.json`: the earlier zero-model positive control. Effective
  config skipped the untrusted layer, while native thread/start launched the owned
  MCP canary. The fixed session flags stop it; linked-worktree/commondir cases
  are in each host's final project-config evidence. No third-party service was used.
- `claude-linux.json`, `claude-cleanup.json`: same-archive live compatibility,
  existing native auto permission mode, parallel work/reuse/PostCompact, archived
  fixture and known session PIDs absent. Terminal screens are omitted.
- `executed-*.py`: exact generic test-driver/probe sources used for final runs.
  The Codex driver's SHA matches each protected native result. Probes require
  explicit --run and are excluded from ordinary CI.
- `exporter.py`: redaction/selection source. `export-provenance.json` records
  original local SHA256 and exported SHA256 separately; redacted bytes cannot
  be used as the original file hash.
- `ci.json`: packaged-runtime checks and artifact identity. `SHA256SUMS` covers
  the exported files, not itself.

This is PASS (Git-approved, on-request), with three bounded fixture-controller
turn grants per host, zero native manual UI clicks, and an explicit native
file-change decline. Production approval logic remains manual. Actual preparation
and expiry/workdir probes are tied to exact native argv/cwd/turn, not module JSON
or path mentions. No unsandboxed retry/session grant or blanket Git rule was used.

A real pending consume was held across pause/stop. Positive old-runtime exit and
protected ownership history permitted retiring that wake-up only; assignment IDs
were preserved, a fresh scan dispatched the third WP, and no executor was replaced.

Home, fixture, repository, host and boot identifiers are aliases. Reasoning,
account and usage telemetry are excluded. Raw logs remain local on the hosts;
export hashes support reproducibility and tamper detection, not remote attestation
of arbitrary editable JSON. No claim covers arbitrary extra tools, future native
versions or all host UNIX services. Finite command expiry does not revoke already
launched background terminals' permissions.
