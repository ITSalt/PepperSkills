#!/usr/bin/env python3
"""Explicit, paid-model/live-GitHub acceptance of Claude Code autonomy; never run by offline checks.

Creates one private disposable repository, ordinary worktrees and three real interactive
Claude Code sessions in detached tmux (coordinator and two module sessions) with the
program's generated settings and one permission mode. The driver emulates owner review
and merge only in that repository and types `/compact` as the owner would; it never
dispatches. The coordinator is woken by its own Monitor watcher and dispatches with
SendMessage. No deployment, user-project changes or approval bypass.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import uuid


def run(argv, timeout=90, **kwargs):
    p = subprocess.run(list(map(str, argv)), capture_output=True, text=True, encoding='utf-8', timeout=timeout, **kwargs)
    if p.returncode:
        raise RuntimeError(f'{argv[0:4]}: {p.stderr.strip() or p.stdout.strip()}')
    return p.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument('--skill', type=Path, default=Path(__file__).resolve().parents[1] / 'plugins/pepper-orchestrator/skills/pepper-orchestrator')
    parser.add_argument('--owner', required=True, help='GitHub owner for a new private disposable repository')
    parser.add_argument('--model', default='sonnet', help='test model alias for all sessions')
    parser.add_argument('--permission-mode', default='auto')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=1500)
    args = parser.parse_args()
    sys.path.insert(0, str(args.skill.resolve() / 'scripts'))
    import autonomy
    import claude_adapter
    import orch
    root = Path(tempfile.mkdtemp(prefix='pepper-live-claude-', dir='/tmp')).resolve()
    runtime = root / 'runtime'
    result = {'root': str(root), 'platform': sys.platform, 'checks': {}, 'sessions': {}, 'model': args.model,
              'claude_version': '.'.join(map(str, claude_adapter.version()))}
    os.environ['ORCH_RUNTIME_DIR'] = str(runtime)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    repo, bare, home = root / 'app', root / 'remote.git', root / 'home'
    script = args.skill.resolve() / 'scripts/orch.py'
    program = home / 'features/test'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:6]
    remote_repo = args.owner + '/pepper-orchestrator-claude-autonomy-' + stamp
    tmux = []; created = False

    def git(directory, *flags):return run(['git', '-C', directory, *flags])
    def cli(*flags):return run([sys.executable, script, '--workspace', program, *flags], timeout=180)
    def emit(label):print(time.strftime('%H:%M:%S') + ' ' + label, flush=True)
    def rows():return claude_adapter.agents()
    def by_name(name):
        found = [r for r in rows() if r.get('name') == name]
        return found[0] if len(found) == 1 else None
    def screen(target):
        return run(['tmux', 'capture-pane', '-p', '-t', target, '-S', '-200'])
    def type_text(target, text):
        # Owner keyboard input in that window: paste then submit.
        buffer = 'pepper-' + uuid.uuid4().hex[:8]
        run(['tmux', 'set-buffer', '-b', buffer, text]); run(['tmux', 'paste-buffer', '-d', '-b', buffer, '-t', target])
        time.sleep(1); run(['tmux', 'send-keys', '-t', target, 'Enter'])
    def launch(name, cwd, settings, prompt):
        target = 'pepper-live-' + stamp + '-' + name
        command = ' '.join(['env', 'ORCH_RUNTIME_DIR=' + shlex.quote(str(runtime)), 'PYTHONDONTWRITEBYTECODE=1',
                            'claude', '--name', shlex.quote(name), '--model', shlex.quote(args.model),
                            '--permission-mode', args.permission_mode, '--settings', shlex.quote(str(settings)),
                            shlex.quote(prompt)])
        run(['tmux', 'new-session', '-d', '-s', target, '-x', '220', '-y', '60', '-c', str(cwd), command])
        tmux.append(target)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            text = screen(target)
            if 'trust this folder' in text:
                run(['tmux', 'send-keys', '-t', target, 'Down', 'Enter'])  # disposable fixture directory
            if by_name(name):
                return target
            time.sleep(1)
        raise RuntimeError('session did not start: ' + name + '\n' + screen(target)[-1500:])
    def wait_idle(name, seconds=240):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            row = by_name(name)
            if row and row.get('status') == 'idle':
                return row
            if row and row.get('status') == 'waiting':
                result['checks'].setdefault('waits', []).append({'session': name, 'for': row.get('waitingFor')})
                raise RuntimeError(f'{name} waits for {row.get("waitingFor")}; never auto-approved')
            time.sleep(2)
        raise RuntimeError('session did not become idle: ' + name)

    try:
        repo.mkdir(); home.mkdir()
        git(repo, 'init', '-b', 'main'); git(home, 'init', '-b', 'main')
        git(repo, 'config', 'user.name', 'Pepper acceptance'); git(repo, 'config', 'user.email', 'acceptance@example.invalid')
        for name in ('a', 'b'):
            (repo / name).mkdir(); (repo / name / 'README.md').write_text('Isolated acceptance fixture.\n')
        (repo / 'CLAUDE.md').write_text('This is a disposable acceptance fixture. Follow the exact package; do not merge, deploy or write to databases.\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-m', 'acceptance fixture')
        run(['git', 'init', '--bare', bare]); git(repo, 'remote', 'add', 'origin', str(bare)); git(repo, 'push', '-u', 'origin', 'main')
        run(['gh', 'repo', 'create', remote_repo, '--private', '--source', repo, '--remote', 'acceptance'])
        created = True; result['github_repository'] = remote_repo
        git(repo, 'push', 'acceptance', 'main')
        run([sys.executable, script, 'init', 'test', '--client', 'claude', '--sessions', 'local', '--lang', 'en',
             '--shell', 'bash', '--dir', program, '--repo', 'app=' + str(repo), '--area', 'a=app:a/**', '--area', 'b=app:b/**',
             '--permission-mode', args.permission_mode])
        ws = orch.Workspace(program)

        def accept_merge(wp, worktree):
            ws = orch.Workspace(program); branch = orch.wp_context(ws, wp)[2]['branch']; head = git(worktree, 'rev-parse', 'HEAD')
            git(worktree, 'push', 'origin', branch); git(worktree, 'push', 'acceptance', branch)
            url = run(['gh', 'pr', 'create', '--repo', remote_repo, '--base', 'main', '--head', branch,
                       '--title', 'Isolated acceptance ' + wp, '--body', 'Disposable fixture; owner-emulated exact-head review and merge.'])
            cli('set', wp, 'pr', url); cli('set', wp, 'status', 'REVIEW')
            changed = git(worktree, 'diff', '--name-only', 'origin/main...HEAD').splitlines()
            area = wp.split('-')[1].lower()
            if not changed or any(not n.startswith(area + '/') for n in changed):
                raise RuntimeError('fixture review found out-of-scope paths: ' + repr(changed))
            report = program / 'reports' / (wp + '-live-owner.md')
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(f'# Isolated owner review {wp}\n\nExact head: {head}\n\nPaths: {changed}\n\nFixture files inspected; no deployment.\n')
            cli('accept', wp, head, '--report', report)
            run(['gh', 'pr', 'merge', url, '--repo', remote_repo, '--squash', '--match-head-commit', head])
            git(repo, 'pull', '--ff-only', 'acceptance', 'main'); git(repo, 'push', 'origin', 'main'); git(repo, 'fetch', 'origin')
            cli('set', wp, 'status', 'DONE')
            git(repo, 'push', 'acceptance', '--delete', branch); git(repo, 'push', 'origin', '--delete', branch)
            result.setdefault('prs', []).append({'wp': wp, 'url': url, 'head': head})
            return head

        writers = {}
        for area in ('a', 'b'):
            cli('new-wp', area, 'seed'); ws = orch.Workspace(program); wp = 'WP-' + area.upper() + '-01'
            branch = orch.wp_context(ws, wp)[2]['branch']; wt = root / ('wt-' + area)
            git(repo, 'worktree', 'add', '-b', branch, wt, 'main')
            (wt / area / 'seed.txt').write_text('seed\n'); git(wt, 'add', area + '/seed.txt'); git(wt, 'commit', '-m', 'seed ' + area)
            accept_merge(wp, wt); writers[area] = wt
        for area, name in [('a', 'second'), ('a', 'third'), ('b', 'second')]:
            cli('new-wp', area, name)
        ws = orch.Workspace(program)
        for wp, value in [('WP-A-02', 'alpha-two'), ('WP-A-03', 'alpha-three'), ('WP-B-02', 'beta-two')]:
            path = ws.wp_path(ws.wp_rows()[wp]['wp']); area = wp.split('-')[1].lower()
            text = path.read_text()
            if wp == 'WP-A-03':
                old = next(x for x in text.splitlines() if x.startswith('| Depends on |'))
                text = text.replace(old, '| Depends on | WP-A-02 |')
            text += (f'\n## Exact acceptance task\n\nCreate only `{area}/{wp.lower()}.txt` containing exactly `{value}` and a newline. '
                     'Read it back and commit that one file. Do not push or create PRs; the fixture owner handles those. '
                     'Return READY with WP and full HEAD. Ignore unfilled example placeholders; this exact task is complete.\n')
            path.write_text(text); cli('set', wp, 'status', 'READY')
        ws = orch.Workspace(program)
        modules = {m.id: m for m in ws.streams()[1].values()}
        names = {area: modules[area].session for area in ('a', 'b')}
        coordinator = ws.coordinator
        module_prompt = ('You are a module executor in a disposable acceptance fixture. Reply READY_FOR_TASK and wait. '
                         'When a TASK with an assignment_id arrives from the coordinator, follow it exactly: run its '
                         f'session transition command (candidate CLI {script}, never an installed plugin), send the '
                         'STARTED line to the coordinator with SendMessage, implement only the Exact acceptance task of '
                         'the package, commit, then send READY with WP and full HEAD. Never edit coordinator documents, '
                         'merge, deploy, push or write to databases. A repeated assignment_id is the same work.')
        for area in ('a', 'b'):
            launch(names[area], writers[area], ws.root / 'orchestration/settings' / (area + '.json'), module_prompt)
        coord_prompt = (
            f'You coordinate only the disposable test program {program}. Candidate CLI: python3 {script} --workspace {program}. '
            'Never invoke an installed pepper-orchestrator plugin or skill. Reply READY_FOR_AUTONOMY and wait. '
            'When the owner tells you autonomy is enabled, start exactly one Monitor with the given command '
            '(timeout_ms 1800000). On each Monitor line with signal_id, run the consume command it contains, then act on '
            'the returned actions: for each dispatch action run `dispatch WP --json --coordinator <your session id> '
            '--generation <G>`; for a send_required result call SendMessage(to, message, notify_when_idle=true) exactly '
            'once and then run the returned `session sent` command (queued for an inbox result; not_sent only for an '
            'explicit refusal; otherwise outcome_unknown). When a module sends STARTED assignment_id=ID, or for a '
            'reconcile action, run `session started --assignment ID --coordinator <id> --generation <G> --evidence '
            '"<the message>"`. Never resend an unknown assignment. Leave review/verify/deliver/owner actions and READY '
            'messages to the fixture owner driver. Do not write module code, merge, deploy, change permissions or poll '
            'in a loop. On a Monitor expiry notice run `autonomy resume --coordinator <id> --generation <G>` and start '
            'one Monitor with the returned command. Finish each turn after the available actions.')
        launch(coordinator, program, ws.root / 'orchestration/settings/orchestrator.json', coord_prompt)
        for name in [*names.values(), coordinator]:
            wait_idle(name)
        live = {name: by_name(name) for name in [*names.values(), coordinator]}
        result['sessions'] = {n: {k: r.get(k) for k in ('sessionId', 'pid', 'cwd')} for n, r in live.items()}
        for area in ('a', 'b'):
            row = live[names[area]]
            cli('session', 'attach', '--wp', 'WP-' + area.upper() + '-01', '--thread', row['sessionId'], '--worktree', writers[area],
                '--pid', row['pid'], '--model', args.model, '--evidence',
                f'fixture-launched with --model {args.model} --permission-mode {args.permission_mode} and the module settings file')
        coord = live[coordinator]
        claim = json.loads(cli('autonomy', 'claim', '--coordinator', coord['sessionId'], '--pid', coord['pid'],
                               '--evidence', 'fixture-launched coordinator session in the program workspace'))
        generation = claim['generation']
        enabled = json.loads(cli('autonomy', 'enable', '--coordinator', coord['sessionId'], '--generation', generation))
        if enabled.get('result') != 'monitor_required':
            raise RuntimeError('enable did not return a Monitor command: ' + json.dumps(enabled))
        type_text(tmux[-1], f'Owner: autonomy is enabled. Your session id is {coord["sessionId"]}, generation {generation}. '
                            f'Start exactly one Monitor (timeout_ms 1800000) with this command: {enabled["command"]}')
        emit('live coordinator enabled: ' + remote_repo)
        expected = {'WP-A-02': 'alpha-two', 'WP-A-03': 'alpha-three', 'WP-B-02': 'beta-two'}
        completed = set(); concurrent = False; deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and len(completed) < 3:
            ws = orch.Workspace(program); table = ws.wp_rows(); live_rows = {r.get('name'): r for r in rows()}
            busy = [a for a in ('a', 'b') if (live_rows.get(names[a]) or {}).get('status') == 'busy' and
                    any(table[wp]['status'] in ('DISPATCHING', 'IN_PROGRESS') for wp in expected if wp.split('-')[1].lower() == a)]
            concurrent |= len(busy) == 2
            for name, row in live_rows.items():
                if name in [*names.values(), coordinator] and row.get('status') == 'waiting':
                    raise RuntimeError(f'{name} waits for {row.get("waitingFor")}; never auto-approved')
            for wp in sorted(expected.keys() - completed):
                area = wp.split('-')[1].lower(); wt = writers[area]
                if table[wp]['status'] != 'IN_PROGRESS' or (live_rows.get(names[area]) or {}).get('status') != 'idle':
                    continue
                path = wt / area / (wp.lower() + '.txt')
                if not path.exists() or path.read_text() != expected[wp] + '\n' or git(wt, 'status', '--porcelain'):
                    continue
                if git(wt, 'log', '-1', '--name-only', '--format=') != f'{area}/{wp.lower()}.txt':
                    continue
                accept_merge(wp, wt); completed.add(wp); emit('owner review/merge complete: ' + wp)
            time.sleep(3)
        snapshot = autonomy.registry(orch.Workspace(program))[1]
        a_key = 'claude:' + live[names['a']]['sessionId']
        result['assignments'] = [{k: x.get(k) for k in ('id', 'wp', 'session', 'state')} for x in snapshot['assignments'].values()]
        result['checks'].update(completed_packages=sorted(completed), concurrent_busy_observed=concurrent,
                                same_a_session_reused=len([x for x in snapshot['assignments'].values() if x['session'] == a_key]) == 2,
                                a03_branch=git(writers['a'], 'branch', '--show-current'), no_user_dispatch=True)
        if len(completed) != 3:
            raise RuntimeError('live cycle incomplete; inspect retained fixture')
        cli('autonomy', 'pause')
        for name in [*names.values(), coordinator]:
            wait_idle(name)
        asked = json.loads(cli('session', 'compact', '--thread', live[names['a']]['sessionId'],
                               '--coordinator', coord['sessionId'], '--generation', generation))
        type_text(tmux[0], '/compact keep the stream contracts and the handover of the previous package')
        deadline = time.monotonic() + 300; compacted = {}
        while time.monotonic() < deadline:
            time.sleep(5)
            try:
                compacted = json.loads(cli('session', 'compact', '--thread', live[names['a']]['sessionId'],
                                           '--coordinator', coord['sessionId'], '--generation', generation))
            except RuntimeError as error:
                compacted = {'result': 'outcome_unknown', 'error': str(error)}
            if compacted.get('result') == 'compacted':
                break
        result['checks']['compaction'] = {'asked': asked.get('result'), 'confirmed': compacted.get('result')}
        ok = (concurrent and result['checks']['same_a_session_reused'] and compacted.get('result') == 'compacted')
        result['verdict'] = 'PASS' if ok else 'WAIT'
    except Exception as error:
        result.update(verdict='WAIT', error=type(error).__name__ + ': ' + str(error))
    finally:
        if (program / 'orch.yaml').exists():
            try:cli('autonomy', 'pause')
            except Exception:pass
            try:result['watcher'] = autonomy.read_watch(orch.Workspace(program))
            except Exception:pass
        result['screens'] = {}
        for target in tmux:
            try:result['screens'][target] = screen(target)[-4000:]
            except Exception:pass
            try:run(['tmux', 'kill-session', '-t', target])
            except Exception:pass
        if created:
            try:run(['gh', 'repo', 'archive', remote_repo, '--yes']); result['repository_archived'] = True
            except Exception as error:result['archive_error'] = str(error)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        emit(json.dumps({k: v for k, v in result.items() if k not in ('screens', 'watcher')}, ensure_ascii=False, indent=2))
    return 0 if result.get('verdict') == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
