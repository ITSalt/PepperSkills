# Agent Plugins manifest schema

`agent-plugin-1.0.0.json` is the unmodified official schema downloaded on
2026-09-21 from https://agent-plugins.org/schemas/1.0.0/plugin.schema.json.
It is vendored so builds validate offline, without fetching schemas at load time.

The canonical metadata is each plugin's root `plugin.json`. Run
`sync-plugin-manifests.py` to generate the compatibility adapters, or `--check`
to validate the schema and reject drift without modifying files.
