#!/usr/bin/env python3
"""Opt-in live check of an extracted plugin against an already running local Codex.

Example: python3 scripts/test-orchestrator-local-continuation.py \
  --skill /absolute/extracted/pepper-orchestrator/skills/pepper-orchestrator \
  --server-pid PID

Creates temporary Git fixtures and native threads. Makes two ordinary model calls.
Exercises worker creation, exact-turn completion, dependency advancement and YOLO.
The driver accepts fixture results. Interactive /clear and watcher-driven coordinator
behavior require a separate live acceptance run.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill', required=True, type=Path)
    parser.add_argument('--server-pid', required=True, type=int)
    args = parser.parse_args()
    sys.path.insert(0, str(args.skill.resolve() / 'scripts'))
    import autonomy
    import codex_transport
    import orch
    import research
    import runtime_selftest

    fixture = runtime_selftest.RuntimeTests()
    fixture.setUp()
    try:
        repo, root = fixture.fixture('codex')
        config = root / 'orch.yaml'
        text = config.read_text().replace('sandbox_mode: workspace-write', 'sandbox_mode: danger-full-access')
        text = text.replace('approval_policy: on-request', 'approval_policy: never')
        config.write_text(text + '\ncontinuation: auto\n')
        for slug in ('first', 'second'):
            fixture.cli('--workspace', root, 'new-wp', 'a', slug)
        workspace = orch.Workspace(root)
        packages = [('WP-A-01', 1), ('WP-A-02', 2)]
        for package, number in packages:
            path = workspace.wp_path(workspace.wp_rows()[package]['wp'])
            dependency = 'WP-A-01' if number == 2 else 'none'
            path.write_text(
                f'# Research fixture {number}\n\n| Field | Value |\n|---|---|\n'
                f'| Execution | research |\n| Depends on | {dependency} |\n\n'
                f'Read a/readme.md and return FIXTURE-PASS-{number} plus its contents. '
                'Do not modify files.\n')
            fixture.cli('--workspace', root, 'set', package, 'status', 'READY')
        with codex_transport.server(shared=True) as server:
            coordinator = server.call('thread/start', {
                'cwd': str(repo), 'sandbox': 'danger-full-access', 'approvalPolicy': 'never'})['thread']['id']
        with contextlib.redirect_stdout(io.StringIO()):
            autonomy.cmd_autonomy(argparse.Namespace(
                workspace=str(root), action='claim', coordinator=coordinator, pid=args.server_pid,
                evidence='fixture coordinator created on this observed live daemon'))
        workspace = orch.Workspace(root)
        _, registry = autonomy.registry(workspace)
        generation = registry['coordinator']['generation']
        registry['research'] = {wp: research.update(workspace, None, 'contract', {
            'question': 'read fixture', 'decision': 'accept fixture', 'artifact': f'reports/{wp}.md',
            'criteria': {'source': {'evidence_standard': 'exact file content', 'unknown_allowed': False}}})
            for wp, number in packages}
        registry['autonomy']['enabled'] = True
        autonomy.persist(workspace, registry)
        for package, number in packages:
            workspace = orch.Workspace(root)
            actions = autonomy.next_actions(workspace)['actions']
            assert any(action.get('wp') == package and action['kind'] == 'continue_research' for action in actions)
            launch = autonomy.launch_local(workspace, package, coordinator, generation)
            deadline = time.monotonic() + 180
            turn = {}
            while time.monotonic() < deadline:
                try:
                    with codex_transport.server(shared=True) as server:
                        turns = codex_transport.turns(server, launch['thread_id'])
                except codex_transport.TransportError:
                    # A newly created rollout can briefly have no stored metadata.
                    time.sleep(1)
                    continue
                turn = next((item for item in turns if item['id'] == launch['turn_id']), {})
                if turn.get('status') in ('completed', 'failed', 'interrupted'):
                    break
                time.sleep(1)
            assert turn.get('status') == 'completed', str(turn)[:300]
            assert f'FIXTURE-PASS-{number}' in json.dumps(turn), 'expected fixture result absent'
            actions = autonomy.next_actions(orch.Workspace(root))['actions']
            assert any(action.get('wp') == package and action['kind'] == 'review_research' for action in actions)
            report = root / 'reports' / f'{package}.md'
            messages = [item.get('text', '') for item in turn.get('items', []) if item.get('type') == 'agentMessage']
            assert any(f'FIXTURE-PASS-{number}' in text for text in messages), 'assistant result absent'
            report.parent.mkdir(exist_ok=True)
            report.write_text('\n'.join(messages))
            _, registry = autonomy.registry(orch.Workspace(root))
            record = registry['research'][package]
            for task in record['tasks']:
                record = research.update(workspace, record, 'result', {'id': launch['request_id'] + ':result:' + task['id'],
                    'task': task['id'], 'evidence': str(report.relative_to(root))})
            record = research.update(workspace, record, 'verdict', {'id': launch['request_id'] + ':accepted',
                'verdict': 'accepted', 'criteria': {'source': {'status': 'satisfied', 'reason': 'exact fixture response verified',
                'evidence': str(report.relative_to(root))}}})
            registry['research'][package] = record
            autonomy.persist(workspace, registry)
            for status in ('ACCEPTED', 'DONE'):
                fixture.cli('--workspace', root, 'set', package, 'status', status,
                            '--evidence', f'Native result verified FIXTURE-PASS-{number}')
            assert fixture.git(repo, 'status', '--short') == '', 'source checkout changed'
            print(f'PASS {package}: native completion, dependent launch, source unchanged', flush=True)
        print('PASS installed local continuation worker lifecycle')
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
