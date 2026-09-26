#!/usr/bin/env bash
# Build deterministic portable Agent Plugin ZIPs.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" "$REPO_ROOT/scripts/sync-plugin-versions.py" --check
"$PYTHON" "$REPO_ROOT/scripts/sync-plugin-manifests.py" --check
"$PYTHON" "$REPO_ROOT/scripts/sync-plugin-metadata.py" --check
"$PYTHON" "$REPO_ROOT/scripts/build-chat-prompts.py" --check
exec "$PYTHON" "$REPO_ROOT/scripts/package.py" --kind plugin --repo-root "$REPO_ROOT" "$@"
