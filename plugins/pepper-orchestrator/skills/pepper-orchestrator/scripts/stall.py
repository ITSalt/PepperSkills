"""Stalled-work detection for the coordinator's control tick (issue #45).

A package is stalled when the side it waits on is the executor and nothing moved
for `stall_minutes`: no file change, commit, index/HEAD update or push, and the
session is not observed busy. The action keeps a stable `idle_since`, so one
condition is one signal, not a minute counter.
"""
import os
from pathlib import Path

import streams

WAITING_ON_EXECUTOR = ('DISPATCHING', 'IN_PROGRESS', 'REVISE')
BUSY = ('active', 'busy')
MAX_DIRTY = 200  # Bounded per tick; the newest change is enough evidence of activity.


def worktree_of(repo, branch):
    result = streams.git(repo.local, 'worktree', 'list', '--porcelain')
    if result.returncode:
        return None
    path = None
    for line in result.stdout.splitlines():
        if line.startswith('worktree '):
            path = line[len('worktree '):]
        elif line == 'branch refs/heads/' + branch and path:
            return Path(path)
    return None


def activity(directory):
    """Newest evidence of work in a worktree, or None when it cannot be read."""
    times = []
    git_dir = streams.git(directory, 'rev-parse', '--absolute-git-dir')
    if git_dir.returncode == 0:
        for name in ('HEAD', 'index'):
            try:
                times.append(os.stat(Path(git_dir.stdout.strip()) / name).st_mtime)
            except OSError:
                pass
    commit = streams.git(directory, 'log', '-1', '--format=%ct')
    if commit.returncode == 0 and commit.stdout.strip().isdigit():
        times.append(float(commit.stdout.strip()))
    status = streams.git(directory, 'status', '--porcelain', '--untracked-files=normal')
    if status.returncode == 0:
        for line in status.stdout.splitlines()[:MAX_DIRTY]:
            name = line[3:].split(' -> ')[-1].strip('"')
            try:
                times.append(os.stat(Path(directory) / name).st_mtime)
            except OSError:
                pass
    return int(max(times)) if times else None


def scan(ws, data, observed, now, context):
    """Stalled actions for packages waiting on an executor; `context` is wp_context(ws, wp)."""
    limit = data['autonomy'].get('stall_minutes', 45) * 60
    busy = {i.get('wp') for k, i in data['instances'].items()
            if observed['sessions'].get(k, {}).get('thread', {}).get('status', {}).get('type') in BUSY}
    actions = []
    for wp, row in sorted(ws.wp_rows().items()):
        if row['status'] not in WAITING_ON_EXECUTOR or wp in busy:
            continue
        _, module, meta = context(ws, wp)  # next_actions has already read every package.
        if meta.get('execution') == 'research' or not meta.get('branch'):
            continue
        directory = worktree_of(module.repo, meta['branch'])
        if directory is None:
            continue  # Not started yet: dispatch/launch reconciliation owns that case.
        since = activity(directory)
        if since is not None and now - since >= limit:
            actions.append({'kind': 'stalled', 'wp': wp, 'idle_since': since, 'worktree': str(directory),
                            'required': 'inspect the session and its processes; nudge, restart or reassign'})
    for wp, record in sorted(data.get('research', {}).items()):
        since = record.get('updated_at')
        if record.get('phase') == 'collecting' and since and now - since >= limit and wp not in data.get('launches', {}):
            actions.append({'kind': 'stalled', 'wp': wp, 'idle_since': since,
                            'required': 'record returned results or decide on the collected evidence'})
    return actions
