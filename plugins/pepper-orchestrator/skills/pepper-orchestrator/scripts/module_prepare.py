#!/usr/bin/env python3
"""Finite module-side preparation from an owner-held plan. Runs inside sandbox.

Stdout is evidence only when the owner matches the actual native command/turn;
this script, an environment variable or its JSON cannot authorize a host action.
"""
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import shutil
import sys
import tempfile
import time


def boundary_probe(spec):
    def attempt(action):
        try:
            action(); return {'acquired': True}
        except OSError as error:
            return {'acquired': False, 'errno': error.errno}
    def acquire(path, flags):
        fd = os.open(path, flags | os.O_NONBLOCK); os.close(fd)
    writes = {p: attempt(lambda p=p: acquire(p, os.O_WRONLY)) for p in spec['protected_paths']}
    aliases = {}
    with tempfile.TemporaryDirectory(prefix='.owner-boundary-', dir=Path.cwd()) as tmp:
        source = spec['integrity_canary']
        for kind in ('hardlink', 'symlink'):
            target = Path(tmp) / kind
            try:
                if kind == 'hardlink': os.link(source, target)
                else: target.symlink_to(source)
                aliases[kind] = attempt(lambda target=target: acquire(target, os.O_WRONLY))
            except OSError as error:
                aliases[kind] = {'acquired': False, 'errno': error.errno, 'creation_denied': True}
    descriptors = {}
    for fd in range(512):
        try:
            info = os.fstat(fd); descriptors[str(fd)] = {'type': stat.S_IFMT(info.st_mode), 'inode': info.st_ino, 'device': info.st_dev}
        except OSError as error:
            if error.errno != errno.EBADF: raise
    targets = {}
    for pid, fds in spec['controls'].items():
        row = {str(fd): attempt(lambda fd=fd: acquire('/proc/' + pid + '/fd/' + str(fd), os.O_RDWR)) for fd in fds}
        if sys.platform == 'darwin':
            lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
            lib.mach_task_self.restype = ctypes.c_uint32
            lib.task_for_pid.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
            port = ctypes.c_uint32(); rc = lib.task_for_pid(lib.mach_task_self(), int(pid), ctypes.byref(port))
            if port.value: lib.mach_port_deallocate(lib.mach_task_self(), port.value)
            row['task_for_pid'] = {'acquired': rc == 0, 'returncode': rc}
        targets[pid] = row
    env = dict(os.environ, CODEX_HOME=spec['home'])
    queued = subprocess.run([spec['native'], 'queue', '--thread', spec['coordinator'],
        '--message', 'READ_ONLY_GATE_CANARY_NO_ACTION'], env=env, capture_output=True, text=True, timeout=10)
    safe = (writes and all(not v['acquired'] and v.get('errno') in (errno.EPERM, errno.EACCES, errno.EROFS) for v in writes.values())
        and all(not v['acquired'] for row in targets.values() for v in row.values())
        and all(not a['acquired'] and a.get('errno') in (errno.EPERM, errno.EACCES, errno.EROFS, errno.EXDEV) for a in aliases.values())
        and set(descriptors) == {'0', '1', '2'} and queued.returncode != 0)
    return {'writes': writes, 'control_access': targets, 'descriptors': descriptors,
        'aliases': aliases,
        'queue': {'returncode': queued.returncode, 'stdout': queued.stdout, 'stderr': queued.stderr}, 'safe': bool(safe)}


def execute(plan):
    directory = Path(plan['worktree']).resolve()
    if Path.cwd().resolve() != directory or os.environ.get('CODEX_THREAD_ID') != plan['thread']:
        raise RuntimeError('preparation belongs to another native module/worktree')
    if time.time() > plan['expires_at']:
        raise RuntimeError('preparation plan expired; request owner reconciliation')
    boundary = boundary_probe(plan['boundary']) if plan.get('boundary') else None
    if boundary is not None and not boundary['safe']:
        raise RuntimeError('module boundary probe failed; owner inspection required: ' + json.dumps(boundary))
    def git(*args):
        r = subprocess.run([plan['git_executable'], '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
            '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', *args],
            capture_output=True, text=True, encoding='utf-8', timeout=90)
        if r.returncode:
            raise RuntimeError('git ' + args[0] + ': ' + r.stderr.strip())
        return r.stdout.strip()
    if Path(git('rev-parse', '--absolute-git-dir')).resolve() != Path(plan['private_gitdir']):
        raise RuntimeError('private gitdir drift')
    if Path(git('rev-parse', '--path-format=absolute', '--git-common-dir')).resolve() != Path(plan['common_gitdir']):
        raise RuntimeError('common gitdir drift')
    if git('status', '--porcelain') or git('branch', '--show-current') != plan['previous_branch']:
        raise RuntimeError('dirty or unexpected branch; do not retry preparation blindly')
    if git('rev-parse', 'HEAD') != plan['previous_head']:
        raise RuntimeError('previous head moved')
    if subprocess.run([plan['git_executable'], 'show-ref', '--verify', '--quiet', 'refs/heads/' + plan['branch']],
            capture_output=True).returncode == 0:
        raise RuntimeError('destination branch exists without a completed receipt')
    git('fetch', '--no-auto-maintenance', 'origin', plan['base'])
    base = git('rev-parse', '--verify', 'FETCH_HEAD^{commit}')
    changed = git('diff', '--name-only', plan['previous_head'], base, '--',
        '.codex/config.toml', '.codex/rules/pepper-orchestrator.rules', '.codex/pepper-setup.json')
    if changed:
        raise RuntimeError('new base changes native configuration; owner preparation required')
    git('switch', '-c', plan['branch'], base)
    for command in plan['setup']:
        r = subprocess.run(command, shell=True, cwd=directory, capture_output=True,
            text=True, encoding='utf-8', timeout=120)
        if r.returncode:
            raise RuntimeError('setup outcome requires inspection: ' + r.stderr.strip())
    if git('branch', '--show-current') != plan['branch']:
        raise RuntimeError('setup changed branch')
    return {'assignment_id': plan['assignment_id'], 'nonce': plan['nonce'],
        'thread': plan['thread'], 'complete': True, 'base': base,
        'branch': plan['branch'], 'head': git('rev-parse', 'HEAD'),
        'boundary': boundary,
        'helper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--plan', type=Path)
    group.add_argument('--boundary', type=Path)
    a = p.parse_args()
    if a.boundary:
        print(json.dumps({'boundary': boundary_probe(json.loads(a.boundary.read_text(encoding='utf-8'))),
            'caller': os.environ.get('CODEX_THREAD_ID'), 'cwd': os.getcwd()}), flush=True)
        return
    print(json.dumps(execute(json.loads(a.plan.read_text(encoding='utf-8')))), flush=True)


if __name__ == '__main__':
    main()
