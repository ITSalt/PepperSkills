# Changelog

## Unreleased — repository layout transition

| Previous path | Canonical path |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `<name>/chat-prompt.md` | `plugins/<name>/adapters/chat/chat-prompt.md` |
| Root `RELEASE-NOTES-v1.4.*.md` | `docs/releases/` |
| `docs/modernization-*.ru.md` | `docs/history/` |

The root skill paths remain as transition symlinks during Phase A. Existing user
installations are not rewritten. See the [installation guide](docs/installation-and-updates.md)
and [Russian transition map](docs/installation-and-updates.ru.md).

### Chat compatibility corrections after review

Chat bodies match checkpoint `e2c7d4f` (including whitespace), except the rebuild
command and six deliberately repaired local-reference labels. The full prompts
already had dangling Markdown links with Russian appendix labels at that checkpoint;
these now name the included appendix directly (English in Creative Mode, Russian in
Compliance). The compact Creative Mode names the full-skill reference without adding
its 5 KB appendix. Appendix selection is explicit in templates. Golden hashes and
exact allowed replacements are recorded in `scripts/fixtures/chat-goldens.json`.
