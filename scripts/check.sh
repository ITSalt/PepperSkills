#!/usr/bin/env bash
# Complete offline release checks; install scripts/requirements-build.txt first.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1
export PYTHON
before="$(git diff --binary HEAD | "$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
before_status="$(git status --porcelain=v1 --untracked-files=all --ignored -- . ':(exclude)dist')"
qa_dir="$(mktemp -d -t pepperskills-check.XXXXXX)"
trap 'rm -rf "$qa_dir"' EXIT
export PEPPERSKILLS_NETWORK_AUDIT_LOG="$qa_dir/network-attempts.log"
export PYTHONPATH="$(pwd)/scripts/offline_guard${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" scripts/test-offline-guard.py
skill="plugins/pepper-ru-web-compliance/skills/pepper-ru-web-compliance"
"$PYTHON" scripts/sync-skill-versions.py --check
"$PYTHON" scripts/sync-plugin-manifests.py --check
"$PYTHON" scripts/sync-plugin-metadata.py --check
"$PYTHON" scripts/build-chat-prompts.py --check
"$PYTHON" scripts/test-chat-prompts.py
"$PYTHON" "$skill/scripts/gen_checklist.py" --check
"$PYTHON" "$skill/scripts/selftest.py"
"$PYTHON" "$skill/scripts/test_modernization.py"
"$PYTHON" plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer/scripts/run_evals.py --check-only
"$PYTHON" plugins/pepper-ru-web-compliance/submission/run_tests.py --out "$qa_dir/submission"
bash scripts/test-install-links.sh
"$PYTHON" scripts/test-install-docs.py
bash scripts/build-skills.sh
bash scripts/build-plugins.sh
"$PYTHON" scripts/test-packages.py
"$PYTHON" scripts/test-build-readonly.py
if [[ -s "$PEPPERSKILLS_NETWORK_AUDIT_LOG" ]]; then
  echo 'offline checks attempted network access:' >&2
  cat "$PEPPERSKILLS_NETWORK_AUDIT_LOG" >&2
  exit 1
fi
after="$(git diff --binary HEAD | "$PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
after_status="$(git status --porcelain=v1 --untracked-files=all --ignored -- . ':(exclude)dist')"
if [[ "$before" != "$after" ]]; then
  echo 'checks modified tracked source files' >&2
  git diff --stat HEAD >&2
  exit 1
fi
if [[ "$before_status" != "$after_status" ]]; then
  echo 'checks created or removed unexpected repository files' >&2
  git status --short >&2
  exit 1
fi
