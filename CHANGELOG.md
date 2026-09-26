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
