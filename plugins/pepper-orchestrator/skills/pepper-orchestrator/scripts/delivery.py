#!/usr/bin/env python3
"""Trusted delivery: merge and stand by the orchestrator, only by an explicit owner decision.

By default the owner delivers. The `delivery` block of orch.yaml hands levels (merge, stand, prod,
prod_migrations) to the orchestrator, each only with a recorded decision D-n. Every action passes
gates by facts; a red gate is never forced, it goes back to the owner. Standard library + git + gh.
Imported by orch.py.
"""
import json
from pathlib import Path
import re
import subprocess
import time

import safe_edit
import streams

LEVELS = ('merge', 'stand', 'prod', 'prod_migrations')
VALUES = ('owner', 'orchestrator')
MERGE_METHODS = ('merge', 'squash', 'rebase')
DEFAULT_RUN_TIMEOUT = 1800
BLOCKS = re.compile(r'blocks delivery|блокирует доставку', re.I)
GRAPH_CHECKED = re.compile(r'graph: checked|граф: проверен', re.I)
PASSING = {'pass', 'skipping'}


class DeliveryError(Exception):
    pass


def settings(config):
    block = config.get('delivery') if isinstance(config.get('delivery'), dict) else {}
    return {**{level: str(block.get(level) or 'owner') for level in LEVELS},
            'enabled_by': block.get('enabled_by'), 'hold': block.get('hold') or None,
            'release_policy': block.get('release_policy'), 'release_window': block.get('release_window'),
            'max_prod_releases_per_day': block.get('max_prod_releases_per_day')}


def repo_setting(module, key, default=None):
    """A delivery setting of the module, else of its repository (0.1.0 modules keep them on the module)."""
    if key in module.raw:
        return module.raw.get(key)
    return module.repo.raw.get(key, default)


def merge_method(module):
    return str(repo_setting(module, 'merge_method') or 'merge')


def run_timeout(module):
    value = repo_setting(module, 'run_timeout')
    return value if isinstance(value, int) and value > 0 else DEFAULT_RUN_TIMEOUT


def errors(config, decision_ids):
    """lint errors of the delivery block and repository delivery settings."""
    found = []
    raw = config.get('delivery')
    if raw is None:
        return found
    if not isinstance(raw, dict):
        return ['orch.yaml: delivery must be a mapping']
    d = settings(config)
    for level in LEVELS:
        if d[level] not in VALUES:
            found.append(f'orch.yaml: delivery.{level} must be owner or orchestrator')
    trusted = [level for level in LEVELS if d[level] == 'orchestrator']
    if trusted and not d['enabled_by']:
        found.append(f'orch.yaml: delivery {", ".join(trusted)}: orchestrator needs enabled_by: D-n (the owner\'s '
                     'recorded decision)')
    elif trusted and str(d['enabled_by']) not in decision_ids:
        found.append(f'orch.yaml: delivery.enabled_by {d["enabled_by"]} is not in decisions.md')
    if d['prod'] == 'orchestrator' and d['merge'] == 'owner':
        found.append('orch.yaml: delivery.prod: orchestrator needs delivery.merge: orchestrator (a prod release '
                     'without its own merge and stand makes no sense)')
    for kind, items in (('repo', config.get('repos') or []), ('module', config.get('modules') or [])):
        for item in items:
            if not isinstance(item, dict):
                continue
            method = item.get('merge_method')
            if method is not None and method not in MERGE_METHODS:
                found.append(f'orch.yaml: {kind} {item.get("id")}: merge_method must be merge, squash or rebase')
            timeout = item.get('run_timeout')
            if timeout is not None and not (isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0):
                found.append(f'orch.yaml: {kind} {item.get("id")}: run_timeout must be a positive number of seconds')
    return found


# ---------------------------------------------------------------- orch.yaml edits

def _block(text):
    """(start, end) of the top-level delivery block in text, or None."""
    match = re.search(r'^delivery:[ \t]*(\{\})?[ \t]*(#.*)?\n', text, re.M)
    if not match:
        return None
    end = match.end()
    for line in text[match.end():].split('\n'):
        if line.strip() and not line.startswith((' ', '#')):
            break
        end += len(line) + 1
    return match.start(), min(end, len(text))


def set_key(path, key, value):
    """Set (or remove, with value None) one key of the delivery block by a point edit."""
    text = Path(path).read_text(encoding='utf-8')
    rendered = json.dumps(value, ensure_ascii=False) if key == 'hold' and value is not None else value
    span = _block(text)
    if span is None:
        if value is None:
            return
        safe_edit.replace_once(path, text, text.rstrip('\n') + f'\n\ndelivery:\n  {key}: {rendered}\n')
        return
    start, end = span
    block = text[start:end]
    lines = block.rstrip('\n').split('\n')
    head = 'delivery:\n' if lines[0].split('#')[0].strip() in ('delivery:', 'delivery: {}') else lines[0] + '\n'
    body = [line for line in lines[1:] if not re.match(rf'^  {re.escape(key)}:', line)]
    if value is not None:
        body.append(f'  {key}: {rendered}')
    new = head + '\n'.join(body) + ('\n' if body else '')
    if not body and value is None:
        new = 'delivery: {}\n'
    safe_edit.replace_once(path, block, new if block.endswith('\n') else new.rstrip('\n'))


# ---------------------------------------------------------------- facts through gh

def gh_json(args):
    result = subprocess.run(['gh', *args], encoding='utf-8', errors='replace', capture_output=True)
    if result.returncode:
        raise DeliveryError((result.stderr or result.stdout).strip().split('\n')[0] or f'gh exited {result.returncode}')
    try:
        return json.loads(result.stdout or 'null')
    except ValueError as error:
        raise DeliveryError(f'gh returned no JSON: {error}')


def pr_facts(repo_name, pr):
    return gh_json(['pr', 'view', pr, '--repo', repo_name, '--json',
                    'number,url,state,headRefOid,mergeable,baseRefName,title,mergeCommit'])


def pr_checks(repo_name, number):
    """(verdict, detail) of the PR's checks: all passed or skipped is green."""
    result = subprocess.run(['gh', 'pr', 'checks', str(number), '--repo', repo_name, '--json', 'name,bucket'],
                            encoding='utf-8', errors='replace', capture_output=True)
    if result.returncode and 'no checks' in (result.stderr + result.stdout).lower():
        return True, 'no checks reported'
    try:
        checks = json.loads(result.stdout or '[]')
    except ValueError:
        return False, (result.stderr or 'gh pr checks failed').strip().split('\n')[0]
    bad = [c for c in checks if str(c.get('bucket', '')).lower() not in PASSING]
    if bad:
        return False, ', '.join(f'{c.get("name")}: {c.get("bucket")}' for c in bad[:5])
    return True, f'{len(checks)} checks passed' if checks else 'no checks reported'


def merge(repo_name, number, method, delete_branch):
    if method not in MERGE_METHODS:  # never --admin or any other flag from a mistyped orch.yaml
        raise DeliveryError(f'merge_method {method!r} is not one of {", ".join(MERGE_METHODS)}')
    args = ['gh', 'pr', 'merge', str(number), '--repo', repo_name, f'--{method}']
    if delete_branch:
        args.append('--delete-branch')
    result = subprocess.run(args, encoding='utf-8', errors='replace', capture_output=True)
    if result.returncode:
        raise DeliveryError((result.stderr or result.stdout).strip().split('\n')[0] or 'gh pr merge failed')
    return ' '.join(args[:1] + args[1:])


def wait_run(repo_name, workflow, sha, branch_name, timeout, interval):
    """(ok, detail): the deploy run of workflow for sha on branch, watched to its end."""
    deadline = time.monotonic() + timeout
    run = None
    while True:
        runs = gh_json(['run', 'list', '--repo', repo_name, '--workflow', workflow, '--commit', sha, '--json',
                        'databaseId,status,conclusion,headBranch,url', '--limit', '20']) or []
        runs = [r for r in runs if not r.get('headBranch') or r.get('headBranch') == branch_name]
        if runs:
            run = runs[0]
            break
        if time.monotonic() >= deadline:
            return False, f'{workflow}: no run for {sha[:10]} on {branch_name} within {timeout} s'
        time.sleep(interval)
    remaining = max(1, int(deadline - time.monotonic()))
    try:
        watched = subprocess.run(['gh', 'run', 'watch', str(run['databaseId']), '--repo', repo_name, '--exit-status'],
                                 encoding='utf-8', errors='replace', capture_output=True, timeout=remaining)
    except subprocess.TimeoutExpired:
        return False, f'{workflow}: run {run["databaseId"]} did not finish within {timeout} s'
    if watched.returncode:
        return False, f'{workflow}: run {run.get("url") or run["databaseId"]} failed'
    return True, f'{workflow}: run {run.get("url") or run["databaseId"]} succeeded'


def run_command(command, cwd, timeout):
    """(ok, detail) of a configured command (deploy_test, rollback_test); stdin is closed, so a script that
    asks for a TTY confirmation fails instead of waiting."""
    try:
        result = subprocess.run(command, shell=True, cwd=cwd, encoding='utf-8', errors='replace',
                                capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f'`{command}` timed out after {timeout} s'
    tail = (result.stdout + result.stderr).strip().split('\n')[-1:]
    return result.returncode == 0, f'`{command}` exited {result.returncode}' + (f': {tail[0]}' if tail and tail[0] else '')


def previous_sha(repo, sha):
    """The first parent of sha: locally when known, else after a fetch that never prompts."""
    if not repo.local.is_dir():
        return None
    result = streams.git(repo.local, 'rev-parse', '--verify', '-q', f'{sha}^1')
    if result.returncode:
        import os
        subprocess.run(['git', '-C', str(repo.local), 'fetch', '-q', 'origin'], capture_output=True,
                       encoding='utf-8', errors='replace', env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}, timeout=120)
        result = streams.git(repo.local, 'rev-parse', '--verify', '-q', f'{sha}^1')
    return result.stdout.strip() if result.returncode == 0 else None
