#!/usr/bin/env bash
# Local release checks. Dependencies: jsonschema, pyyaml; browser checks separate.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
export PYTHON
skill="plugins/pepper-ru-web-compliance/skills/pepper-ru-web-compliance"
"$PYTHON" scripts/sync-plugin-manifests.py --check
"$PYTHON" scripts/build-chat-adapters.py --check
"$PYTHON" scripts/build-chat-prompt.py --check
"$PYTHON" "$skill/scripts/gen_checklist.py" --check
"$PYTHON" "$skill/scripts/selftest.py"
"$PYTHON" "$skill/scripts/test_modernization.py"
"$PYTHON" plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer/scripts/run_evals.py --check-only
qa_dir="$(mktemp -d -t pepperskills-check.XXXXXX)"
trap 'rm -rf "$qa_dir"' EXIT
"$PYTHON" plugins/pepper-ru-web-compliance/submission/run_tests.py --out "$qa_dir"
bash scripts/build-skills.sh
bash scripts/build-plugins.sh
"$PYTHON" scripts/test-packages.py
