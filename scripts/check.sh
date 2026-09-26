#!/usr/bin/env bash
# Complete offline release checks; install scripts/requirements-build.txt first.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
export PYTHON
before="$(git diff --binary HEAD | "$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
skill="plugins/pepper-ru-web-compliance/skills/pepper-ru-web-compliance"
"$PYTHON" scripts/sync-skill-versions.py --check
"$PYTHON" scripts/sync-plugin-manifests.py --check
"$PYTHON" scripts/sync-plugin-metadata.py --check
"$PYTHON" scripts/build-chat-prompts.py --check
"$PYTHON" "$skill/scripts/gen_checklist.py" --check
"$PYTHON" "$skill/scripts/selftest.py"
"$PYTHON" "$skill/scripts/test_modernization.py"
"$PYTHON" plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer/scripts/run_evals.py --check-only
qa_dir="$(mktemp -d -t pepperskills-check.XXXXXX)"
trap 'rm -rf "$qa_dir"' EXIT
"$PYTHON" plugins/pepper-ru-web-compliance/submission/run_tests.py --out "$qa_dir"
bash scripts/test-install-links.sh
bash scripts/build-skills.sh
bash scripts/build-plugins.sh
"$PYTHON" scripts/test-packages.py
after="$(git diff --binary HEAD | "$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
if [[ "$before" != "$after" ]]; then
  echo 'checks modified tracked source files' >&2
  git diff --stat HEAD >&2
  exit 1
fi
