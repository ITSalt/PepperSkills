#!/usr/bin/env bash
# Build deterministic standalone skill ZIPs from canonical plugin directories.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" "$REPO_ROOT/scripts/sync-plugin-versions.py" --check
"$PYTHON" "$REPO_ROOT/scripts/sync-plugin-manifests.py" --check
"$PYTHON" "$REPO_ROOT/scripts/sync-plugin-metadata.py" --check
"$PYTHON" "$REPO_ROOT/scripts/build-chat-prompts.py" --check
exec "$PYTHON" "$REPO_ROOT/scripts/package.py" --kind skill --repo-root "$REPO_ROOT" "$@"
