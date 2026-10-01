"""Short, reentrant process locks and recoverable local file transactions.

Locks are operating-system locks, released on process death. Undo journals make
interrupted multi-file operations recoverable without overwriting foreign edits.
No network or long-running command belongs inside transaction().
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time


class StateError(RuntimeError):
    pass


_local = threading.local()
_thread_locks = {}
_guard = threading.Lock()


def runtime_dir():
    return Path(os.environ.get('ORCH_RUNTIME_DIR', '~/.pepper-orchestrator/runtime')).expanduser().resolve()


def root_for(path):
    path = Path(path).resolve()
    # Explicit transactions also cover creation of orch.yaml and its sibling files.
    active = getattr(_local, 'active', {})
    owned = [Path(root) for root in active if path == Path(root) or Path(root) in path.parents]
    if owned:
        return max(owned, key=lambda root: len(root.parts))
    directory = path if path.is_dir() else path.parent
    for parent in (directory, *directory.parents):
        if (parent / 'orch.yaml').is_file():
            return parent
    for parent in (directory, *directory.parents):
        if (parent / '.git').exists():
            return parent
    return directory


def atomic(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        fsync_directory(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def fsync_directory(directory):
    if os.name != 'nt':
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _encode(data):
    return None if data is None else base64.b64encode(data).decode('ascii')


def _decode(data):
    return None if data is None else base64.b64decode(data)


def _save(tx):
    atomic(tx['journal'], json.dumps({'entries': tx['entries']}).encode(), 0o600)


def _rollback(journal):
    if not journal.exists():
        return
    entries = json.loads(journal.read_text(encoding='utf-8'))['entries']
    # Validate all touched files before rolling anything back.
    histories = {}
    for e in entries:
        histories.setdefault(e['path'], []).append(e)
    for name, history in histories.items():
        p = Path(name)
        current = p.read_bytes() if p.exists() else None
        known = [_decode(e[k]) for e in history for k in ('before', 'after')]
        if current not in known:
            raise StateError(f'recovery conflict at {name}; preserved journal: {journal}')
    for history in reversed(list(histories.values())):
        e = history[0]
        p, before = Path(e['path']), _decode(e['before'])
        if before is None:
            p.unlink(missing_ok=True)
        else:
            atomic(p, before, e['mode'])
    journal.unlink()
    fsync_directory(journal.parent)


@contextmanager
def transaction(root, timeout=10):
    root = os.path.normcase(str(Path(root).resolve()))
    active = getattr(_local, 'active', {})
    if root in active:
        yield
        return
    key = hashlib.sha256(root.encode()).hexdigest()
    directory = runtime_dir() / 'locks'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal = directory / (key + '.txn.json')
    with _guard:
        mutex = _thread_locks.setdefault(root, threading.RLock())
    if not mutex.acquire(timeout=timeout):
        raise StateError(f'state busy after {timeout}s: {root}; retry the operation')
    handle = None
    acquired = False
    try:
        handle = open(directory / (key + '.lock'), 'a+b')
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0'); handle.flush()
        else:
            import fcntl
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise StateError(f'state busy after {timeout}s: {root}; retry the operation')
                time.sleep(.025)
        _rollback(journal)
        tx = {'journal': journal, 'entries': []}
        _local.active = {**active, root: tx}
        try:
            yield
        except BaseException:
            _rollback(journal)
            raise
        else:
            journal.unlink(missing_ok=True)
            fsync_directory(journal.parent)
        finally:
            _local.active = active
    finally:
        if handle:
            if acquired:
                if os.name == 'nt':
                    handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        mutex.release()


def record(path, after):
    """Write-ahead undo record. Caller must hold the path's transaction lock."""
    path = Path(os.path.normcase(str(Path(path).resolve())))
    active = getattr(_local, 'active', {})
    tx = active.get(os.path.normcase(str(root_for(path))))
    if tx is None:
        raise StateError(f'no transaction for {path}')
    before = path.read_bytes() if path.exists() else None
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    tx['entries'].append({'path': str(path), 'before': _encode(before),
                          'after': _encode(after), 'mode': mode})
    _save(tx)


def digest(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else 'missing'
