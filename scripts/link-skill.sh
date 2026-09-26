#!/usr/bin/env bash
# Backwards-compatible focused wrapper for shared standalone skill links.
set -euo pipefail
if [[ $# -ne 3 ]]; then
  echo "usage: $0 <skill-name> <link-path> <canonical-skill-path>" >&2
  exit 2
fi
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_dir/link-path.sh" skill "$1" "$2" "$3"
