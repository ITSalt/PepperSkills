$ErrorActionPreference = 'Stop'
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Command failed: $LASTEXITCODE" } }

# Exercise the distributed Codex entrypoint, ordinary Git worktrees, Unicode
# and actual PowerShell argument parsing. No credentials or model calls.
python scripts/package.py --kind plugin pepper-orchestrator
Check-Exit
$stage = Join-Path $env:RUNNER_TEMP 'pepper archive smoke'
New-Item -ItemType Directory -Force $stage | Out-Null
Expand-Archive dist/pepper-orchestrator/0.11.0/pepper-orchestrator.plugin.zip -DestinationPath $stage -Force
$skill = Join-Path $stage 'pepper-orchestrator/codex/skills/pepper-orchestrator'
python scripts/test-orchestrator-native.py --skill $skill --powershell
Check-Exit
# Native plugin installation in this disposable runner, using the ZIP as the
# plugin source rather than depending on a Python source checkout.
$catalogue = Join-Path $stage '.agents/plugins'
New-Item -ItemType Directory -Force $catalogue | Out-Null
@'
{"name":"pepper-smoke","plugins":[{"name":"pepper-orchestrator","source":{"source":"local","path":"./pepper-orchestrator"},"policy":{"installation":"AVAILABLE","authentication":"ON_INSTALL"}}]}
'@ | Set-Content -Encoding utf8 (Join-Path $catalogue 'marketplace.json')
codex plugin marketplace add $stage --json
Check-Exit
codex plugin add pepper-orchestrator@pepper-smoke --json
Check-Exit
$plugins = codex plugin list --json | ConvertFrom-Json
Check-Exit
$installed = @($plugins.installed | Where-Object { $_.pluginId -eq 'pepper-orchestrator@pepper-smoke' })
if ($installed.Count -ne 1 -or $installed[0].version -ne '0.11.0' -or -not $installed[0].enabled) {
    throw 'Distributed Codex plugin was not installed and enabled'
}
python scripts/test-orchestrator-native.py --skill $skill --transport --expected-plugin pepper-orchestrator@pepper-smoke
Check-Exit
