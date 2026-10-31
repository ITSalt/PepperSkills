#!/usr/bin/env python3
"""Explicit owner console over a verified archive and private App Server STDIO.

Run with python3 -I -S -B from an owner-installed directory outside model roots.
No listener, public file inbox, system service or automatic permission approval.
"""
import argparse
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
import zipfile


CONFIG = '''approval_policy = "on-request"
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
'''

COORDINATOR = ('Use pepper_orchestrator for this program. On AUTONOMY call consume with its signal, '
    'then dispatch compatible WP actions and reconcile unknown/queued assignments. '
    'Finish each turn; the passive watcher wakes you. Never poll in a model loop, run legacy shell '
    'orchestration, create sessions, edit module files, merge, deploy or change permissions. '
    'Owner/review/delivery actions stay with the owner.')
MODULE = ('Follow TASK assignment IDs through pepper_orchestrator prepare, native request_permissions, '
    'the exact returned finite shell command, then prepared. Wait for the owner decision; no escalation '
    'or alternate host runner. Echo STARTED before implementation. Commit only this package and return '
    'READY with full SHA. Never retry unknown setup, create another executor, edit coordinator documents, '
    'push/merge/deploy or change permissions otherwise. A repeated assignment is the same work.')


def file_sha(path):
    value = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def within(path, root):
    """Identity-based ancestry also catches case aliases on macOS volumes."""
    root = Path(root).resolve(strict=True)
    identity = (root.stat().st_dev, root.stat().st_ino)
    path = Path(path).resolve()
    for parent in (path, *path.parents):
        try:
            info = parent.stat()
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) == identity:
            return True
    return False


def outside_repository(path):
    path = Path(path).resolve(strict=True)
    if path.is_file(): path = path.parent
    device = path.stat().st_dev
    for parent in (path, *path.parents):
        if parent.stat().st_dev != device: break
        if (parent / '.git').exists():
            raise RuntimeError('install owner code outside Git worktrees; never load mutable project Python')


def verify_archive(archive, expected, skill):
    if not re.fullmatch(r'[0-9a-f]{64}', expected) or file_sha(archive) != expected:
        raise RuntimeError('candidate archive SHA256 mismatch')
    with zipfile.ZipFile(archive) as bundle:
        roots = [name[:-len('scripts/orch.py')] for name in bundle.namelist() if name.endswith('/scripts/orch.py')]
        canonical = [r for r in roots if '/codex/' not in r]
        if len(canonical) != 1:
            raise RuntimeError('archive must contain exactly one canonical Orchestrator skill')
        prefix = canonical[0]
        count = 0; python_files = set()
        if any(p.is_symlink() for p in skill.rglob('*')):
            raise RuntimeError('installed skill must not contain symlinks')
        for member in bundle.infolist():
            if not member.filename.startswith(prefix) or member.is_dir():
                continue
            relative = member.filename[len(prefix):]; path = PurePosixPath(relative)
            if path.is_absolute() or '..' in path.parts or '\\' in relative or member.file_size > 64 * 1024 * 1024:
                raise RuntimeError('unsafe archive member')
            target = skill / relative
            if target.is_symlink() or not target.is_file() or target.stat().st_nlink != 1 or target.read_bytes() != bundle.read(member):
                raise RuntimeError('installed skill differs from verified archive: ' + relative)
            count += 1
            if relative.endswith('.py'): python_files.add(relative)
        if count < 10:
            raise RuntimeError('incomplete installed skill')
        required = {'scripts/orch.py', 'scripts/owner_main.py', 'scripts/private_owner.py',
                    'scripts/module_prepare.py', 'scripts/codex_transport.py'}
        actual = {p.relative_to(skill).as_posix() for p in skill.rglob('*.py')}
        if not required <= python_files or python_files != actual:
            raise RuntimeError('missing or extra unverified installed Python files')


def validate_paths(manifest, directory, native, archive, auth_home):
    if manifest.get('version') != 1 or not isinstance(manifest.get('model'), str):
        raise RuntimeError('owner manifest version=1 and explicit model required')
    if not manifest.get('modules') or not isinstance(manifest.get('coordinator'), dict):
        raise RuntimeError('declare one coordinator and fixed module worktrees')
    actors = [manifest['coordinator'], *manifest['modules']]
    roots = [Path(a['cwd']).resolve(strict=True) for a in actors]
    if any(not r.is_dir() for r in roots):
        raise RuntimeError('actor worktrees must be existing directories')
    if any(within(a, b) or within(b, a) for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise RuntimeError('actor worktrees must not overlap')
    protected_dirs = [Path(__file__).resolve().parent.parent, directory,
        Path(manifest['workspace']).resolve(strict=True), native.parent,
        Path.home() / '.local/share/pepper-orchestrator/owner-locks']
    protected = [*protected_dirs, native, archive, Path(sys.executable).resolve(),
        Path(shutil.which('git')).resolve(), auth_home / 'auth.json']
    helper = native.with_name('codex-code-mode-host')
    if helper.exists(): protected.append(helper.resolve())
    temporary = {Path(p).resolve() for p in ('/tmp', '/private/tmp', tempfile.gettempdir(), os.environ.get('TMPDIR', '/tmp'))}
    if any(within(p, root) for p in protected for root in roots):
        raise RuntimeError('actor root exposes owner authority')
    if any(p.exists() and within(root, p) for p in protected_dirs for root in roots):
        raise RuntimeError('actor root is inside protected owner data/code')
    if any(p.is_relative_to(t) for p in protected for t in temporary):
        raise RuntimeError('owner code/state/executables cannot live in shared writable temporary roots')
    return roots


@contextmanager
def program_mutex(workspace):
    import fcntl
    info = Path(workspace).stat()
    identity = hashlib.sha256(f'{info.st_dev}:{info.st_ino}'.encode()).hexdigest()
    target = Path.home() / '.local/share/pepper-orchestrator/owner-locks' / (identity + '.lock')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('another private owner holds this program') from error
        yield
    finally:
        os.close(fd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--native', type=Path, required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--auth-home', type=Path, default=Path.home() / '.codex')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--preflight', action='store_true', help='verify archive/paths only; no server or model')
    a = p.parse_args()
    if os.name == 'nt': p.error('private owner live mode requires Linux or macOS')
    if not sys.flags.isolated or not sys.flags.no_site:
        p.error('run with python3 -I -S -B from the verified installed archive')
    manifest = json.loads(a.manifest.read_text(encoding='utf-8'))
    directory, native, archive, auth_home = (v.expanduser().resolve() for v in (a.directory, a.native, a.archive, a.auth_home))
    if not native.is_file() or not archive.is_file():
        raise RuntimeError('native executable and candidate archive must exist')
    roots = validate_paths(manifest, directory, native, archive, auth_home)
    skill = Path(__file__).resolve().parent.parent
    outside_repository(skill)
    verify_archive(archive, a.sha256, skill)
    if a.preflight:
        print(json.dumps({'archive_sha256': a.sha256, 'paths': 'verified', 'model_turns': 0})); return 0
    # Only verified, protected installed code is imported. No ambient project Python.
    sys.path.insert(0, str(skill / 'scripts'))
    import autonomy
    import codex_transport
    import orch
    import private_owner
    import state_io
    workspace = Path(manifest['workspace']).resolve()
    with program_mutex(workspace):
        if a.resume:
            saved = private_owner.PrivateOwner.validate_recovery(directory, native, workspace)
            expected = {(m['module'], str(Path(m['cwd']).resolve()), m['branch_prefix'].rstrip('/') + '/') for m in manifest['modules']}
            actual = {(r['module'], r['worktree'], r['branch_prefix']) for r in saved['roles'].values() if r['role'] == 'module'}
            coords = [r for r in saved['roles'].values() if r['role'] == 'coordinator']
            if actual != expected or len(coords) != 1 or coords[0]['worktree'] != str(Path(manifest['coordinator']['cwd']).resolve()):
                raise RuntimeError('saved registration is incomplete or differs from the owner manifest')
        else:
            _, existing = autonomy.registry(orch.Workspace(workspace))
            if existing['instances'] or existing.get('coordinator'):
                raise RuntimeError('existing program ownership/sessions require explicit migration or --resume')
            directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            if any(directory.iterdir()): raise RuntimeError('new owner directory must be empty')
            saved = None
        home = directory / 'codex-home'; home.mkdir(exist_ok=a.resume)
        config = home / 'config.toml'
        if a.resume:
            if saved['codex_home'] != str(home) or state_io.digest(config) != saved.get('isolated_config_sha256'):
                raise RuntimeError('isolated owner configuration drift')
        else:
            config.write_text(CONFIG, encoding='utf-8')
        auth = home / 'auth.json'
        api = None; owner = None; registered = []
        try:
            shutil.copyfile(auth_home / 'auth.json', auth); auth.chmod(0o600)
            os.environ.update(CODEX_HOME=str(home), ORCH_RUNTIME_DIR=str(directory / 'runtime'), PYTHONDONTWRITEBYTECODE='1')
            api = codex_transport.PrivateServer(native, home, directory, directory / ('events-' + uuid.uuid4().hex + '.jsonl'), actor_roots=roots)
            owner = private_owner.PrivateOwner(api, workspace, directory)
            if saved:
                for tid, row in saved['roles'].items():
                    response = api.resume_thread(tid, row['worktree'])
                    if response['thread']['id'] != tid or response['model'] != row['profile']['model']:
                        raise RuntimeError('same-thread/model recovery failed')
                    owner.register(response, row['role'], row.get('module'), row.get('branch_prefix'))
                    registered.append(tid)
            else:
                for role, entry in [('coordinator', manifest['coordinator']), *[('module', m) for m in manifest['modules']]]:
                    response = api.start_thread(entry['cwd'], manifest['model'], [private_owner.TOOL],
                        (COORDINATOR if role == 'coordinator' else MODULE) + '\n' + entry.get('instructions', ''))
                    if response['model'] != manifest['model']: raise RuntimeError('native model substitution')
                    owner.register(response, role, entry.get('module'), entry.get('branch_prefix'))
                    registered.append(response['thread']['id'])
            owner.start()
            for tid in registered:
                turn = api.call('turn/start', {'threadId': tid, 'input': [{'type': 'text',
                    'text': 'Call pepper_orchestrator operation=context once, then reply READY_FOR_TASK. No implementation.'}]})['turn']['id']
                api.wait_idle(tid, turn)
            with owner.core():
                ws = orch.Workspace(workspace)
                for row in owner.roles.values():
                    if row['role'] != 'module': continue
                    entry = next(m for m in manifest['modules'] if m['module'] == row['module'])
                    wp = autonomy.registry(ws)[1]['instances']['codex:' + row['thread']]['wp'] if saved else entry['wp']
                    autonomy.attach(ws, argparse.Namespace(wp=wp, thread=row['thread'], worktree=row['worktree'],
                        pid=api.proc.pid, evidence='explicit verified private owner launch/recovery'))
                out = io.StringIO()
                with redirect_stdout(out):
                    autonomy.cmd_autonomy(argparse.Namespace(action='recover' if saved else 'claim', workspace=str(workspace),
                        coordinator=owner.coordinator, pid=api.proc.pid, evidence='protected native registration',
                        previous_stopped='positive native process exit, verified installed code and empty terminal history' if saved else None))
                owner.bind_generation(json.loads(out.getvalue())['generation'])
                with redirect_stdout(io.StringIO()):
                    autonomy.cmd_autonomy(argparse.Namespace(action='resume' if saved else 'enable', workspace=str(workspace),
                        coordinator=owner.coordinator, generation=owner.generation, max_parallel_sessions=None,
                        interval_seconds=None, session_reuse=None))
            commands = queue.Queue()
            def read_console():
                for line in sys.stdin: commands.put(line.strip())
                commands.put('stop')
            threading.Thread(target=read_console, daemon=True).start()
            shown = set()
            print('Private owner active. Commands: status, pause, resume, grant ID, deny ID, stop.', flush=True)
            while not api.failure:
                owner.tick()
                for ident, request in list(api.approvals.items()):
                    if ident not in shown:
                        print('WAIT ' + json.dumps({'id': ident, 'request': request}, ensure_ascii=True), flush=True)
                        shown.add(ident)
                try: text = commands.get(timeout=1)
                except queue.Empty: continue
                words = text.split()
                if words == ['stop']: break
                try:
                    if words == ['status']:
                        print(json.dumps({'epoch': api.epoch, 'generation': owner.generation,
                            'pending_approvals': list(api.approvals), 'error': owner.error}), flush=True)
                    elif words in (['pause'], ['resume']):
                        with owner.core():
                            autonomy.cmd_autonomy(argparse.Namespace(action=words[0], workspace=str(workspace), coordinator=owner.coordinator,
                                generation=owner.generation, max_parallel_sessions=None, interval_seconds=None, session_reuse=None))
                    elif len(words) == 2 and words[0] in ('grant', 'deny'):
                        matches = [k for k in api.approvals if str(k) == words[1]]
                        if len(matches) != 1: raise RuntimeError('unknown/ambiguous approval ID')
                        ident = matches[0]
                        if words[0] == 'grant':
                            owner.resolve_git_approval(ident, owner_decision='explicit owner console grant ' + str(ident))
                        else:
                            method = api.approvals[ident]['method']
                            if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                                api.reply_approval(ident, {'decision': 'decline'})
                            elif method == 'item/permissions/requestApproval':
                                api.reply_approval(ident, {'permissions': {}, 'scope': 'turn'})
                            else: raise RuntimeError('unsupported request; stop and inspect')
                    else: print('Unknown command; no action.', flush=True)
                except Exception as error:
                    print('BLOCKED ' + type(error).__name__ + ': ' + str(error), flush=True)
            if api.failure: raise RuntimeError(api.failure)
        finally:
            try:
                if owner:
                    owner.worker_stop.set()
                    try:
                        with owner.core(), redirect_stdout(io.StringIO()):
                            autonomy.cmd_autonomy(argparse.Namespace(action='pause', workspace=str(workspace)))
                        owner.save_manifest()
                    except Exception as error:
                        print('Shutdown state requires inspection: ' + str(error), file=sys.stderr)
                try:
                    if api: api.close()
                finally:
                    if owner: owner.stop()
            finally:
                auth.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
