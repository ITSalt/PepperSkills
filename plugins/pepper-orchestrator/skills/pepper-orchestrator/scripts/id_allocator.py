"""Durable, namespaced, idempotent number reservations on one local host."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import uuid

import state_io


class AllocationError(RuntimeError):
    pass


def repo_scope(path):
    result = subprocess.run(['git', '-C', str(Path(path).expanduser()), 'rev-parse',
                             '--path-format=absolute', '--git-common-dir'],
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        raise AllocationError(f'not a Git repository: {path}')
    common = os.path.normcase(str(Path(result.stdout.strip()).resolve()))
    return 'repo-' + hashlib.sha256(common.encode()).hexdigest()


def scope_paths(scope):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', scope):
        raise AllocationError('invalid scope identifier')
    directory = state_io.runtime_dir() / 'ids' / hashlib.sha256(scope.encode()).hexdigest()
    return directory / 'ids.sqlite3', directory / 'registered.json'


def connect(scope, initialize=False):
    db, marker = scope_paths(scope)
    if marker.exists() and not db.is_file():
        raise AllocationError(f'allocator missing for {scope}; restore {db}; never reset issued numbers')
    if not marker.exists() and not initialize:
        raise AllocationError(f'allocator not registered: {scope}; run id migrate first')
    if initialize:
        db.parent.mkdir(parents=True, exist_ok=True)
    con = None
    try:
        con = sqlite3.connect(str(db), timeout=10, isolation_level=None)
        con.execute('PRAGMA synchronous=FULL')
        if initialize:
            con.execute('PRAGMA journal_mode=DELETE')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS counters(namespace TEXT PRIMARY KEY, value INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS reservations(
                    request TEXT PRIMARY KEY, namespace TEXT NOT NULL,
                    first INTEGER NOT NULL, count INTEGER NOT NULL);
            ''')
        else:
            con.execute('SELECT value FROM counters LIMIT 1')
        return con
    except sqlite3.Error as e:
        if con:
            con.close()
        raise AllocationError(f'allocator unavailable for {scope}: {e}; restore or retry, no fallback') from e


def register(scope, seeds):
    for name, value in seeds.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,119}', name) or isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 9223372036854775807:
            raise AllocationError('seed requires a valid namespace and a nonnegative 64-bit integer')
    db, marker = scope_paths(scope)
    with state_io.transaction(db.parent):
        con = connect(scope, initialize=True)
        try:
            con.execute('BEGIN IMMEDIATE')
            for name, value in seeds.items():
                con.execute('INSERT INTO counters VALUES (?,?) ON CONFLICT(namespace) DO UPDATE '
                            'SET value=max(value,excluded.value)', (name, value))
            con.execute('COMMIT')
            if os.name != 'nt':
                db.chmod(0o600)
            state_io.atomic(marker, json.dumps({'scope': scope, 'version': 1}).encode(), 0o600)
        finally:
            con.close()
    return str(db)


def reserve(scope, namespace, request_id, count=1):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,119}', namespace):
        raise AllocationError('invalid namespace')
    if not request_id or len(request_id) > 250 or any(ord(c) < 32 for c in request_id):
        raise AllocationError('request-id must contain 1..250 printable characters')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100000:
        raise AllocationError('count must be 1..100000')
    con = connect(scope)
    try:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT namespace,first,count FROM reservations WHERE request=?', (request_id,)).fetchone()
        if old:
            if (old[0], old[2]) != (namespace, count):
                raise AllocationError('request-id already reserved with different namespace or count')
            first = old[1]
        else:
            con.execute('INSERT OR IGNORE INTO counters VALUES (?,0)', (namespace,))
            value = con.execute('SELECT value FROM counters WHERE namespace=?', (namespace,)).fetchone()[0]
            if value > 9223372036854775807 - count:
                raise AllocationError('sequence exhausted')
            first = value + 1
            con.execute('UPDATE counters SET value=? WHERE namespace=?', (value + count, namespace))
            con.execute('INSERT INTO reservations VALUES (?,?,?,?)', (request_id, namespace, first, count))
        con.execute('COMMIT')
        return {'scope': scope, 'namespace': namespace, 'request_id': request_id,
                'first': first, 'count': count, 'numbers': list(range(first, first + count))}
    except sqlite3.Error as e:
        raise AllocationError(f'allocator busy or failed: {e}; retry with the same request-id') from e
    finally:
        con.close()


ID = re.compile(r'(?<![A-Z0-9-])(WP-[A-Z0-9]+(?:-[A-Z0-9]+)*|PLUGIN-BUG|BUG|R|P|D|A|Q|B)-(\d+)\b')


def import_seeds(root, branches=True, namespaces=()):
    root = Path(root).resolve()
    seeds = {}
    def scan(text):
        for prefix, n in ID.findall(text):
            seeds[prefix] = max(seeds.get(prefix, 0), int(n))
        for prefix in namespaces:
            for n in re.findall(r'(?<![A-Za-z0-9_-])' + re.escape(prefix) + r'[-_](\d+)\b', text):
                seeds[prefix] = max(seeds.get(prefix, 0), int(n))
    for p in root.rglob('*'):
        if p.is_file() and p.suffix in ('.md', '.sql', '.json', '.yaml', '.yml') and not any(
                x in ('.orch-backup', '.git', 'node_modules', '.pepper-worktrees') for x in p.relative_to(root).parts):
            scan(p.read_text(encoding='utf-8'))
    if branches:
        refs = subprocess.run(['git', '-C', str(root), 'for-each-ref', '--format=%(refname)'],
                              capture_output=True, text=True, encoding='utf-8')
        if refs.returncode == 0:
            top = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                                 capture_output=True, text=True, encoding='utf-8')
            rel = root.relative_to(Path(top.stdout.strip()))
            for ref in refs.stdout.splitlines():
                result = subprocess.run(['git', '-C', str(root), 'grep', '-E',
                                         '(WP-|PLUGIN-BUG-|BUG-|[RPDAQB]-' + ''.join('|' + re.escape(n) + '[-_]' for n in namespaces) + ')[A-Z0-9-]*[0-9]',
                                         ref, '--', str(rel) if str(rel) != '.' else '.'],
                                        capture_output=True, text=True, encoding='utf-8')
                if result.returncode not in (0, 1):
                    raise AllocationError(f'cannot import IDs from {ref}: {result.stderr.strip()}')
                scan(result.stdout)
    return seeds


def new_scope():
    return 'program-' + str(uuid.uuid4())
