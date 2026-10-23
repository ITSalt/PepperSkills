#!/usr/bin/env python3
"""Trusted delivery: merge and stand by the orchestrator, only by an explicit owner decision.

By default the owner delivers. The `delivery` block of orch.yaml hands levels (merge, stand, prod,
prod_migrations) to the orchestrator, each only with a recorded decision D-n. Every action passes
gates by facts; a red gate is never forced, it goes back to the owner. Standard library + git + gh.
Imported by orch.py.
"""
import json
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import release
import safe_edit
import state_io
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


@contextmanager
def operation_lock(root):
    """One delivery workflow per local program; hold/state writes remain independent.

    This is not a state transaction. Network waits may hold this workflow mutex,
    while short transactions (including hold) remain usable. OS process death
    releases the mutex; persisted outcome records still prevent blind replay.
    """
    key = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()
    directory = state_io.runtime_dir() / 'delivery-locks'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / (key + '.lock')).open('a+b') as handle:
        try:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0'); handle.flush()
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            raise DeliveryError('another delivery operation is active; hold remains available; retry after reconciliation') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def shell_program(shell):
    if shell == 'powershell':
        executable = shutil.which('pwsh')
    elif shell == 'bash':
        executable = None
        if os.name == 'nt':
            # System32/bash.exe starts WSL, not the program's Git Bash shell.
            git = shutil.which('git')
            if git:
                for parent in Path(git).resolve().parents:
                    for candidate in (parent / 'bin/bash.exe', parent / 'usr/bin/bash.exe'):
                        if candidate.is_file():
                            return str(candidate)
        executable = shutil.which('bash') if os.name != 'nt' else None
    else:
        raise DeliveryError(f'unsupported delivery shell: {shell}')
    if not executable:
        raise DeliveryError(f'delivery shell unavailable: {shell}')
    return executable


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


def stand_plan(module):
    """Unambiguous stand transport; never guess that a missing command means automatic deploy."""
    import session_settings
    import verification
    mode = repo_setting(module, 'deploy_test_mode')
    command = repo_setting(module, 'deploy_test')
    workflows = verification.workflows(module, 'test')
    if mode is None:
        if workflows:
            mode = 'workflow'
        elif session_settings.is_command(command):
            mode = 'command'
        elif str(command or '').lower().startswith('owner-confirmed'):
            mode = 'owner'
        elif repo_setting(module, 'base_deploys') == 'staging':
            mode = 'automatic'
        else:
            raise DeliveryError('stand transport is ambiguous: set deploy_test_mode: command|workflow|automatic|owner')
    if mode not in ('command', 'workflow', 'automatic', 'owner'):
        raise DeliveryError('invalid deploy_test_mode: command|workflow|automatic|owner')
    if mode == 'command' and (not isinstance(command, str) or not command.strip() or
                              command.lower().startswith('owner-confirmed')):
        raise DeliveryError('deploy_test_mode command needs a nonempty deploy_test command, not owner prose')
    if mode == 'workflow' and not workflows:
        raise DeliveryError('deploy_test_mode workflow needs deploy_workflows.test')
    if mode == 'automatic' and repo_setting(module, 'base_deploys') != 'staging':
        raise DeliveryError('automatic stand delivery needs base_deploys: staging')
    if mode == 'command':
        import shutil
        shell = module.raw.get('shell') or module.repo.raw.get('shell')
        if shell and not shutil.which('pwsh' if shell == 'powershell' else 'bash'):
            raise DeliveryError(f'stand shell unavailable: {shell}')
    return mode, command, workflows


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
    elif trusted and not re.fullmatch(r'D-\d+', str(d['enabled_by'])):
        found.append('orch.yaml: delivery.enabled_by must name an owner decision D-n, not an assumption/question')
    elif trusted and str(d['enabled_by']) not in decision_ids:
        found.append(f'orch.yaml: delivery.enabled_by {d["enabled_by"]} is not in decisions.md')
    if d['prod'] == 'orchestrator' and d['merge'] == 'owner':
        found.append('orch.yaml: delivery.prod: orchestrator needs delivery.merge: orchestrator (a prod release '
                     'without its own merge and stand makes no sense)')
    if d['prod_migrations'] == 'orchestrator' and d['prod'] != 'orchestrator':
        found.append('orch.yaml: delivery.prod_migrations: orchestrator needs delivery.prod: orchestrator')
    if d['release_policy'] is not None and d['release_policy'] not in release.POLICIES:
        found.append('orch.yaml: delivery.release_policy must be batch or per_package')
    if d['release_window']:
        try:
            release.parse_window(d['release_window'])
        except release.WindowError as error:
            found.append(f'orch.yaml: delivery.{error}' if str(error).startswith('release_window') else
                         f'orch.yaml: delivery.release_window: {error}')
    limit = d['max_prod_releases_per_day']
    if limit is not None and not (isinstance(limit, int) and not isinstance(limit, bool) and limit > 0):
        found.append('orch.yaml: delivery.max_prod_releases_per_day must be a positive number')
    for kind, items in (('repo', config.get('repos') or []), ('module', config.get('modules') or [])):
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get('deploy_test_mode') not in (None, 'command', 'workflow', 'automatic', 'owner'):
                found.append(f'orch.yaml: {kind} {item.get("id")}: invalid deploy_test_mode')
            exceptions = item.get('nonblocking_checks')
            if exceptions is not None and (not isinstance(exceptions, list) or any(not isinstance(e, dict) or
                    set(e) != {'name', 'source', 'decision'} or not isinstance(e['name'], str) or not e['name'] or
                    not re.fullmatch(r'D-\d+', str(e['decision'])) or e['decision'] not in decision_ids or not isinstance(e['source'], str) or
                    not re.fullmatch(r'(app|status):[A-Za-z0-9_.-]+', e['source']) for e in exceptions)):
                found.append(f'orch.yaml: {kind} {item.get("id")}: nonblocking_checks needs exact name, source and recorded decision')
            method = item.get('merge_method')
            if method is not None and method not in MERGE_METHODS:
                found.append(f'orch.yaml: {kind} {item.get("id")}: merge_method must be merge, squash or rebase')
            promote = item.get('promote')
            if promote is not None and promote not in release.PROMOTES:
                found.append(f'orch.yaml: {kind} {item.get("id")}: promote must be pr or ff')
            if promote == 'ff' and not item.get('release_clone'):
                found.append(f'orch.yaml: {kind} {item.get("id")}: promote: ff needs release_clone (a clean clone '
                             'the fast-forward push goes from)')
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
                    'number,url,state,headRefOid,mergeable,baseRefName,title,mergeCommit,autoMergeRequest,mergeStateStatus'])


def not_queued(repo_name, number):
    owner, name = repo_name.split('/', 1)
    query = ('query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)'
             '{pullRequest(number:$number){mergeQueueEntry{id}}}}')
    data = gh_json(['api', 'graphql', '-f', 'query=' + query, '-f', 'owner=' + owner,
                    '-f', 'name=' + name, '-F', 'number=' + str(number)])
    try:
        if data.get('errors'):
            return False
        return data['data']['repository']['pullRequest']['mergeQueueEntry'] is None
    except (KeyError, TypeError, AttributeError):
        return False


def pr_checks(repo_name, number, exceptions=None, decisions=()):
    """(verdict, detail) of the PR's checks: all passed or skipped is green."""
    result = subprocess.run(['gh', 'pr', 'checks', str(number), '--repo', repo_name, '--json', 'name,bucket'],
                            encoding='utf-8', errors='replace', capture_output=True)
    if result.returncode == 1 and not result.stdout.strip() and re.fullmatch(
            r'no checks reported on the .+ branch\s*', result.stderr.strip(), re.I):
        return True, 'no checks reported'
    if result.stderr.strip():
        return False, result.stderr.strip()
    if result.returncode not in (0, 1, 8) or (result.returncode and not result.stdout.strip()):
        return False, (result.stderr.strip() or 'cannot read PR checks')
    try:
        checks = json.loads(result.stdout)
    except ValueError:
        return False, (result.stderr or 'gh pr checks failed').strip().split('\n')[0]
    if not isinstance(checks, list) or any(not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'] or
            c.get('bucket') not in ('pass', 'skipping', 'fail', 'pending', 'cancel') for c in checks):
        return False, 'incomplete PR checks response'
    if result.returncode and not checks:
        return False, 'checks command failed without verified check results'
    if result.returncode == 1 and not any(c['bucket'] in ('fail', 'cancel') for c in checks) or \
            result.returncode == 8 and not any(c['bucket'] == 'pending' for c in checks):
        return False, 'checks command exit status contradicts its response'
    ignored = []
    if exceptions:
        try:
            if not isinstance(exceptions, list) or any(not isinstance(e, dict) or
                    set(e) != {'name', 'source', 'decision'} or not re.fullmatch(r'D-\d+', str(e['decision'])) or e['decision'] not in decisions or
                    not e['name'] or not re.fullmatch(r'(app|status):[A-Za-z0-9_.-]+', e['source']) for e in exceptions):
                raise DeliveryError('nonblocking_checks needs exact name, app:<slug>|status:<login>, recorded decision')
            required = subprocess.run(['gh', 'pr', 'checks', str(number), '--repo', repo_name, '--required',
                                       '--json', 'name,bucket'], encoding='utf-8', errors='replace', capture_output=True)
            if required.returncode == 1 and not required.stdout.strip() and re.fullmatch(
                    r'no required checks reported on the .+ branch\s*', required.stderr.strip(), re.I):
                required_names = set()
            else:
                if required.stderr.strip():
                    raise DeliveryError(required.stderr.strip())
                required_data = json.loads(required.stdout)
                if required.returncode not in (0, 1, 8) or not isinstance(required_data, list) or any(
                        not isinstance(c, dict) or not isinstance(c.get('name'), str) or not c['name'] or
                        c.get('bucket') not in ('pass', 'skipping', 'fail', 'pending', 'cancel') for c in required_data):
                    raise DeliveryError('required checks could not be established')
                if required.returncode == 1 and not any(c['bucket'] in ('fail', 'cancel') for c in required_data) or \
                        required.returncode == 8 and not any(c['bucket'] == 'pending' for c in required_data):
                    raise DeliveryError('required checks exit status contradicts its response')
                required_names = {c['name'] for c in required_data}
                missing = required_names - {c['name'] for c in checks}
                if missing:
                    raise DeliveryError('required checks missing from response: ' + ', '.join(sorted(missing)))
            head = pr_facts(repo_name, str(number)).get('headRefOid')
            if not re.fullmatch(r'[0-9a-f]{40}', head or ''):
                raise DeliveryError('cannot establish check source revision')
            sources = {}
            for endpoint, field in (('check-runs', 'check_runs'), ('statuses', None)):
                for page in range(1, 21):
                    data = gh_json(['api', f'repos/{repo_name}/commits/{head}/{endpoint}?per_page=100&page={page}'])
                    data = data.get(field) if field and isinstance(data, dict) else data
                    if not isinstance(data, list):
                        raise DeliveryError('incomplete check sources response')
                    for c in data:
                        name = c.get('name') if field else c.get('context')
                        source = ('app:' + str((c.get('app') or {}).get('slug') or '')) if field else (
                            'status:' + str((c.get('creator') or {}).get('login') or ''))
                        sources.setdefault(name, set()).add(source)
                    if len(data) < 100:
                        break
                else:
                    raise DeliveryError('check sources pagination incomplete')
            retained = []
            for c in checks:
                match = next((e for e in exceptions if e['name'] == c['name'] and
                              sources.get(c['name']) == {e['source']}), None)
                if match and c['name'] not in required_names:
                    ignored.append(f'{c["name"]} {match["source"]}: {c["bucket"]} (nonblocking by {match["decision"]})')
                else:
                    retained.append(c)
            checks = retained
        except (DeliveryError, ValueError, KeyError, TypeError, AttributeError) as error:
            return False, f'cannot apply CI exception: {error}'
    bad = [c for c in checks if str(c.get('bucket', '')).lower() not in PASSING]
    if bad:
        return False, '; '.join([', '.join(f'{c.get("name")}: {c.get("bucket")}' for c in bad[:5]), *ignored])
    return True, '; '.join([f'{len(checks)} checks passed' if checks else 'no blocking checks', *ignored])


def merge(repo_name, number, method, delete_branch, expected_head=None):
    if method not in MERGE_METHODS:  # never --admin or any other flag from a mistyped orch.yaml
        raise DeliveryError(f'merge_method {method!r} is not one of {", ".join(MERGE_METHODS)}')
    args = ['gh', 'pr', 'merge', str(number), '--repo', repo_name, f'--{method}']
    if not re.fullmatch(r'[0-9a-f]{40}', expected_head or ''):
        raise DeliveryError('merge requires the full accepted PR head SHA')
    args += ['--match-head-commit', expected_head]
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


def run_command(command, cwd, timeout, shell='bash'):
    """(ok, detail) of a configured command (deploy_test, rollback_test); stdin is closed, so a script that
    asks for a TTY confirmation fails instead of waiting."""
    try:
        executable = shell_program(shell)
        argv = ([executable, '-NoProfile', '-NonInteractive', '-Command',
                 "$ErrorActionPreference='Stop'; " + command + '; if ($LASTEXITCODE) { exit $LASTEXITCODE }']
                if shell == 'powershell' else [executable, '-c', command])
        result = subprocess.run(argv, cwd=cwd, encoding='utf-8', errors='replace',
                                capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f'`{command}` timed out after {timeout} s'
    except OSError as error:
        return False, f'cannot start {shell}: {error}'
    except DeliveryError as error:
        return False, str(error)
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
