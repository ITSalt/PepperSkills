# Pepper Orchestrator 0.14.0: public release packaging

31 October 2026. Public preview, tag [`pepper-orchestrator-v0.14.0`](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-orchestrator-v0.14.0).
[Русский](pepper-orchestrator-0.14.0-release.ru.md).

The owner separately authorized public release after the Linux/macOS runtime acceptance. Root and plugin READMEs, the changelogs, Windows guide, private-owner setup/recovery guides and execution-plan status now describe 0.14.0. Generated manifests already identify 0.14.0; marketplace entries use the canonical plugin source. Installation is opt-in and does not change user configurations or start a service.

## Published assets

| Asset | SHA256 |
|---|---|
| `pepper-orchestrator.plugin.zip` | `c1975b462d4e28273dc63d69fd853d90bb6997691709f19ffd5b9e85be7d3b96` |
| `pepper-orchestrator.zip` | `7371ec92ecd182f58a8366ac9e3b3a9d4ceca37a1c886883c9b1aed65f9faf19` |

The release also supplies `SHA256SUMS`. Verify it before extraction. The plugin ZIP includes the dedicated Codex entrypoint plus canonical resources; the standalone ZIP contains the canonical skill used by the private-owner launcher.

## Relationship to live acceptance

The [Linux/macOS acceptance report](pepper-orchestrator-0.14.0-private-owner.md) retains the exact hashes actually executed, including the same-archive Claude Linux regression. Those bytes were built at `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d`; evidence/test-driver commit `ee8a6fc` did not change the package.

This release was rebuilt after documentation updates. It is **not the byte-identical ZIP used by those model scenarios**. [Machine comparison](evidence/orchestrator-0140-release-20261031/archive-comparison.json) verifies:

- No added or removed archive entries.
- Plugin: 225 entries, 12 changed Markdown entries; all 82 script entries are identical.
- Standalone: 101 entries, four changed Markdown references; all 41 script entries are identical.
- All other files, including SKILL.md, manifests, configurations, commands, templates and executable code, are byte-identical. Changes are version/status text, release links and setup/update explanations.

The public plugin ZIP additionally passed zero-model native project-MCP/redirected-commondir probes on **both Linux and macOS**, with native Codex 0.165.0. It retained workspace-write, on-request, reviewer=user, network=true and no additional base writable roots. Project MCP did not start; both isolated native runtimes stopped and auth copies were removed. No model scenario was rerun for the Markdown-only rebuild. [Release-specific evidence](evidence/orchestrator-0140-release-20261031/README.md).

Full local `scripts/check.sh` passed on the release tree, including packaged/generated copies, 20 owner tests, 41 autonomy tests (15 Claude), deterministic builds, source immutability and private-trace checks. [PR #42 checks](https://github.com/ITSalt/PepperSkills/pull/42/checks) cover Linux/macOS/Windows; package equality is checked across Linux/macOS and Python versions. Windows coverage remains core/native plugin/App Server smoke; private-owner Windows live mode is not claimed.

## Reproduce the comparison

Use separate checkouts of accepted commit `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d` and release tag `pepper-orchestrator-v0.14.0`. Build each using `bash scripts/build-plugins.sh pepper-orchestrator`, with the documented build dependencies installed. Run:

```sh
python3 compare-archives.py /absolute/accepted/dist/pepper-orchestrator/0.14.0 \
  /absolute/release/dist/pepper-orchestrator/0.14.0 > comparison.json
```

The [comparison script](evidence/orchestrator-0140-release-20261031/compare-archives.py) asserts the old hashes, identical entry sets, unchanged scripts/SKILL.md and Markdown-only differences. Its output must match the committed comparison JSON. Source, tag and public download hashes are independently reviewable; a GitHub release does not assert external plugin-store approval.

Follow the [private-owner guide](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/private-owner.md) for a protected installation, fixed actor manifest, zero-model preflight and explicit owner console grants. A running owner must be stopped before upgrading; recovery requires unchanged code/configuration, positive old-process exit and persisted thread identity. Automatic production approvals remain disabled.
