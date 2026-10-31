# Public 0.14.0 packaging evidence

These records supplement the [same-archive runtime acceptance](../orchestrator-private-owner-0140-20261031/README.md); they do not replace its archive hashes.

- `archive-comparison.json`: deterministic comparison of the accepted and public archive pairs. All changed entries are explicitly listed; no file was added/removed and scripts/SKILL.md/non-Markdown bytes are identical.
- `compare-archives.py`: executable comparison recipe. Build the accepted commit and release tag separately; pass their `dist/pepper-orchestrator/0.14.0` directories. Output must match the committed JSON.
- `linux-project-config.json`, `macos-project-config.json`: public plugin ZIP zero-model startup probes. Export includes only archive/driver/raw-result hashes, native profiles, empty MCP inventories, marker results and cleanup. Home, fixture and thread identifiers are omitted; runtime actor path is `<ACTOR_ROOT>`. Each raw JSON SHA256 is computed before this export.
- Probe source is the tagged `scripts/probe-orchestrator-project-config.py`; `cleanup-zero-model-threads.py` records the subsequent model-free history cleanup. Native reports `no rollout found` for both empty threads on both platforms; no model history was created. Native runtimes stopped and temporary auth copies were removed.
- `local-check.json`: command, success and SHA256 of the complete local release check log. CI logs remain in PR #42 checks and tagged/main GitHub Actions runs.

`SHA256SUMS` covers every file in this evidence folder except itself. Raw logs stay outside the repository. Public release ZIPs have their own `SHA256SUMS` asset and must not be confused with this evidence manifest.
