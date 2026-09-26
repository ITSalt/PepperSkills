#!/usr/bin/env bash
# Build portable Agent Plugins for local testing and OpenAI Skills-only review.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
PYTHON="${PYTHON:-python3}"
"$PYTHON" scripts/sync-plugin-manifests.py --check
"$PYTHON" scripts/build-chat-prompts.py --check

if [[ $# -gt 0 ]]; then
  PLUGINS=("$@")
else
  PLUGINS=(pepper-ru-web-compliance pepper-creative-mode pepper-prompt-engineer)
fi

for plugin in "${PLUGINS[@]}"; do
  src="$REPO_ROOT/plugins/$plugin"
  [[ -f "$src/plugin.json" ]] || { echo "missing: $src/plugin.json" >&2; exit 1; }
  out="$src/$plugin.plugin.zip"
  rm -f "$out"
  staging="$(mktemp -d -t pepperskills-plugin.XXXXXX)"
  mkdir -p "$staging/$plugin"
  cp -R "$src/." "$staging/$plugin/"
  find "$staging" -name '.DS_Store' -delete
  find "$staging" -type f \( -name '*.zip' -o -name '*.skill' \) -delete
  find "$staging" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$staging" -path '*/assets/registries-snapshot/*.json' -delete
  # Normalize mtimes so repeated builds produce byte-identical ZIP metadata.
  find "$staging" -exec touch -t 198001010000 {} +
  (cd "$staging" && zip -r -X "$out" "$plugin" >/dev/null)
  echo "built: $out"
  rm -rf "$staging"
done
