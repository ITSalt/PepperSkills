#!/usr/bin/env python3
"""Installed archive / native transport smoke without authentication or model calls."""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          encoding='utf-8', **kwargs).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skill', type=Path, required=True)
    parser.add_argument('--powershell', action='store_true')
    parser.add_argument('--transport', action='store_true')
    parser.add_argument('--expected-plugin')
    args = parser.parse_args()
    skill = args.skill.resolve()
    sys.path.insert(0, str(skill / 'scripts'))
    codex_adapter = importlib.import_module('codex_adapter')
    if args.transport:
        transport = importlib.import_module('codex_transport')
        caps = transport.capabilities()
        assert caps['available'] and caps['app_server'], caps
        # Initialize/dispatch JSON-RPC on native Windows without starting a turn.
        with transport.server() as api:
            result = api.call('thread/list', {'limit': 1})
            assert isinstance(result['data'], list), result
            if args.expected_plugin:
                loaded = api.call('skills/list', {'cwds': [str(Path.cwd())], 'forceReload': True})
                matches = [s for item in loaded['data'] for s in item['skills']
                           if s.get('pluginId') == args.expected_plugin]
                assert len(matches) == 1, loaded
                entrypoint = Path(matches[0]['path'])
                assert 'Pepper Orchestrator for Codex CLI' in entrypoint.read_text(encoding='utf-8')
                assert (entrypoint.parent / 'scripts/orch.py').is_file(), entrypoint
        print(json.dumps({'native_transport': caps, 'app_server': 'PASS'}))
    if args.powershell:
        with tempfile.TemporaryDirectory(prefix="pepper smoke проба ' spaces ") as temp:
            root = Path(temp)
            os.environ['ORCH_RUNTIME_DIR'] = str(root / 'runtime')
            repo = root / 'project'; repo.mkdir()
            run(['git', '-C', str(repo), 'init', '-b', 'main'])
            run(['git', '-C', str(repo), 'config', 'user.name', 'Fixture'])
            run(['git', '-C', str(repo), 'config', 'user.email', 'fixture@example.invalid'])
            (repo / 'CLAUDE.md').write_text('Custom Claude instructions\n', encoding='utf-8')
            run(['git', '-C', str(repo), 'add', '.'])
            run(['git', '-C', str(repo), 'commit', '-m', 'fixture'])
            ws = root / 'coordinator'
            script = str(skill / 'scripts/orch.py')
            run([sys.executable, script, 'init', 'windows', '--client', 'codex', '--lang', 'ru',
                 '--sessions', 'local', '--shell', 'powershell', '--repo', 'app=' + str(repo),
                 '--area', 'app=app:**', '--dir', str(ws)])
            run([sys.executable, script, '--workspace', str(ws), 'new-wp', 'app', 'smoke'])
            orch = importlib.import_module('orch')
            streams = importlib.import_module('streams')
            workspace = orch.Workspace(ws)
            module = workspace.streams()[1]['app']
            meta = streams.wp_meta(workspace.wp_path(workspace.wp_rows()['WP-APP-01']['wp']), module)
            command = codex_adapter.launch(workspace, module, 'WP-APP-01', meta)
            # A function intercepts only the final model launch. The preparation
            # command actually executes from the ZIP via the current interpreter.
            powershell = root / 'launch.ps1'
            captured = root / 'argv.json'
            powershell.write_text(
                "$ErrorActionPreference = 'Stop'\nfunction codex {\n"
                "  ConvertTo-Json -InputObject @($args) -Compress | Set-Content -Encoding utf8 "
                + codex_adapter.shell_join([str(captured)], 'powershell')[2:] + "\n}\n"
                + command + "\nif ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n", encoding='utf-8')
            run(['pwsh', '-NoProfile', '-File', str(powershell)])
            argv = json.loads(captured.read_text(encoding='utf-8-sig'))
            assert argv[0] == '--cd', argv
            assert Path(argv[1]).is_dir(), argv
            assert 'Report SESSION WP-APP-01' in argv[-1], argv
            assert '--ask-for-approval' in argv and '--sandbox' in argv, argv
            # Both user documents are updated while preserving private text.
            instructions = importlib.import_module('project_instructions')
            shared = 'Общие правила: python -m unittest\n'
            status = instructions.status(repo)['files']
            instructions.sync(repo, shared, status[0]['sha256'], status[1]['sha256'], True)
            assert instructions.status(repo)['synchronized']
            assert (repo / 'CLAUDE.md').read_text(encoding='utf-8').startswith('Custom Claude')
            print('PASS: extracted Codex skill, PowerShell launch, worktree, Russian text and paired instructions')


if __name__ == '__main__':
    main()
