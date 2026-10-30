#!/usr/bin/env python3
"""Explicit paid disposable private-STDIO integration trial. Never runs in CI.

The fixture controller handles owner review/merge only. Real coordinator tools
call the portable scheduler; real modules perform all Git preparation in sandbox.
No production approval automation. A separate flag authorizes only this fixture's
exact native turn grants, following the owner's selected Git-approved test mode.
"""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


def run(argv, timeout=90):
    p = subprocess.run(list(map(str, argv)), capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    if p.returncode:
        raise RuntimeError(str(argv[:4]) + ': ' + (p.stderr.strip() or p.stdout.strip()))
    return p.stdout.strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True, action='store_true')
    p.add_argument('--skill', type=Path, required=True)
    p.add_argument('--native', type=Path, required=True)
    p.add_argument('--github-owner', required=True)
    p.add_argument('--model', default='gpt-6.1-sol')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--authorize-fixture-git-turns', action='store_true')
    p.add_argument('--timeout', type=int, default=900)
    a = p.parse_args()
    if not a.authorize_fixture_git_turns:
        p.error('selected fixture grant mode requires explicit --authorize-fixture-git-turns')
    skill = a.skill.resolve(); sys.path.insert(0, str(skill / 'scripts'))
    import autonomy
    import codex_adapter
    import codex_transport
    import orch
    import private_owner
    import state_io
    grant_spec = importlib.util.spec_from_file_location('fixture_grants', Path(__file__).with_name('probe-orchestrator-git-grants.py'))
    grants = importlib.util.module_from_spec(grant_spec); grant_spec.loader.exec_module(grants)
    parent = Path.home() / '.local/share/pepper-orchestrator/private-autonomy-trials'; parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='trial-', dir=parent)).resolve()
    repo, home, bare = (root / n for n in ('app', 'program-home', 'upstream.git'))
    program = home / 'features/test'; codexhome = root / 'codex-home'
    sourcehome = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    os.environ.update(ORCH_RUNTIME_DIR=str(root / 'runtime'), CODEX_HOME=str(codexhome),
        PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    result = {'fixture': str(root), 'model': a.model, 'native': str(a.native.resolve()),
        'native_sha256': hashlib.sha256(a.native.read_bytes()).hexdigest(), 'checks': {},
        'grants': [], 'threads': [], 'verdict': 'NOT_RUN', 'native_manual_UI_clicks': 0,
        'authorization': 'Owner selected sandbox + explicit Git permissions and requested disposable Linux/macOS integration acceptance.'}
    api = None; owner = None; remote = None; created = False
    def git(directory, *args):
        # This owner-only fixture path ignores global Git config. Use existing gh
        # authentication for GitHub explicitly, without changing credential config
        # or exposing a token. Modules fetch only the local bare origin.
        return run(['git', '-c', 'credential.helper=',
            '-c', 'credential.https://github.com.helper=!gh auth git-credential', '-C', directory, *args])
    def cli(*args): return run([sys.executable, skill / 'scripts/orch.py', '--workspace', program, *args])
    def branch(wp, area, suffix):
        ws = orch.Workspace(program); path = ws.wp_path(ws.wp_rows()[wp]['wp'])
        lines = path.read_text().splitlines()
        field = next(l for l in lines if l.startswith('| Work branch |'))
        path.write_text('\n'.join(l.replace(field, '| Work branch | `gate/' + area + '/' + suffix + '` |') for l in lines) + '\n')
    def review_merge(wp, worktree):
        ws = orch.Workspace(program); b = orch.wp_context(ws, wp)[2]['branch']; head = git(worktree, 'rev-parse', 'HEAD')
        changed = git(worktree, 'diff', '--name-only', 'origin/main...HEAD').splitlines()
        area = wp.split('-')[1].lower()
        if not changed or any(not name.startswith(area + '/') for name in changed):
            raise RuntimeError('owner review found out-of-scope changes: ' + repr(changed))
        git(worktree, 'push', 'origin', b); git(worktree, 'push', 'acceptance', b)
        url = run(['gh', 'pr', 'create', '--repo', remote, '--base', 'main', '--head', b,
            '--title', 'Disposable acceptance ' + wp, '--body', 'Isolated fixture. Exact-head owner review; no deployment.'])
        cli('set', wp, 'pr', url); cli('set', wp, 'status', 'REVIEW')
        report = program / 'reports' / (wp + '-owner.md'); report.parent.mkdir(exist_ok=True)
        report.write_text('# Fixture owner review\n\nExact head: ' + head + '\n\nPaths: ' + repr(changed) + '\n')
        cli('accept', wp, head, '--report', report)
        run(['gh', 'pr', 'merge', url, '--repo', remote, '--squash', '--match-head-commit', head])
        merged = json.loads(run(['gh', 'pr', 'view', url, '--repo', remote, '--json', 'state,headRefOid,mergeCommit']))
        if merged['state'] != 'MERGED' or merged['headRefOid'] != head or not merged['mergeCommit']['oid']:
            raise RuntimeError('exact-head squash merge unconfirmed')
        git(repo, 'pull', '--ff-only', 'acceptance', 'main'); git(repo, 'push', 'origin', 'main'); git(repo, 'fetch', 'origin')
        cli('set', wp, 'status', 'DONE')
        git(repo, 'push', 'acceptance', '--delete', b); git(repo, 'push', 'origin', '--delete', b)
        result.setdefault('reviews', []).append({'wp': wp, 'head': head, 'pr': url, 'merge': merged})
        print('owner review/merge', wp, flush=True)
    handled_approvals = set()
    def approve_exact_fixture_requests():
        for ident, request in list(api.approvals.items()):
            if ident in handled_approvals: continue
            params = request.get('params', {}); tid, turn = params.get('threadId'), params.get('turnId')
            plans = [plan for plan in list(owner.preparations.values()) if plan['thread'] == tid and plan['turn'] == turn and plan['epoch'] == api.epoch]
            if len(plans) != 1:
                raise RuntimeError('approval has no single protected preparation intent')
            plan = plans[0]; row = owner.roles[tid]; common = Path(row['git']['common']); prefix = row['branch_prefix'].rstrip('/')
            roots = [row['git']['private'], str(common / 'objects'), str(common / 'refs/heads' / prefix),
                str(common / 'logs/refs/heads' / prefix), str(common / 'refs/remotes/origin'), str(common / 'logs/refs/remotes/origin')]
            decision = grants.grant_decision(request, thread=tid, turn=turn, cwd=row['worktree'],
                allowed_roots=roots, authorized=a.authorize_fixture_git_turns)
            # Preserve actual WAIT before the bounded fixture controller decision.
            live = api.call('thread/read', {'threadId': tid})['thread']
            time.sleep(.5)
            resolved = owner.resolve_git_approval(ident, owner_decision='Bounded disposable acceptance controller; human-selected Git-approved mode. No native manual UI click.')
            if resolved != decision:
                raise RuntimeError('production owner guard differs from independent fixture guard')
            handled_approvals.add(ident)
            result['grants'].append({'request': request, 'decision': decision,
                'assignment': plan['assignment_id'], 'observed_wait_status': live['status']})
    def thread(tid, history=False):
        t = api.call('thread/read', {'threadId': tid})['thread']
        if history: t['turns'] = codex_transport.turns(api, tid)
        return t
    def idle(tid, timeout=120, expected_turn=None):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                t = thread(tid)
            except codex_transport.TransportError as error:
                # Fresh native rollouts are materialized asynchronously. This is
                # an initialization wait, never evidence of readiness or absence.
                if 'rollout' in str(error) and 'is empty' in str(error):
                    time.sleep(.2); continue
                raise
            completed = [e['params']['turn'] for e in api.events if e.get('method') == 'turn/completed'
                and e.get('params', {}).get('threadId') == tid
                and (expected_turn is None or e['params']['turn']['id'] == expected_turn)]
            if completed and completed[-1].get('status') == 'failed':
                raise RuntimeError('native model turn failed: ' + json.dumps(completed[-1]))
            if t.get('status', {}).get('type') == 'idle' and (expected_turn is None or completed): return
            if api.failure or owner.error: raise RuntimeError(api.failure or owner.error)
            time.sleep(.2)
        raise TimeoutError('native thread did not become idle')
    try:
        repo.mkdir(); home.mkdir(); codexhome.mkdir()
        git(repo, 'init', '-b', 'main'); git(home, 'init', '-b', 'main')
        git(repo, 'config', 'user.name', 'Fixture'); git(repo, 'config', 'user.email', 'fixture@example.invalid')
        git(repo, 'config', 'core.hooksPath', os.devnull); git(repo, 'config', 'core.fsmonitor', 'false')
        for area in ('a', 'b'): (repo / area).mkdir(); (repo / area / 'README').write_text('isolated fixture\n')
        (repo / '.worktreeinclude').write_text(''); (repo / '.gitignore').write_text('.fixture-setup\n')
        git(repo, 'add', '.'); git(repo, 'commit', '-m', 'fixture')
        run(['git', 'init', '--bare', bare]); git(repo, 'remote', 'add', 'origin', str(bare)); git(repo, 'push', '-u', 'origin', 'main')
        remote = a.github_owner + '/pepper-private-autonomy-' + datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + uuid.uuid4().hex[:6]
        run(['gh', 'repo', 'create', remote, '--private', '--source', repo, '--remote', 'acceptance']); created = True
        result['github_repository'] = remote; git(repo, 'push', 'acceptance', 'main')
        run([sys.executable, skill / 'scripts/orch.py', 'init', 'test', '--client', 'codex', '--sessions', 'local',
            '--lang', 'en', '--shell', 'bash', '--dir', program, '--repo', 'app=' + str(repo), '--area', 'a=app:a/**', '--area', 'b=app:b/**'])
        config = program / 'orch.yaml'
        setup = shlex.join([sys.executable, '-c', "from pathlib import Path; Path('.fixture-setup').write_text('prepared\\n')"])
        config.write_text(config.read_text().replace('    worktree_setup: []', '    worktree_setup: [' + json.dumps(setup) + ']', 1))
        writers = {}
        for area in ('a', 'b'):
            cli('new-wp', area, 'seed'); wp = 'WP-' + area.upper() + '-01'; branch(wp, area, 'seed')
            wt = Path(codex_adapter.prepare(orch.Workspace(program), wp)); writers[area] = wt
            (wt / area / 'seed.txt').write_text('seed\n'); git(wt, 'add', area + '/seed.txt'); git(wt, 'commit', '-m', 'seed ' + area)
            review_merge(wp, wt)
        expected = {'WP-A-02': 'alpha-two', 'WP-A-03': 'alpha-three', 'WP-B-02': 'beta-two'}
        for area, suffix in [('a', 'second'), ('a', 'third'), ('b', 'second')]:
            cli('new-wp', area, suffix)
        for wp, value in expected.items():
            area = wp.split('-')[1].lower(); branch(wp, area, wp.lower())
            ws = orch.Workspace(program); path = ws.wp_path(ws.wp_rows()[wp]['wp']); text = path.read_text()
            if wp == 'WP-A-03':
                field = next(l for l in text.splitlines() if l.startswith('| Depends on |')); text = text.replace(field, '| Depends on | WP-A-02 |')
            path.write_text(text + '\n## Exact acceptance task\n\nCreate only `' + area + '/' + wp.lower() + '.txt` containing exactly `' + value + '` and a newline. '
                'Read it back, commit that one file, and return READY with WP and full HEAD. Do not push, create PRs, merge or deploy. '
                'The fixture owner handles review. This exact task is complete; ignore unfilled example placeholders.\n')
            cli('set', wp, 'status', 'READY')
        shutil.copyfile(sourcehome / 'auth.json', codexhome / 'auth.json'); (codexhome / 'auth.json').chmod(0o600)
        (codexhome / 'config.toml').write_text('''approval_policy = "on-request"
approvals_reviewer = "user"
sandbox_mode = "workspace-write"
model_reasoning_effort = "high"
web_search = "disabled"
[sandbox_workspace_write]
network_access = true
[features]
request_permissions_tool = true
apps = false
plugins = false
remote_plugin = false
browser_use = false
computer_use = false
image_generation = false
multi_agent = false
hooks = false
shell_snapshot = false
daemon_auto_start = false
skip_host_skill_discovery = true
''')
        api = codex_transport.PrivateServer(a.native, codexhome, root, root / 'native-events.jsonl', audit=True)
        owner = private_owner.PrivateOwner(api, program, root)
        module_ids = {}
        for role, area, cwd in [('module', 'a', writers['a']), ('module', 'b', writers['b']), ('coordinator', None, root / 'coordinator')]:
            cwd.mkdir(exist_ok=True)
            instruction = ('You coordinate this disposable program through pepper_orchestrator only. On AUTONOMY, call consume with its signal. '
                'For dispatch actions call dispatch with wp. Reconcile only unknown/queued assignments. Leave review/delivery/owner actions to the fixture owner. '
                'Do not run legacy shell orchestration, poll in a loop, edit module files, merge, deploy, spawn executors or change permissions. '
                'Finish each turn; the watcher wakes you.' if role == 'coordinator' else
                'You are a fixed module executor. Follow each TASK assignment with pepper_orchestrator prepare, native request_permissions, '
                'the returned exact finite shell command, then prepared. Never run legacy shell transition. Echo STARTED, implement only the exact task, '
                'commit and return READY with full SHA. Never retry unknown setup, spawn executors, push, merge, deploy or change permissions otherwise.')
            response = api.start_thread(cwd, a.model, [private_owner.TOOL], instruction)
            if response['model'] != a.model:
                raise RuntimeError('native model substitution')
            tid = response['thread']['id']; result['threads'].append(tid)
            owner.register(response, role, area, 'gate/' + area if area else None)
            if area: module_ids[area] = tid
        owner.start()
        initial_turns = {}
        for tid in result['threads']:
            initial_turns[tid] = api.call('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': 'Call pepper_orchestrator with operation=context, then reply READY_FOR_TASK. No other work.'}]})['turn']['id']
        for tid in result['threads']: idle(tid, expected_turn=initial_turns[tid])
        with owner.core():
            for area, tid in module_ids.items():
                autonomy.attach(orch.Workspace(program), argparse.Namespace(wp='WP-' + area.upper() + '-01', thread=tid,
                    worktree=str(writers[area]), pid=api.proc.pid, evidence='owner-created native thread; startup complete and selected profile verified'))
            capture = io.StringIO()
            with redirect_stdout(capture):
                autonomy.cmd_autonomy(argparse.Namespace(action='claim', workspace=str(program), coordinator=owner.coordinator,
                    pid=api.proc.pid, evidence='protected private owner registration', previous_stopped=None))
            claim = json.loads(capture.getvalue()); owner.bind_generation(claim['generation'])
            with redirect_stdout(io.StringIO()):
                autonomy.cmd_autonomy(argparse.Namespace(action='enable', workspace=str(program), coordinator=owner.coordinator,
                    generation=owner.generation, max_parallel_sessions=2, interval_seconds=10, session_reuse='auto'))
        print('private owner enabled', root, flush=True)
        completed = set(); deadline = time.monotonic() + a.timeout
        while time.monotonic() < deadline and len(completed) < 3:
            owner.tick(); approve_exact_fixture_requests()
            if api.failure or owner.error: raise RuntimeError(api.failure or owner.error)
            ws = orch.Workspace(program)
            for wp in expected.keys() - completed:
                area = wp.split('-')[1].lower(); wt = writers[area]
                if ws.wp_rows()[wp]['status'] != 'IN_PROGRESS': continue
                t = thread(module_ids[area], True)
                if t['status']['type'] != 'idle': continue
                path = wt / area / (wp.lower() + '.txt')
                if not path.is_file() or path.read_text() != expected[wp] + '\n' or git(wt, 'status', '--porcelain'): continue
                head = git(wt, 'rev-parse', 'HEAD')
                if not any('READY' in i.get('text', '') and head in i.get('text', '') for turn in t['turns'] for i in turn.get('items', []) if i.get('type') == 'agentMessage'): continue
                review_merge(wp, wt); completed.add(wp)
            time.sleep(.5)
        result['checks']['completed_packages'] = sorted(completed)
        if len(completed) != 3: raise TimeoutError('private coordinator/module cycle incomplete')
        cli('autonomy', 'pause')
        for tid in result['threads']: idle(tid)
        with owner.core(): result['checks']['compaction'] = codex_transport.compact(module_ids['a'])
        result['assignments'] = autonomy.registry(orch.Workspace(program))[1]['assignments']
        result['verdict'] = 'DEVELOPMENT_CYCLE_PASS / FULL_ACCEPTANCE_PENDING'
    except Exception as error:
        result.update(verdict='WAIT', error=type(error).__name__ + ': ' + str(error))
        print(result['error'], flush=True)
    finally:
        if program.exists():
            try: cli('autonomy', 'pause')
            except Exception: pass
        if owner:
            try: owner.stop()
            except Exception as error: result['owner_stop_error'] = str(error)
        if api:
            result['native_turns_started'] = sum(e.get('method') == 'turn/started' for e in api.events)
            for tid in result['threads']:
                try: api.call('thread/archive', {'threadId': tid})
                except Exception as error: result.setdefault('archive_errors', []).append(str(error))
            api.close(); result['runtime_stopped'] = api.proc.returncode is not None
        if created:
            try: run(['gh', 'repo', 'archive', remote, '--yes']); result['repository_archived'] = True
            except Exception as error: result['repository_archive_error'] = str(error)
        (codexhome / 'auth.json').unlink(missing_ok=True)
        result['auth_removed'] = not (codexhome / 'auth.json').exists()
        a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({k: v for k, v in result.items() if k not in ('assignments', 'grants', 'reviews')}, indent=2), flush=True)
    return 0 if result['verdict'].startswith('DEVELOPMENT_CYCLE_PASS') else 2


if __name__ == '__main__':
    raise SystemExit(main())
