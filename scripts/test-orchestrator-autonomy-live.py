#!/usr/bin/env python3
"""Explicit, paid-model/live-GitHub acceptance; never invoked by offline checks.

Creates one private disposable repository, ordinary worktrees and an isolated
local App Server. The driver emulates owner review/merge only in that repository.
The real coordinator is woken by the watcher and dispatches real module threads.
No deployment, user-project changes, configuration edits or approval bypass.
"""
import argparse
import atexit
from datetime import datetime, timezone
import json
import os
import hashlib
import platform
import shutil
import zipfile
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def run(argv, **kwargs):
    p = subprocess.run(list(map(str, argv)), capture_output=True, text=True, encoding='utf-8', timeout=90, **kwargs)
    if p.returncode:
        raise RuntimeError(f'{argv[0:4]}: {p.stderr.strip() or p.stdout.strip()}')
    return p.stdout.strip()


def idle_completed(thread):
    """History can contain a failed turn before a successful recovery."""
    turns = thread.get('turns') or []
    latest = max(turns, key=lambda t: (t.get('startedAt') or 0, t['id'])) if turns else None
    return thread.get('status', {}).get('type') == 'idle' and latest is not None and latest['status'] == 'completed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', required=True)
    parser.add_argument('--skill', type=Path, default=Path(__file__).resolve().parents[1] / 'plugins/pepper-orchestrator/skills/pepper-orchestrator')
    parser.add_argument('--owner', required=True, help='GitHub owner for a new private disposable repository')
    parser.add_argument('--model', help='test model only; default is model/list isDefault, not a user-config rewrite')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--archive', type=Path, help='immutable archive whose extracted skill is under test')
    parser.add_argument('--commit', help='exact source commit recorded in the verdict')
    args = parser.parse_args()
    provenance = {}
    if args.archive:
        provenance['archive_sha256'] = hashlib.sha256(args.archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(args.archive) as archive:
            roots = [n[:-len('scripts/orch.py')] for n in archive.namelist() if n.endswith('/scripts/orch.py')]
            # Plugin ZIP also has a generated Codex copy. Select the canonical skill.
            prefix = next((r for r in roots if '/skills/pepper-orchestrator/' in r and '/codex/' not in r), roots[0])
            for name in archive.namelist():
                if name.startswith(prefix) and not name.endswith('/'):
                    target = args.skill.resolve() / name[len(prefix):]
                    if not target.is_file() or target.read_bytes() != archive.read(name):
                        raise RuntimeError('extracted skill differs from the supplied archive: ' + name)
    source_home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    test_home = Path.home() / '.local/share/pepper-orchestrator/acceptance-homes' / uuid.uuid4().hex
    test_home.mkdir(parents=True, mode=0o700)
    if (source_home / 'auth.json').is_file():
        shutil.copyfile(source_home / 'auth.json', test_home / 'auth.json')
        (test_home / 'auth.json').chmod(0o600)
    atexit.register((test_home / 'auth.json').unlink, missing_ok=True)
    (test_home / 'config.toml').write_text('model_reasoning_effort = "high"\n')
    os.environ['CODEX_HOME'] = str(test_home)
    sys.path.insert(0, str(args.skill.resolve() / 'scripts'))
    import autonomy
    import codex_adapter
    import codex_transport
    import orch
    root = Path(tempfile.mkdtemp(prefix='pepper-live-', dir='/tmp')).resolve()
    result = {'root': str(root), 'platform': sys.platform, 'kernel': platform.release(), 'python': platform.python_version(), 'source_commit': args.commit, **provenance, 'checks': {}, 'threads': []}
    os.environ['ORCH_RUNTIME_DIR'] = str(root / 'runtime')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    repo, bare, home = root / 'app', root / 'remote.git', root / 'home'
    script = args.skill.resolve() / 'scripts/orch.py'
    program = home / 'features/test'
    remote_repo = args.owner + '/pepper-orchestrator-autonomy-' + datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:6]
    server = None; api = None; created = False
    def git(directory, *flags):return run(['git', '-C', directory, *flags])
    def cli(*flags):return run([sys.executable, script, '--workspace', program, *flags])
    def emit(label):print(label, flush=True)
    try:
        repo.mkdir(); home.mkdir()
        git(repo, 'init', '-b', 'main'); git(home, 'init', '-b', 'main')
        git(repo, 'config', 'user.name', 'Pepper acceptance'); git(repo, 'config', 'user.email', 'acceptance@example.invalid')
        for name in ('a', 'b'):
            (repo / name).mkdir(); (repo / name / 'README.md').write_text('Isolated acceptance fixture.\n')
        (repo / '.worktreeinclude').write_text('')
        (repo / 'AGENTS.md').write_text('This is a disposable acceptance fixture. Follow the exact package; do not merge, deploy or write to databases.\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-m', 'acceptance fixture')
        run(['git', 'init', '--bare', bare]); git(repo, 'remote', 'add', 'origin', str(bare)); git(repo, 'push', '-u', 'origin', 'main')
        run(['gh', 'repo', 'create', remote_repo, '--private', '--source', repo, '--remote', 'acceptance'])
        created = True; result['github_repository'] = remote_repo
        git(repo, 'push', 'acceptance', 'main')
        run([sys.executable, script, 'init', 'test', '--client', 'codex', '--sessions', 'local', '--lang', 'en',
             '--shell', 'bash', '--dir', program, '--repo', 'app=' + str(repo), '--area', 'a=app:a/**', '--area', 'b=app:b/**'])
        endpoint = 'unix://' + str(root / 's.sock')
        config = program / 'orch.yaml'; text = config.read_text(); text = text.replace('codex:\n', 'codex:\n  remote: ' + endpoint + '\n', 1); config.write_text(text)
        if endpoint not in orch.Workspace(program).config['codex'].get('remote', ''):
            raise RuntimeError('fixture endpoint configuration failed')
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
            # Delete remote branches; local accepted HEAD remains in its worktree.
            git(repo, 'push', 'acceptance', '--delete', branch); git(repo, 'push', 'origin', '--delete', branch)
            result.setdefault('prs', []).append({'wp': wp, 'url': url, 'head': head})
            return head
        writers = {}
        for area in ('a', 'b'):
            cli('new-wp', area, 'seed'); ws = orch.Workspace(program); wp = 'WP-' + area.upper() + '-01'
            wt = Path(codex_adapter.prepare(ws, wp)); (wt / area / 'seed.txt').write_text('seed\n')
            git(wt, 'add', area + '/seed.txt'); git(wt, 'commit', '-m', 'seed ' + area)
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
        log = open(root / 'server.log', 'w')
        server = subprocess.Popen([*codex_transport.command(), 'app-server', '--listen', endpoint],
                                  stdin=subprocess.PIPE, stdout=log, stderr=log)
        for _ in range(100):
            if (root / 's.sock').exists():break
            time.sleep(.1)
        api = codex_transport.Server(remote=endpoint)
        model = args.model or next(x['model'] for x in api.call('model/list', {})['data'] if x.get('isDefault'))
        result.update(model=model, codex_version=codex_transport.capabilities()['version'], launched_cli=codex_transport.command(), sandbox='workspace-write', approval_policy='on-request')
        def start(cwd, instruction):
            response = api.call('thread/start', {'cwd': str(cwd), 'model': model, 'sandbox': 'workspace-write',
                                'approvalPolicy': 'on-request', 'config': {'sandbox_workspace_write': {
                                    'network_access': True,  # Selected isolated-fixture profile for RPC/GitHub.
                                    'writable_roots': [str(root / 'runtime')]}},
                                'developerInstructions': instruction}, timeout=60)
            tid = response['thread']['id']; result['threads'].append(tid)
            api.call('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': 'Reply READY_FOR_TASK and wait for the next message.'}]})
            return tid
        def thread(tid, history=False):
            response = api.call('thread/read', {'threadId': tid})['thread']
            if history:response['turns'] = codex_transport.turns(api, tid)
            return response
        def wait_idle(tid, seconds=90):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    t = thread(tid, True)
                    if t['status']['type'] == 'systemError':raise RuntimeError('test model runtime failed: ' + json.dumps(t['turns'])[-2000:])
                    if idle_completed(t):return t
                except codex_transport.TransportError:
                    pass
                time.sleep(.5)
            raise RuntimeError('test thread did not become idle: ' + tid)
        module_ids = {}
        for area, wt in writers.items():
            tid = start(wt, 'You are a module executor in a disposable fixture. Follow TASK assignment IDs exactly. '
                        'Use only the supplied candidate CLI, not an installed plugin. Read the package and run its transition command. '
                        'Echo STARTED exactly, implement only its Exact acceptance task, commit, then return READY with SHA. '
                        'Never edit coordinator documents, merge, deploy, push or write to databases. Never spawn another executor.')
            wait_idle(tid); module_ids[area] = tid
            cli('session', 'attach', '--wp', 'WP-' + area.upper() + '-01', '--thread', tid, '--worktree', wt,
                '--pid', server.pid, '--evidence', 'fixture-created thread on this exact isolated server process; verified workspace-write/on-request')
        coord = start(program,
            f'You coordinate only this disposable test program {program}. Candidate CLI: {script}. '
            'Use this absolute CLI with --workspace; never invoke an installed plugin. '
            'On AUTONOMY signals run the supplied consume command, then act on next --json. '
            'For dispatch actions invoke dispatch WP --json --coordinator YOUR_THREAD_ID --generation 1. '
            'For reconcile actions invoke session started --assignment ID --coordinator YOUR_THREAD_ID --generation 1. '
            'Treat queued as pending, never resend unknown assignments. Leave review/verify/deliver/owner actions to the fixture owner driver. '
            'Do not write module code, merge, deploy, change permissions, spawn executors or poll in a loop. '
            'Finish each turn after the available dispatch/reconcile actions; the watcher will wake you. '
            'Use the thread ID from the consume command as YOUR_THREAD_ID.')
        wait_idle(coord)
        # Startup/config migrations or another client can change the settings
        # file. Confirm only after all fixture clients have finished startup.
        for area, tid in module_ids.items():
            cli('session', 'attach', '--wp', 'WP-' + area.upper() + '-01', '--thread', tid, '--worktree', writers[area],
                '--pid', server.pid, '--evidence', 'fixture startup complete; rechecked selected workspace-write/on-request profile, model and process')
        claim = json.loads(cli('autonomy', 'claim', '--coordinator', coord, '--pid', server.pid,
                               '--evidence', 'fixture-created coordinator on this same isolated server'))
        generation = claim['generation']; result['coordinator'] = coord
        cli('autonomy', 'enable', '--coordinator', coord, '--generation', generation)
        emit('live coordinator/watcher enabled: ' + remote_repo)
        completed = set(); deadline = time.monotonic() + args.timeout
        overlapping = False
        expected = {'WP-A-02': 'alpha-two', 'WP-A-03': 'alpha-three', 'WP-B-02': 'beta-two'}
        while time.monotonic() < deadline and len(completed) < 3:
            ws = orch.Workspace(program)
            active = [wp for wp, row in ws.wp_rows().items() if wp in expected and row['status'] in ('DISPATCHING', 'IN_PROGRESS')]
            overlapping |= len(active) >= 2
            for wp in expected.keys() - completed:
                row = ws.wp_rows()[wp]; area = wp.split('-')[1].lower(); wt = writers[area]
                if row['status'] != 'IN_PROGRESS':continue
                t = thread(module_ids[area], True)
                if t['status']['type'] != 'idle':continue
                path = wt / area / (wp.lower() + '.txt')
                if not path.exists() or path.read_text() != expected[wp] + '\n' or git(wt, 'status', '--porcelain'):continue
                head = git(wt, 'rev-parse', 'HEAD')
                if not any('READY' in i.get('text', '') and head in i.get('text', '') for turn in t['turns'] for i in turn.get('items', []) if i.get('type') == 'agentMessage'):continue
                accept_merge(wp, wt); completed.add(wp); emit('owner review/merge complete: ' + wp)
            if any(e.get('method') and 'requestApproval' in e['method'] for e in api.events):
                result['approval_wait_observed'] = True  # Never auto-grant it.
            time.sleep(1)
        windows = {}
        for area, tid in module_ids.items():
            windows[area] = [
                {'started': turn.get('startedAt'), 'completed': turn.get('completedAt')}
                for turn in codex_transport.turns(api, tid)
                if any('TASK' in part.get('text', '') and 'assignment_id=' in part.get('text', '')
                       for item in turn.get('items', []) if item.get('type') == 'userMessage'
                       for part in item.get('content', []))]
        actual_overlap = any(max(a['started'], b['started']) < min(a['completed'], b['completed'])
                             for a in windows['a'] for b in windows['b'] if a['completed'] and b['completed'])
        result['turn_windows'] = windows
        result['checks'].update(completed_packages=sorted(completed), independent_overlap=actual_overlap,
                                overlapping_reservations=overlapping,
                                same_a_thread_reused=len([x for x in autonomy.registry(orch.Workspace(program))[1]['assignments'].values() if x['session'] == 'codex:' + module_ids['a']]) == 2,
                                no_user_dispatch=True)
        if len(completed) != 3:raise RuntimeError('live cycle incomplete; inspect retained fixture and watcher diagnostics')
        cli('autonomy', 'pause')
        for tid in result['threads']:wait_idle(tid)
        result['checks']['compaction'] = codex_transport.compact(module_ids['a'], remote=endpoint)
        snapshot = autonomy.registry(orch.Workspace(program))[1]
        result['assignments'] = [{k: a[k] for k in ('id', 'wp', 'session', 'state')} for a in snapshot['assignments'].values()]
        result['verdict'] = 'PASS' if result['checks']['compaction'].get('completed') and actual_overlap else 'WAIT'
    except Exception as error:
        result.update(verdict='WAIT', error=type(error).__name__ + ': ' + str(error))
        if program.exists():
            try:cli('autonomy', 'pause')
            except Exception:pass
        if api:
            try:
                result['watcher'] = autonomy.read_watch(orch.Workspace(program))
                result['thread_summaries'] = [{**{k: t.get(k) for k in ('id', 'status', 'model')},
                    'tail': json.dumps(codex_transport.turns(api, tid)[0])[-12000:]} for tid in result['threads'] for t in [api.call('thread/read', {'threadId': tid})['thread']]]
            except Exception:pass
    finally:
        # Also stop observation on interruption, not only the normal/Exception
        # paths. This command affects this disposable fixture only.
        if (program / 'orch.yaml').exists():
            try:cli('autonomy', 'pause')
            except Exception:pass
        if api:
            for tid in result['threads']:
                try:
                    t = api.call('thread/read', {'threadId': tid})['thread']
                    if t.get('status', {}).get('type') == 'active':
                        for turn in codex_transport.turns(api, tid):
                            if turn['status'] == 'inProgress':api.call('turn/interrupt', {'threadId': tid, 'turnId': turn['id']})
                    api.call('thread/archive', {'threadId': tid})
                except Exception:pass
            api.close()
        if server:
            server.stdin.close(); server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        if created:
            try:run(['gh', 'repo', 'archive', remote_repo, '--yes']); result['repository_archived'] = True
            except Exception as error:result['archive_error'] = str(error)
        (test_home / 'auth.json').unlink(missing_ok=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        emit(json.dumps({k: v for k, v in result.items() if k not in ('thread_summaries', 'watcher')}, ensure_ascii=False, indent=2))
    return 0 if result.get('verdict') == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
