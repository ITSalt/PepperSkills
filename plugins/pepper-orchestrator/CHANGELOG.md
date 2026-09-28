# Changelog

## 0.1.0 — preview, unreleased

Preview of the stage 1 core; formats and commands may change before 1.0.0.

- Stage 1 core: canonical skill with a mode router and modes `init`, `plan`, `resume`, `owner`,
  `decide`.
- Workspace CLI `orch.py` (init, new-wp, set, journal, owner, queue, decide, lint, commit) and
  `safe_edit.py` (exactly one match, backup, size check), standard library only, with a self-test.
- Workspace, work package and bug templates in English and Russian; optional `Specification` field
  in work packages and `spec_graph: none` in `orch.yaml` as the docking point for a specification
  graph.
- Concept: English translation (`references/concept.md`) and Russian original
  (`references/concept.ru.md`).
- Claude Code short commands in `commands/`.
