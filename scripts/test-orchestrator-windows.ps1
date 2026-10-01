$ErrorActionPreference = 'Stop'
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Command failed: $LASTEXITCODE" } }

# Exercise the distributed Codex entrypoint, ordinary Git worktrees, Unicode
# and actual PowerShell argument parsing. No credentials or model calls.
python scripts/package.py --kind plugin pepper-orchestrator
Check-Exit
$stage = Join-Path $env:RUNNER_TEMP 'pepper archive smoke'
New-Item -ItemType Directory -Force $stage | Out-Null
Expand-Archive dist/pepper-orchestrator/0.9.0/pepper-orchestrator.plugin.zip -DestinationPath $stage -Force
$skill = Join-Path $stage 'pepper-orchestrator/codex/skills/pepper-orchestrator'
python scripts/test-orchestrator-native.py --skill $skill --powershell
Check-Exit
python scripts/test-orchestrator-native.py --skill $skill --transport
Check-Exit
