"""Opt-in local Codex/Claude coordination. Planning is read-only; watcher never dispatches.

Markdown owns WP state. This registry owns routing, reservations and delivery only.
All writes use the existing transaction journal; external observations happen first.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

import claude_adapter
import codex_adapter
import codex_transport
import runtime_commands as runtime
import state_io
import streams


class AutonomyError(streams.StreamError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def registry(ws):
    path = ws.root / 'orchestration/sessions.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (ValueError, OSError) as error:
        raise AutonomyError(f'cannot read session registry: {error}') from error
    if data.get('version', 1) not in (1, 2):
        raise AutonomyError('unsupported session registry version')
    data.setdefault('sessions', {})  # Backwards-compatible WP -> session index.
    data.setdefault('outbox', {})
    data.setdefault('instances', {})
    data.setdefault('assignments', {})
    data.setdefault('revision', 0)
    data.setdefault('generation', 0)
    data.setdefault('autonomy', {'enabled': False, 'session_reuse': 'auto',
                                 'interval_seconds': 600, 'max_parallel_sessions': 2})
    for wp, old in data['sessions'].items():
        key = old['client'] + ':' + old['thread_id']
        if key not in data['instances']:
            data['instances'][key] = {**old, 'key': key, 'history': [wp], 'assignment_id': None,
                                       'confirmation': None}
    data['version'] = 2  # Pure in-memory migration; persisted only by a write command.
    return path, data


def persist(ws, data):
    data['revision'] += 1
    runtime.save(ws.root / 'orchestration/sessions.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def endpoint(ws):
    return (ws.config.get('codex') or {}).get('remote')


def is_claude(ws):
    return ws.config.get('client', 'claude') == 'claude'


def adapter(ws):
    return claude_adapter if is_claude(ws) else codex_adapter


def observe_thread(ws, thread, history=False, rows=None):
    if is_claude(ws):
        return claude_adapter.read_session(thread, rows)
    return codex_transport.read_thread(thread, include_turns=history, shared=True, remote=endpoint(ws))['thread']


def process_identity(pid):
    if not pid or int(pid) <= 0:
        raise AutonomyError('a positive client/server PID is required')
    pid = int(pid)
    if sys.platform == 'darwin':
        import ctypes
        # sys/proc_info.h: proc_bsdinfo, PROC_PIDTBSDINFO. Microseconds avoid
        # treating two incarnations of a reused PID in one second as identical.
        class BSDInfo(ctypes.Structure):
            _fields_ = [('prefix', ctypes.c_byte * 120), ('seconds', ctypes.c_uint64), ('microseconds', ctypes.c_uint64)]
        info = BSDInfo()
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        if lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != ctypes.sizeof(info):
            code = ctypes.get_errno()
            raise AutonomyError(f'process {pid} is not observable; reconfirm after recovery') from OSError(code, os.strerror(code))
        return {'host': socket.gethostname(), 'pid': pid, 'started': f'{info.seconds}.{info.microseconds:06d}'}
    if sys.platform.startswith('linux'):
        try:
            fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            return {'host': socket.gethostname(), 'pid': pid, 'started': boot + ':' + fields[19],
                    'pid_namespace': os.readlink('/proc/self/ns/pid')}
        except (OSError, IndexError) as error:
            raise AutonomyError(f'process {pid} is not observable; reconfirm after recovery') from error
    if os.name == 'nt':
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            '$ErrorActionPreference = "Stop"; '
                            f'$p = Get-CimInstance Win32_Process -Filter "ProcessId = {pid}"; '
                            'if ($null -eq $p) { "ABSENT" } else { $p.CreationDate.ToUniversalTime().ToString("o") }'],
                           capture_output=True, text=True, timeout=10)
    else:
        raise AutonomyError('precise process identity is unsupported on this platform; autonomy is unavailable')
    if r.returncode or not r.stdout.strip():
        raise AutonomyError(f'process {pid} is not observable; reconfirm after recovery')
    if r.stdout.strip() == 'ABSENT':
        raise AutonomyError(f'process {pid} has exited') from ProcessLookupError(errno.ESRCH, 'process absent')
    return {'host': socket.gethostname(), 'pid': pid, 'started': r.stdout.strip()}


def process_observation(proof):
    """Only positively observed absence/replacement proves the confirmed writer exited.

    ENOENT in a hidden PID namespace, EACCES and observation failures are unknown.
    Old Linux confirmations lack the namespace proof and require owner reattachment.
    """
    try:
        if not isinstance(proof, dict) or proof.get('host') != socket.gethostname():
            raise AutonomyError('missing confirmation or different host')
        if type(proof.get('pid')) is not int or proof['pid'] <= 0 or not isinstance(proof.get('started'), str):
            raise AutonomyError('invalid process confirmation')
        if sys.platform.startswith('linux'):
            if proof.get('pid_namespace') != os.readlink('/proc/self/ns/pid'):
                raise AutonomyError('PID namespace is unconfirmed or changed')
            if proof['started'].split(':', 1)[0] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
                raise AutonomyError('host boot changed; reconfirm after recovery')
        try:
            current = process_identity(proof['pid'])
        except AutonomyError as error:
            cause = error.__cause__
            if not isinstance(cause, OSError) or cause.errno not in (errno.ENOENT, errno.ESRCH):
                raise
            if os.name != 'nt':
                try:
                    os.kill(proof['pid'], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AutonomyError('PID exists but identity is unavailable')
            return {'state': 'exited'}
        return {'state': 'live' if current == proof else 'exited'}
    except (AutonomyError, OSError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        return {'state': 'unavailable', 'reason': str(error)}


def parent_pid(pid):
    if sys.platform.startswith('linux'):
        return int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
    if os.name == 'nt':
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            f'(Get-CimInstance Win32_Process -Filter "ProcessId = {pid}").ParentProcessId'],
                           capture_output=True, text=True, timeout=10)
    else:
        r = subprocess.run(['ps', '-o', 'ppid=', '-p', str(pid)], capture_output=True, text=True, timeout=10)
    return int(r.stdout.strip() or 0)


def ancestors():
    """PIDs above this process; the Claude session that runs a Bash command is one of them."""
    found, pid = [], os.getpid()
    for _ in range(64):
        try:
            pid = parent_pid(pid)
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            break
        if pid <= 1 or pid in found:
            break
        found.append(pid)
    return found


def configuration(ws, instance):
    directory = Path(instance['worktree'])
    if instance.get('client') == 'claude':
        paths = claude_adapter.config_files(ws, instance['module'], directory)
        return digest({'config': ws.config, 'files': {str(p): state_io.digest(p) for p in paths}})
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    paths = [home / 'config.toml', directory / '.codex/config.toml',
             directory / '.codex/rules/pepper-orchestrator.rules',
             codex_adapter.settings_path(ws.root, instance['module'])]
    return digest({'config': ws.config, 'files': {str(p): state_io.digest(p) for p in paths},
                   'endpoint': endpoint(ws)})


def thread_identity(thread):
    return {k: thread.get(k) for k in ('id', 'createdAt', 'model', 'reasoningEffort')}


def confirm(ws, instance, pid, evidence, thread):
    if not evidence:
        raise AutonomyError('confirmation requires concrete process/configuration evidence')
    if not pid:
        raise AutonomyError('confirmation requires --pid of the live client/server process')
    if not thread.get('cwd') or Path(thread['cwd']).resolve() != Path(instance['worktree']).resolve():
        raise AutonomyError('thread cwd does not match the registered worktree')
    if thread.get('pid') and int(thread['pid']) != int(pid):
        # Claude reports the PID of the live session: the confirmed process must be that one.
        raise AutonomyError('PID does not belong to the live session')
    return {'process': process_identity(pid), 'configuration': configuration(ws, instance),
            'thread': thread_identity(thread), 'evidence': evidence, 'confirmed_at': time.time()}


def compatible(ws, instance, thread, meta):
    reasons = []
    proof = instance.get('confirmation')
    if not proof:
        return ['session configuration/process has not been confirmed']
    try:
        if process_identity(proof['process']['pid']) != proof['process']:
            reasons.append('client process changed; reconfirm session')
    except (AutonomyError, OSError, subprocess.TimeoutExpired) as error:
        reasons.append(str(error))
    if configuration(ws, instance) != proof['configuration'] or thread_identity(thread) != proof['thread']:
        reasons.append('configuration or live thread identity changed; reconfirm session')
    if not thread.get('cwd'):
        reasons.append('session is not live on this host')
    elif Path(thread['cwd']).resolve() != Path(instance['worktree']).resolve():
        reasons.append('thread cwd changed')
    status = thread.get('status') or {}
    if status.get('type') != 'idle' or status.get('activeFlags'):
        reasons.append('session is ' + status.get('type', 'unknown') + ': ' + ', '.join(status.get('activeFlags', [])))
    if instance.get('state') != 'running':
        reasons.append('registered session is stopped')
    if instance.get('context_state') not in (None, 'ready'):
        reasons.append('compaction outcome needs explicit reconciliation/confirmation')
    if instance.get('client') == 'claude':
        if thread.get('pid') != proof['process']['pid']:
            reasons.append('live session PID changed; reconfirm session')
        # Model/effort are not observable for Claude: compare the owner-confirmed launch values.
        claimed = proof.get('claimed') or {}
        for field in ('model', 'effort'):
            if meta.get(field) and meta[field] != claimed.get(field):
                reasons.append('required ' + field + ' is not confirmed for this Claude session')
        return reasons
    for field, actual in [('model', 'model'), ('effort', 'reasoningEffort')]:
        if meta.get(field) and meta[field] != thread.get(actual):
            reasons.append('required ' + field + ' does not match live session')
    return reasons


def owner(data, thread, generation):
    codex_transport.check_native_operation()
    current = data.get('coordinator') or {}
    if not thread or current.get('thread_id') != thread or current.get('generation') != generation or current.get('released'):
        raise AutonomyError('coordinator ownership/generation mismatch; claim or recover ownership first')
    if process_identity(current['process']['pid']) != current['process']:
        raise AutonomyError('coordinator process changed; recover ownership explicitly')
    return current


def require_enabled(ws, data):
    ws.require_open('autonomous dispatch')
    if ws.config.get('client', 'claude') not in ('codex', 'claude') or not data['autonomy']['enabled']:
        raise AutonomyError('autonomy is paused or disabled')


def pr_url(row):
    found = re.search(r'https://[^\s)]+/pull/\d+', row.get('pr', ''))
    return found.group(0) if found else None


def git_snapshot(directory):
    def read(*args):
        result = streams.git(directory, *args)
        if result.returncode:
            raise AutonomyError('git observation failed: ' + ' '.join(args) + ': ' + result.stderr.strip())
        return result.stdout.strip()
    return {'branch': read('branch', '--show-current'), 'head': read('rev-parse', 'HEAD'),
            'dirty': read('status', '--porcelain', '--untracked-files=normal')}


def pr_observation(url):
    # Read-only, bounded GitHub observation. Errors are not absence or success.
    r = subprocess.run(['gh', 'pr', 'view', url, '--json',
                        'url,state,headRefOid,mergeCommit,baseRefName,statusCheckRollup'],
                       capture_output=True, text=True, encoding='utf-8', timeout=30)
    if r.returncode or r.stderr.strip():
        raise AutonomyError('PR observation failed: ' + (r.stderr.strip() or str(r.returncode)))
    value = json.loads(r.stdout)
    if not isinstance(value, dict) or not value.get('headRefOid') or value.get('state') not in ('OPEN', 'CLOSED', 'MERGED'):
        raise AutonomyError('incomplete PR observation')
    return value


def observations(ws, data):
    result = {'sessions': {}, 'prs': {}, 'errors': []}
    client = ws.config.get('client', 'claude')
    rows = None
    if is_claude(ws) and any(i['client'] == 'claude' and i.get('state') != 'stopped' for i in data['instances'].values()):
        try:
            rows = claude_adapter.agents()  # One snapshot per tick for every session.
        except claude_adapter.ClaudeError as error:
            rows = error
    for key, instance in sorted(data['instances'].items()):
        if instance['client'] != client or instance.get('state') == 'stopped':
            continue
        try:
            if isinstance(rows, Exception):
                raise rows
            extra = {'rows': rows} if rows is not None else {}
            thread = observe_thread(ws, instance['thread_id'], history=True, **extra)
            result['sessions'][key] = {'thread': thread, 'git': git_snapshot(Path(instance['worktree']))}
        except (OSError, ValueError, subprocess.TimeoutExpired, codex_transport.TransportError,
                claude_adapter.ClaudeError, AutonomyError) as error:
            result['sessions'][key] = {'error': str(error)}
    relevant = {i.get('wp') for i in data['instances'].values() if i.get('state') == 'running'}
    for wp, row in ws.wp_rows().items():
        if wp not in relevant and row['status'] not in streams.ACTIVE + ('VERIFYING', 'DEPLOYED_TEST'):
            continue
        url = pr_url(row)
        if url:
            try:
                result['prs'][wp] = pr_observation(url)
            except (OSError, ValueError, subprocess.TimeoutExpired, AutonomyError) as error:
                result['prs'][wp] = {'error': str(error)}
    return result


def finished(ws, instance, observed):
    """Evidence that this writer can leave its old branch, including squash merges."""
    old = instance.get('wp')
    if not old:
        return []
    row = ws.wp_rows().get(old, {})
    if row.get('status') not in streams.SATISFIED:
        return [f'previous {old} is {row.get("status", "unknown")}; confirmed merge is required']
    if any(lock['holder'] == old for lock in runtime.api().locks(ws)):
        return [f'previous {old} still holds locks or mandatory integration work']
    pr = observed['prs'].get(old, {})
    if pr.get('state') != 'MERGED' or not (pr.get('mergeCommit') or {}).get('oid'):
        return [f'previous {old} merge is unconfirmed: ' + pr.get('error', 'missing merged PR facts')]
    accepted, _ = runtime.api().accepted_revision(ws, old)
    fact = observed['sessions'].get(instance['key'], {})
    if not accepted or len(accepted) != 40 or accepted != pr.get('headRefOid') or accepted != fact.get('git', {}).get('head'):
        return [f'previous {old} local HEAD does not match its full accepted/merged PR head']
    return []


def candidates(ws, module, meta, data, observed):
    matches, rejected = [], {}
    for key, instance in sorted(data['instances'].items()):
        if instance['client'] != ws.config.get('client', 'claude') or instance['module'] != module.id:
            continue
        fact = observed['sessions'].get(key, {})
        reasons = [fact['error']] if fact.get('error') else []
        if not fact or 'thread' not in fact:
            reasons.append('live session is not observable')
        else:
            reasons += compatible(ws, instance, fact['thread'], meta)
            directory = Path(instance['worktree'])
            if streams.common_dir(directory) != streams.common_dir(module.repo.local):
                reasons.append('worktree belongs to another repository')
            if not streams.is_linked_worktree(directory):
                reasons.append('reuse requires a separate linked worktree')
            if is_claude(ws):
                if not claude_adapter.settings_current(ws, module):
                    reasons.append('module settings file is missing or older than orch.yaml; regenerate and reconfirm')
            elif not codex_adapter.reuse_rules_ok(directory):
                reasons.append('native rules require owner preparation/reconfirmation')
            if fact['git']['dirty']:
                reasons.append('worktree is dirty')
            if fact['git']['branch'] != instance.get('branch'):
                reasons.append('worktree branch changed outside the assignment protocol')
            reasons += finished(ws, instance, observed)
            for other_key, other in data['instances'].items():
                if other_key != key and other.get('state') == 'running' and (
                        Path(other['worktree']).resolve() == directory.resolve() or
                        (other.get('branch') == fact['git']['branch'] and streams.common_dir(Path(other['worktree'])) == streams.common_dir(directory))):
                    reasons.append('another registered writer owns this worktree/branch')
            aid = instance.get('assignment_id')
            if aid and data['assignments'][aid]['state'] in ('reserved', 'sending', 'queued', 'outcome_unknown'):
                reasons.append('previous assignment has not been reconciled/started')
            if any(e.get('thread_id') == instance['thread_id'] and not e.get('assignment_id') and
                   (e.get('sending') or e.get('outcome_unknown')) for e in data['outbox'].values()):
                reasons.append('legacy outbox has an unknown send; reconcile it before reuse')
        if reasons:
            rejected[key] = reasons
        else:
            matches.append(key)
    return matches, rejected


def active_slots(ws, data, observed):
    active = {wp for wp, row in ws.wp_rows().items() if row['status'] in streams.ACTIVE}
    for assignment in data['assignments'].values():
        if assignment['state'] in ('completed', 'cancelled'):
            continue
        instance = data['instances'][assignment['session']]
        if assignment['state'] == 'started' and not finished(ws, instance, observed):
            continue
        active.add(assignment['wp'])
    return len(active)


def wave_conflict(ws, chosen, wp):
    _, module, meta = runtime.api().wp_context(ws, wp)
    wanted, _ = runtime.api().lock_names(module.repo, meta)
    for old in chosen:
        _, other, ometa = runtime.api().wp_context(ws, old)
        if module.repo.key != other.repo.key:
            continue
        if module.id == other.id or not module.worktree_mode or not other.worktree_mode:
            return f'conflicts with selected {old} in the same stream/repository'
        if streams.overlap_outside_shared(meta['paths'], ometa['paths'], module.repo.shared_paths):
            return f'paths conflict with selected {old}'
        names, _ = runtime.api().lock_names(other.repo, ometa)
        if any(streams.patterns_overlap(a, b) for a in wanted for b in names):
            return f'locks conflict with selected {old}'
    return None


def dependency_cycles(ws):
    graph = {}
    rows = ws.wp_rows()
    for wp, row in rows.items():
        if row['status'] not in streams.SATISFIED and not row['status'].startswith('CANCELLED'):
            graph[wp] = [d for d in runtime.api().wp_context(ws, wp)[2]['depends']
                         if rows.get(d, {}).get('status') not in streams.SATISFIED]
    cycles, visiting, visited = set(), [], set()
    def visit(wp):
        if wp in visiting:
            cycles.add(tuple(sorted(visiting[visiting.index(wp):])))
            return
        if wp in visited:
            return
        visiting.append(wp)
        for dep in graph.get(wp, []):
            if dep in graph:
                visit(dep)
        visiting.pop(); visited.add(wp)
    for wp in sorted(graph):
        visit(wp)
    return [list(c) for c in sorted(cycles)]


def next_actions(ws, observed=None):
    _, data = registry(ws)
    version = runtime.state_version(ws)
    observed = observations(ws, data) if observed is None else observed
    settings = data['autonomy']
    actions, waiting, selected, used = [], [], [], set()
    capacity = max(0, settings['max_parallel_sessions'] - active_slots(ws, data, observed))
    for wp, row in sorted(ws.wp_rows().items()):
        status = row['status']
        if status == 'READY':
            problems, _, _, _, module = runtime.api().dispatch_problems(ws, wp)
            _, _, meta = runtime.api().wp_context(ws, wp)
            conflict = wave_conflict(ws, selected, wp)
            if conflict:
                problems.append(conflict)
            if capacity <= 0:
                problems.append('parallel session limit reached (active and reserved assignments)')
            if ws.closed or not settings['enabled']:
                problems.append('autonomy is paused/disabled or program is closed')
            available, rejected = candidates(ws, module, meta, data, observed)
            available = [k for k in available if k not in used]
            for key in rejected:
                fact = observed['sessions'].get(key, {})
                state = fact.get('thread', {}).get('status', {})
                if fact.get('error') or state.get('type') in ('active', 'systemError'):
                    problems.append('existing session must be observed/reconciled before another writer: ' + key)
            if problems:
                waiting.append({'wp': wp, 'reasons': problems, 'sessions': rejected})
                continue
            if not available or settings['session_reuse'] != 'auto':
                actions.append({'kind': 'owner', 'wp': wp, 'reason': 'new terminal required' if not available else 'session_reuse=' + settings['session_reuse'],
                                'launch': adapter(ws).launch(ws, module, wp, meta), 'sessions': rejected,
                                'candidate': available[0] if available else None})
                continue
            key = available[0]
            actions.append({'kind': 'dispatch', 'wp': wp, 'session': key})
            selected.append(wp); used.add(key); capacity -= 1
        elif status in ('REVIEW', 'ACCEPTED', 'MERGED', 'DEPLOYED_TEST', 'VERIFYING', 'VERIFIED_TEST', 'REVISE'):
            kind = {'REVIEW': 'review', 'REVISE': 'reconcile', 'ACCEPTED': 'deliver',
                    'MERGED': 'verify', 'DEPLOYED_TEST': 'verify', 'VERIFYING': 'verify', 'VERIFIED_TEST': 'release'}[status]
            actions.append({'kind': kind, 'wp': wp, 'required': 'existing lifecycle gates and delivery delegation',
                            'pr': observed['prs'].get(wp)})
    for key, fact in observed['sessions'].items():
        if fact.get('error'):
            waiting.append({'session': key, 'kind': 'observation_error', 'reasons': [fact['error']]})
            continue
        instance = data['instances'][key]
        assignment = data['assignments'].get(instance.get('assignment_id'), {})
        flags = fact['thread'].get('status', {}).get('activeFlags', [])
        if flags:
            actions.append({'kind': 'owner', 'session': key, 'wp': assignment.get('wp') or instance.get('wp'),
                            'reason': 'session requires user input/approval', 'flags': flags})
        if assignment.get('state') in ('sending', 'queued', 'outcome_unknown') or (
                assignment.get('state') == 'started' and fact['thread'].get('status', {}).get('type') != 'active'
                and ws.wp_rows().get(instance.get('wp'), {}).get('status') in ('DISPATCHING', 'IN_PROGRESS')):
            actions.append({'kind': 'reconcile', 'wp': assignment.get('wp') or instance.get('wp'), 'session': key,
                            'assignment_id': assignment.get('id'), 'state': assignment.get('state')})
    if ws.has_table(ws.status, 'owner'):
        for item in ws.table(ws.status, 'owner')[2]:
            if item['closed'] in ('', '—', '-'):
                actions.append({'kind': 'owner', 'item': item['id'], 'reason': item['text']})
    cycles = dependency_cycles(ws)
    for cycle in cycles:
        actions.append({'kind': 'owner', 'reason': 'dependency cycle', 'packages': cycle})
    rows = ws.wp_rows()
    if rows and not actions and all(r['status'] in ('DONE', 'PROD') or r['status'].startswith('CANCELLED') for r in rows.values()):
        actions.append({'kind': 'owner', 'reason': 'work packages complete; verify program goal and run close --check'})
    # Only meaningful external fields; volatile timestamps and runtime clocks never
    # manufacture a change. Git HEAD/dirty, PR checks and turn completion do.
    external = {'prs': observed['prs'], 'sessions': {k: {'error': f.get('error'), 'git': f.get('git'),
                'thread': {n: f.get('thread', {}).get(n) for n in ('id', 'createdAt', 'model', 'reasoningEffort', 'status', 'turns')}}
                for k, f in observed['sessions'].items()}}
    return {'actions': actions, 'waiting': waiting, 'fingerprint': digest([version, external, actions, waiting]),
            'situation': 'paused' if not settings['enabled'] or ws.closed else 'deadlock' if cycles else
                         'observation_error' if any(w.get('kind') == 'observation_error' for w in waiting) else
                         'actionable' if actions else 'waiting' if waiting else 'quiet',
            'state_version': version, 'registry_revision': data['revision'],
            'next_check_seconds': settings['interval_seconds'], 'enabled': settings['enabled'] and not ws.closed,
            'observations': observed}


def public_plan(plan):
    return {k: v for k, v in plan.items() if k != 'observations'}


def attach(ws, args):
    row, module, meta = runtime.api().wp_context(ws, args.wp)
    directory = Path(args.worktree).expanduser().resolve()
    if streams.common_dir(directory) != streams.common_dir(module.repo.local) or streams.current_branch(directory) != meta['branch']:
        raise AutonomyError('session must belong to this WP repository and branch')
    thread = observe_thread(ws, args.thread)
    client = 'claude' if is_claude(ws) else 'codex'
    instance = {'key': client + ':' + args.thread, 'thread_id': args.thread, 'client': client,
                'program': ws.config['program'], 'module': module.id, 'wp': args.wp,
                'worktree': str(directory), 'branch': meta['branch'], 'state': 'running',
                'history': [args.wp], 'assignment_id': None}
    if client == 'claude':
        if thread['status']['type'] == 'notLoaded':
            raise AutonomyError('Claude session is not live on this host (claude agents --json)')
        if not thread.get('name'):
            raise AutonomyError('Claude session has no name; /rename it so SendMessage can address it')
        claude_adapter.recipient(args.thread, thread['name'])
        instance['name'] = thread['name']
    instance['confirmation'] = confirm(ws, instance, args.pid, args.evidence, thread)
    if client == 'claude':
        # Owner-confirmed launch values: Claude does not expose model/effort externally.
        instance['confirmation']['claimed'] = {'model': getattr(args, 'model', None), 'effort': getattr(args, 'effort', None)}
    with state_io.transaction(ws.root):
        _, data = registry(ws)
        if streams.current_branch(directory) != meta['branch']:
            raise AutonomyError('worktree branch changed during attachment; inspect before retry')
        for key, old in data['instances'].items():
            if key != instance['key'] and old.get('state') == 'running' and (
                    old.get('wp') == args.wp or Path(old['worktree']).resolve() == directory):
                raise AutonomyError('another registered writer must be stopped/reconciled before attach')
        old = data['instances'].get(instance['key'])
        if old:
            if old.get('assignment_id') and data['assignments'][old['assignment_id']]['state'] != 'completed':
                if old['wp'] != args.wp:
                    raise AutonomyError('cannot change an active assignment through attach')
            instance.update(history=old['history'], assignment_id=old.get('assignment_id'))
        data['instances'][instance['key']] = instance
        data['sessions'][args.wp] = instance.copy()
        persist(ws, data)
    return instance


def reserve(ws, wp, thread, generation, plan=None):
    plan = next_actions(ws) if plan is None else plan
    chosen = next((a for a in plan['actions'] if a.get('wp') == wp and a['kind'] == 'dispatch'), None)
    if not chosen:
        return {'result': 'blocked', 'wp': wp, 'plan': public_plan(plan)}
    _, module, meta = runtime.api().wp_context(ws, wp)
    if is_claude(ws):
        claude_adapter.capabilities()
    else:
        runtime.check_capabilities(ws)
    with state_io.transaction(ws.root):
        current = runtime.api().Workspace(ws.root)
        _, data = registry(current)
        require_enabled(current, data); owner(data, thread, generation)
        if any(a['generation'] != generation and a['state'] in ('reserved', 'sending', 'queued', 'outcome_unknown')
               for a in data['assignments'].values()):
            raise AutonomyError('reconcile outstanding assignments of the previous coordinator first')
        if runtime.state_version(current) != plan['state_version'] or data['revision'] != plan['registry_revision']:
            raise AutonomyError('state changed during dispatch preflight; recompute next')
        problems, wanted, _, _, _ = runtime.api().dispatch_problems(current, wp)
        if problems:
            raise AutonomyError('; '.join(problems))
        instance = data['instances'][chosen['session']]
        if git_snapshot(Path(instance['worktree'])) != plan['observations']['sessions'][instance['key']]['git']:
            raise AutonomyError('worktree changed during preflight')
        aid = instance.get('assignment_id')
        if aid:
            if data['assignments'][aid]['state'] != 'started' or finished(current, instance, plan['observations']):
                raise AutonomyError('previous assignment must be reconciled before reuse')
            data['assignments'][aid]['state'] = 'completed'
        for lock in wanted:
            if runtime.api().acquire(current, module.repo, lock, wp, 'autonomous dispatch'):
                raise AutonomyError('lock changed during dispatch')
        aid = str(uuid.uuid4())
        assignment = {'id': aid, 'wp': wp, 'session': instance['key'], 'state': 'reserved',
                      'generation': generation, 'coordinator': thread, 'branch': meta['branch'],
                      'previous_branch': instance['branch'], 'worktree': instance['worktree'],
                      'previous_head': plan['observations']['sessions'][instance['key']]['git']['head'],
                      'created_at': time.time(), 'locks': wanted}
        instance.update(assignment_id=aid)
        data['assignments'][aid] = assignment
        task = task_message(current, assignment, module)
        data['outbox'][aid] = {'assignment_id': aid, 'wp': wp, 'thread_id': instance['thread_id'],
                                'message': task, 'delivered': False, 'sending': False}
        runtime.api().cmd_set(argparse.Namespace(workspace=str(ws.root), wp=wp, column='status',
                                                text='DISPATCHING', quiet=True, evidence='assignment ' + aid))
        persist(current, data)
    return {'result': 'assigned', 'assignment_id': aid, 'wp': wp, 'session': instance['key']}


def task_message(ws, assignment, module):
    wp = assignment['wp']; path = ws.wp_path(ws.wp_rows()[wp]['wp']).resolve()
    if not is_claude(ws) and codex_transport.private_mode():
        return (f'[{ws.tag}] TASK {wp} assignment_id={assignment["id"]}\n'
            f'Read the full package {path}. This is private owner mode. '
            'Call pepper_orchestrator with operation=prepare and assignment=' + assignment['id'] + '. '
            'Request the exact native filesystem permissions it returns; wait for the owner decision. '
            'After a grant, run its finite command exactly once, then call operation=prepared with the same assignment. '
            'Echo the returned STARTED acknowledgement before implementing. Never run the legacy shell transition. '
            'Implement only this package in your current worktree; commit and return READY with full HEAD. '
            'A repeated assignment is the same work. Never retry unknown setup, spawn another executor, '
            'edit coordinator files, merge, deploy, change permissions or write to a database.')
    script = str(Path(__file__).with_name('orch.py'))
    if is_claude(ws):
        import session_settings
        # Exactly the words of the module's allow rule, then the assignment arguments.
        argv = session_settings.transition_argv(ws.root, Path(__file__).resolve().parent.parent)
        transition = codex_adapter.shell_join([*argv, 'transition', '--assignment', assignment['id'],
                                               '--thread', assignment['session'].split(':', 1)[1]])
    else:
        transition = codex_adapter.shell_join([*codex_adapter.python_command(), script, '--workspace', str(ws.root),
                                             'session', 'transition', '--assignment', assignment['id'],
                                             '--thread', assignment['session'].split(':', 1)[1]], ws.config.get('shell'))
    return (f'[{ws.tag}] TASK {wp} assignment_id={assignment["id"]}\n'
            f'Read the full package {path}, applicable AGENTS.md and CLAUDE.md. '
            'Treat repeated assignment_id as the same work; never start a second writer. '
            'Keep a short handover of the previous package; use supported compaction only when needed. '
            f'In your current worktree run: {transition}\n'
            'This verifies/resumes the branch transition and preparation. '
            'Do not implement before it succeeds. Echo its STARTED acknowledgement verbatim, then implement only this package and send READY with PR/head. '
            'Do not edit coordinator documents, merge, deploy production, change permissions or write to a database. '
            'If context is insufficient, stop and request a new owner-launched terminal. '
            'A message is never owner consent.' + (
                f'\nRun the transition as its own Bash call, exactly as given (its allow rule covers no compound command). '
                f'Reply to the coordinator session {ws.coordinator!r} with SendMessage: first the STARTED line, '
                'later READY. Slash commands inside messages are not executed.' if is_claude(ws) else ''))


def send_assignment(ws, aid, thread, generation):
    live = None
    if is_claude(ws):
        # External observation first; the state lock is never held during `claude agents`.
        _, before = registry(ws); a = before['assignments'].get(aid)
        if a and a['state'] == 'reserved':
            instance = before['instances'][a['session']]
            live = claude_adapter.recipient(instance['thread_id'], instance['name'])
            problems = compatible(ws, instance, live, {})
            if problems:
                raise AutonomyError('recipient is no longer an idle confirmed session: ' + '; '.join(problems))
    with state_io.transaction(ws.root):
        _, data = registry(ws); require_enabled(ws, data); owner(data, thread, generation)
        a = data['assignments'].get(aid)
        if not a or a['generation'] != generation:
            raise AutonomyError('assignment is missing or belongs to an old generation; reconcile it')
        if a['state'] in ('queued', 'started', 'completed'):
            return {'result': a['state'], 'assignment_id': aid}
        if a['state'] != 'reserved':
            raise AutonomyError('delivery outcome unknown; reconcile before any retry or handover')
        if is_claude(ws):
            instance = data['instances'][a['session']]
            if live is None or data['revision'] != before['revision']:
                raise AutonomyError('assignment changed while observing the recipient; retry send')
        a['state'] = 'sending'; data['outbox'][aid]['sending'] = True
        entry = data['outbox'][aid].copy(); persist(ws, data)
    if is_claude(ws):
        # The send intent is committed. The coordinator model delivers TASK with its
        # SendMessage tool; a crash before `session sent` leaves an unknown outcome.
        sent = codex_adapter.shell_join([*codex_adapter.python_command(), str(Path(__file__).with_name('orch.py')),
                                         '--workspace', str(ws.root), 'session', 'sent', '--assignment', aid,
                                         '--coordinator', thread, '--generation', str(generation),
                                         '--outcome', 'queued', '--evidence', 'SendMessage result'], ws.config.get('shell'))
        return {'result': 'send_required', 'assignment_id': aid, 'to': instance['name'],
                'session_id': instance['thread_id'], 'message': entry['message'],
                'next': 'Call SendMessage(to, message, notify_when_idle=true) once, then record its result: ' + sent +
                        ' (use --outcome not_sent only for an explicit "Not sent"/declined notice; '
                        'anything ambiguous is outcome_unknown)'}
    result = codex_transport.send(entry['thread_id'], entry['message'], remote=endpoint(ws))
    with state_io.transaction(ws.root):
        _, data = registry(ws); a = data['assignments'][aid]
        # An early start acknowledgement always wins over late sender bookkeeping.
        if a['state'] not in ('started', 'completed'):
            a['state'] = 'queued' if result.get('queued') else 'outcome_unknown' if result.get('outcome_unknown') else 'reserved'
        data['outbox'][aid].update(result, sending=result.get('outcome_unknown', False))
        persist(ws, data)
    return {'result': a['state'], 'assignment_id': aid, 'transport': result}


def record_started(ws, aid):
    # Only a module's transition or an observed assistant acknowledgement invokes
    # this helper. The public CLI cannot arbitrarily flip a WP to IN_PROGRESS.
    _, data = registry(ws); a = data['assignments'].get(aid)
    if not a:
        raise AutonomyError('unknown assignment')
    instance = data['instances'][a['session']]
    if a['state'] in ('completed', 'started'):
        return {'result': a['state'], 'assignment_id': aid}
    if a['state'] not in ('sending', 'queued', 'outcome_unknown'):
        raise AutonomyError('assignment has not been sent')
    a.update(state='started', started_at=time.time())
    if instance.get('wp') in data['sessions']:
        data['sessions'][instance['wp']]['state'] = 'reused'
    instance.update(wp=a['wp'], branch=a['branch'])
    if a['wp'] not in instance['history']:
        instance['history'].append(a['wp'])
    data['sessions'][a['wp']] = instance.copy()
    runtime.api().cmd_set(argparse.Namespace(workspace=str(ws.root), wp=a['wp'], column='status', text='IN_PROGRESS',
                                            quiet=True, evidence='assignment started ' + aid))
    persist(ws, data)
    return {'result': 'started', 'assignment_id': aid}


def executor_ok(instance, receipt):
    """Claude: the transition receipt names the session/process that ran it."""
    proof = instance.get('confirmation') or {}
    ran = receipt.get('executor') or {}
    return ran.get('session_id') == instance['thread_id'] and ran.get('process') == proof.get('process')


def reconcile(ws, aid, thread, generation, evidence=None):
    _, before = registry(ws); a = before['assignments'].get(aid)
    if not a:
        raise AutonomyError('unknown assignment')
    instance = before['instances'][a['session']]
    live = observe_thread(ws, instance['thread_id'], history=True)
    # Read recipient output, never the echoed TASK/user input as acknowledgement.
    marker = 'STARTED assignment_id=' + aid
    ack = any(i.get('type') == 'agentMessage' and marker in i.get('text', '')
              for turn in live.get('turns', []) for i in turn.get('items', []))
    if instance['client'] == 'claude':
        # Claude history is not readable from outside. The executor-bound receipt
        # (session ID + confirmed process of the caller) is the start proof; a
        # relayed STARTED message is recorded as supporting evidence only.
        path = transition_path(ws, aid)
        saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        ack = executor_ok(instance, saved)
    facts = git_snapshot(Path(instance['worktree']))
    with state_io.transaction(ws.root):
        _, data = registry(ws); owner(data, thread, generation)
        if data['revision'] != before['revision']:
            raise AutonomyError('assignment changed while observing recipient; retry reconcile')
        if data['assignments'][aid]['state'] in ('started', 'completed'):
            return {'result': data['assignments'][aid]['state'], 'assignment_id': aid}
        if a['state'] == 'reserved':
            # No send intent was ever committed. Ownership may safely transfer;
            # queued/unknown sends can never take this path.
            data['assignments'][aid].update(generation=generation, coordinator=thread)
            persist(ws, data)
            return {'result': 'reserved', 'assignment_id': aid}
        receipt = transition_path(ws, aid)
        prepared = json.loads(receipt.read_text(encoding='utf-8')).get('complete') if receipt.exists() else False
        if ack and prepared and facts['branch'] == a['branch']:
            if evidence:
                data['assignments'][aid]['ack_evidence'] = evidence
                persist(ws, data)
            return record_started(ws, aid)
    return {'result': 'outcome_unknown', 'assignment_id': aid,
            'reason': 'no verified start; reservation retained; do not resend or hand over'}


def transition_path(ws, aid):
    if not re.fullmatch(r'[0-9a-f-]{36}', aid):
        raise AutonomyError('invalid assignment ID')
    return state_io.runtime_dir() / 'transitions' / digest(str(ws.root.resolve())) / (aid + '.json')


def transition(ws, aid, thread):
    """Executed by the assigned module. Writes Git and a technical runtime receipt,
    never coordinator documents. A repeated invocation resumes observed facts.
    """
    _, data = registry(ws); require_enabled(ws, data)
    a = data['assignments'].get(aid)
    if not a or a['state'] not in ('sending', 'queued', 'outcome_unknown', 'started'):
        raise AutonomyError('assignment is not awaiting/continuing execution')
    instance = data['instances'][a['session']]
    executor = None
    if instance['client'] == 'claude':
        # Claude Code exports the session ID and its own PID to Bash; both must be the attached ones.
        if thread != instance['thread_id'] or os.environ.get('CLAUDE_CODE_SESSION_ID') != thread:
            raise AutonomyError('transition belongs to another Claude session')
        try:
            ran = process_identity(int(os.environ.get('CLAUDE_PID') or 0))
        except (ValueError, AutonomyError) as error:
            raise AutonomyError('Claude session process is not observable from the transition') from error
        if ran != (instance.get('confirmation') or {}).get('process'):
            raise AutonomyError('transition runs in another Claude process than the confirmed one')
        if ran['pid'] not in ancestors():
            raise AutonomyError('transition is not a child of the confirmed Claude session process')
        executor = {'session_id': thread, 'process': ran}
    elif thread != instance['thread_id'] or os.environ.get('CODEX_THREAD_ID', thread) != thread:
        raise AutonomyError('transition belongs to another thread')
    directory = Path(instance['worktree']).resolve()
    if Path.cwd().resolve() != directory:
        raise AutonomyError('run transition from the assigned module worktree')
    live = observe_thread(ws, thread)
    proof_errors = compatible(ws, instance, {**live, 'status': {'type': 'idle'}}, {})
    if proof_errors:
        raise AutonomyError('; '.join(proof_errors))
    _, module, _ = runtime.api().wp_context(ws, a['wp'])
    receipt = transition_path(ws, aid)
    with state_io.transaction(receipt.parent):
        fact = git_snapshot(directory)
        if receipt.exists():
            previous = json.loads(receipt.read_text(encoding='utf-8'))
            if previous.get('complete'):
                if fact['branch'] != a['branch']:
                    raise AutonomyError('completed transition branch changed; reconcile explicitly')
                return {'result': 'prepared', 'assignment_id': aid, 'acknowledgement': 'STARTED assignment_id=' + aid}
        if fact['dirty'] or fact['branch'] not in (a['previous_branch'], a['branch']):
            raise AutonomyError('dirty or unexpected branch; retain reservation and reconcile')
        if fact['branch'] == a['previous_branch']:
            if fact['head'] != a['previous_head']:
                raise AutonomyError('previous branch moved since assignment')
            if streams.has_remote(module.repo):
                r = streams.git(directory, 'fetch', 'origin', module.repo.base)
                if r.returncode:
                    detail = re.sub(r'(https?://)[^/@\s]+@', r'\1<redacted>@', r.stderr.strip())
                    raise AutonomyError('cannot fetch current base; transition retained: ' + detail)
            base_ref = streams.base_ref(module.repo)
            resolved = streams.git(directory, 'rev-parse', '--verify', base_ref + '^{commit}')
            if resolved.returncode:
                raise AutonomyError('current base cannot be resolved')
            base = resolved.stdout.strip()
            native = claude_adapter.NATIVE_CONFIG if instance['client'] == 'claude' else (
                '.codex/config.toml', '.codex/rules/pepper-orchestrator.rules')
            changed = streams.git(directory, 'diff', '--name-only', fact['head'], base, '--', *native)
            if changed.returncode or changed.stdout.strip():
                raise AutonomyError('new base changes native client configuration; owner preparation/reconfirmation is required')
            if streams.ref_exists(directory, a['branch']):
                raise AutonomyError('new branch already exists without transition evidence; reconcile')
            state_io.atomic(receipt, json.dumps({'branch': a['branch'], 'base': base, 'complete': False,
                                                 'executor': executor}).encode())
            r = streams.git(directory, 'switch', '-c', a['branch'], base)
            if r.returncode:
                raise AutonomyError('branch transition failed: ' + r.stderr.strip())
        elif not receipt.exists():
            raise AutonomyError('new branch has no transition receipt; reconcile before preparation')
        # Reuse preserves native client rules and only runs environment setup.
        # A failed setup is never rerun
        # blindly: the owner must inspect its effects and explicitly permit retry.
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('setup_started'):
            raise AutonomyError('setup outcome unknown; inspect effects and recover transition explicitly')
        saved['setup_started'] = True
        state_io.atomic(receipt, json.dumps(saved).encode())
        adapter(ws).prepare_reuse(ws, a['wp'], directory)
        if configuration(ws, instance) != instance['confirmation']['configuration']:
            raise AutonomyError('configuration changed during transition; inspect before reconfirming/retrying')
        saved['complete'] = True
        state_io.atomic(receipt, json.dumps(saved).encode())
    return {'result': 'prepared', 'assignment_id': aid, 'acknowledgement': 'STARTED assignment_id=' + aid}


def watch_path(ws):
    return state_io.runtime_dir() / 'watchers' / (digest(str(ws.root.resolve())) + '.json')


def read_watch(ws):
    path = watch_path(ws)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def write_watch(ws, value):
    state_io.atomic(watch_path(ws), (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def watch_tick(ws, state, clock=None):
    now = time.time() if clock is None else clock
    _, data = registry(ws)
    if ws.closed or not data['autonomy']['enabled']:
        return {**state, 'stopped': True}, None
    current = data.get('coordinator') or {}
    if current.get('released') or not current.get('thread_id'):
        raise AutonomyError('no active coordinator; resume after ownership recovery')
    owner(data, current['thread_id'], current['generation'])
    plan = next_actions(ws)
    signal = state.get('pending')
    if signal:
        # The coordinator consumes the signal explicitly; neither timeout nor an
        # empty queue result proves non-delivery. Keep only the latest observation.
        state['coalesced'] = plan['fingerprint']
        return state, None
    actionable = bool(plan['actions']) or any(w.get('kind') == 'observation_error' for w in plan['waiting'])
    if not actionable or (state.get('fingerprint') == plan['fingerprint'] and now < state.get('next_due', 0)):
        return state, None
    live = observe_thread(ws, current['thread_id'])
    if live.get('status', {}).get('type') == 'notLoaded':
        raise AutonomyError('coordinator session is not live; resume after ownership recovery')
    # Claude: a session with a running Monitor reports busy at an empty prompt, and the
    # client queues Monitor lines between turns; the single pending signal is the dedupe.
    if not is_claude(ws) and live.get('status', {}).get('type') != 'idle':
        state['coalesced'] = plan['fingerprint']
        return state, None
    sid = str(uuid.uuid4())
    consume = codex_adapter.shell_join([
        *codex_adapter.python_command(), str(Path(__file__).with_name('orch.py')),
        '--workspace', str(ws.root), 'autonomy', 'consume', '--signal', sid,
        '--coordinator', current['thread_id'], '--generation', str(current['generation'])], ws.config.get('shell'))
    return {**state, 'fingerprint': plan['fingerprint'], 'next_due': now + plan['next_check_seconds'],
            'pending': {'id': sid, 'state': 'sending', 'generation': current['generation'],
                        'thread': current['thread_id']}}, (
                f'[{ws.tag}] AUTONOMY signal_id={sid}. Inspect current state, not this stale notification. '
                f'Run: {consume}\n'
                'If enabled, follow next actions and dispatch compatible READY packages yourself. '
                'Reconcile unknown assignments first. Preserve all delivery gates and owner decisions.')


def emit(line):
    # One physical line per event: Claude Monitor turns each stdout line into a notification.
    print(' '.join(str(line).split()), flush=True)


def watcher_alive(state):
    proof = state.get('process')
    try:
        return bool(proof) and process_identity(proof['pid']) == proof
    except (AutonomyError, OSError, subprocess.TimeoutExpired):
        return False


def run_watcher(ws, token, stdout=False):
    path = watch_path(ws)
    with state_io.transaction(path.parent):
        state = read_watch(ws)
        if state.get('token') != token:
            raise AutonomyError('watcher replaced before startup')
        mine = process_identity(os.getpid())
        if stdout and watcher_alive(state) and state['process'] != mine and not state.get('stopped'):
            raise AutonomyError('another watcher process is running for this program; stop it or wait for its Monitor to expire')
        state.update(process=mine, stopped=False)
        write_watch(ws, state)
    if stdout:
        emit(f'[{ws.tag}] AUTONOMY watcher started; it prints only actionable signals, observation failures and its stop.')
    while True:
        ws = runtime.api().Workspace(ws.root)
        with state_io.transaction(path.parent):
            state = read_watch(ws)
            if state.get('token') != token:
                return 0
        try:
            updated, message = watch_tick(ws, state)
            updated.pop('error', None)
            # Recheck pause/ownership after slow external observations, before
            # committing the send intent. Never hold state locks during queue.
            with state_io.transaction(ws.root):
                fresh = runtime.api().Workspace(ws.root)
                _, data = registry(fresh)
                if fresh.closed or not data['autonomy']['enabled']:
                    updated['stopped'] = True; message = None
                else:
                    updated['stopped'] = False
                if message:
                    pending = updated['pending']
                    owner(data, pending['thread'], pending['generation'])
                with state_io.transaction(path.parent):
                    latest = read_watch(ws)
                    if latest.get('token') != token:
                        return 0
                    # A consume operation can clear pending while facts are read.
                    if latest.get('pending') != state.get('pending'):
                        continue
                    if updated != latest:
                        write_watch(ws, updated)
            if updated.get('stopped'):
                if stdout:
                    emit(f'[{ws.tag}] AUTONOMY watcher stopped: autonomy paused/disabled or program closed.')
                return 0
            if message and stdout:
                pending = updated['pending']
                emit(message)
                with state_io.transaction(path.parent):
                    latest = read_watch(ws)
                    if (latest.get('pending') or {}).get('id') == pending['id']:
                        latest['pending']['state'] = 'queued'
                        write_watch(ws, latest)
            elif message:
                pending = updated['pending']
                result = codex_transport.send(pending['thread'], message, remote=endpoint(ws))
                with state_io.transaction(path.parent):
                    latest = read_watch(ws)
                    if (latest.get('pending') or {}).get('id') == pending['id']:
                        latest['pending']['state'] = 'queued' if result.get('queued') else 'outcome_unknown'
                        write_watch(ws, latest)
        except (OSError, ValueError, subprocess.TimeoutExpired, codex_transport.TransportError,
                claude_adapter.ClaudeError, AutonomyError) as error:
            # Observability failure is recoverable on resume. Persist technical
            # diagnostics once, without writing program journals or sending TASKs.
            with state_io.transaction(path.parent):
                latest = read_watch(ws)
                if latest.get('token') != token:
                    return 0
                if latest.get('error') != str(error):
                    latest['error'] = str(error); write_watch(ws, latest)
                    if stdout:  # Failure must not look like silence.
                        emit(f'[{ws.tag}] AUTONOMY observation error: {error}')
        time.sleep(5)


def start_watcher(ws):
    path = watch_path(ws)
    if not is_claude(ws) and codex_transport.private_mode():
        # Private STDIO cannot be shared with a detached CLI. The explicit owner
        # drives watch_tick in-process; no new endpoint or model poll is created.
        with state_io.transaction(path.parent):
            previous = read_watch(ws)
            state = {**previous, 'mode': 'private-owner', 'stopped': False}
            if state != previous:
                write_watch(ws, state)
        return {'watcher': 'private-owner', 'mode': 'in-process'}
    if is_claude(ws):
        # Claude: the coordinator itself runs the watcher under its Monitor tool,
        # so lines wake that same session. No detached process is created here.
        with state_io.transaction(path.parent):
            previous = read_watch(ws)
            current = (registry(ws)[1].get('coordinator') or {})
            bound = {'thread': current.get('thread_id'), 'generation': current.get('generation')}
            # Monitor lines reach only the session that runs it: a watcher of another
            # coordinator generation is replaced, never reused.
            if watcher_alive(previous) and not previous.get('stopped') and previous.get('coordinator') == bound:
                return {'result': 'watching', 'watcher': previous}
            token = str(uuid.uuid4())
            write_watch(ws, {**previous, 'token': token, 'process': None, 'stopped': False, 'coordinator': bound})
        command = codex_adapter.shell_join([*codex_adapter.python_command(), str(Path(__file__).with_name('orch.py')),
                                            '--workspace', str(ws.root), 'autonomy', 'watch', '--token', token,
                                            '--stdout'], ws.config.get('shell'))
        return {'result': 'monitor_required', 'token': token, 'command': command,
                'next': 'Start exactly one Monitor with this command and timeout_ms 1800000; on its expiry notice '
                        'run autonomy resume again and start the returned command. Do not run it with Bash.'}
    with state_io.transaction(path.parent):
        previous = read_watch(ws)
        proof = previous.get('process') or previous.get('starting_process')
        if proof and not previous.get('stopped'):
            try:
                if process_identity(proof['pid']) == proof:
                    return {'result': 'watching', 'watcher': previous}
            except AutonomyError:
                pass
        token = str(uuid.uuid4())
        # Preserve in-flight signals across process death. A new watcher never
        # treats a crash or a timeout as permission to send a duplicate wakeup.
        value = {**previous, 'token': token, 'process': None, 'starting_process': process_identity(os.getpid()), 'stopped': False}
        write_watch(ws, value)
        command = [sys.executable, str(Path(__file__).with_name('orch.py')), '--workspace', str(ws.root),
                   'autonomy', 'watch', '--token', token]
        options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        with open(os.devnull, 'w') as output:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output, **options)
        return {'result': 'watcher_started', 'pid': child.pid, 'token': token}


def cmd_next(args):
    ws = runtime.workspace(args)
    result = public_plan(next_actions(ws))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for action in result['actions']:
            print(json.dumps(action, ensure_ascii=False))
        for item in result['waiting']:
            print('WAIT ' + json.dumps(item, ensure_ascii=False))
    return 0


def cmd_dispatch(args):
    ws = runtime.workspace(args)
    plan = next_actions(ws)
    chosen = next((a for a in plan['actions'] if a.get('wp') == args.wp and a['kind'] in ('dispatch', 'owner')), None)
    if args.dry_run:
        result = {'result': 'reuse_candidate' if chosen and chosen['kind'] == 'dispatch' else 'needs_new_session' if chosen else 'blocked',
                  'wp': args.wp, 'candidate': chosen, 'plan': public_plan(plan)}
    elif not chosen or chosen['kind'] != 'dispatch':
        result = {'result': 'needs_new_session' if chosen else 'blocked', 'wp': args.wp,
                  'candidate': chosen, 'plan': public_plan(plan)}
    else:
        result = reserve(ws, args.wp, args.coordinator, args.generation, plan)
        if result['result'] == 'assigned':
            result = send_assignment(ws, result['assignment_id'], args.coordinator, args.generation)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['result'] in ('reuse_candidate', 'assigned', 'queued', 'started', 'send_required') else 2


def consume(ws, signal, coordinator, generation, evidence=None):
    """Consume once, then recompute; shared by CLI and private native tools."""
    with state_io.transaction(ws.root):
        _, data = registry(ws); owner(data, coordinator, generation)
        with state_io.transaction(watch_path(ws).parent):
            state = read_watch(ws)
            pending = state.get('pending') or {}
            if pending.get('id') != signal:
                raise AutonomyError('signal is missing, consumed or belongs to an old coordinator')
            if pending.get('generation') != generation and not evidence:
                raise AutonomyError('old-coordinator signal requires explicit reconciliation evidence')
            state.update(pending=None, last_consumed=signal)
            if evidence:
                state['signal_reconciliation'] = evidence
            write_watch(ws, state)
    fresh = runtime.api().Workspace(ws.root)
    return public_plan(next_actions(fresh)) if data['autonomy']['enabled'] and not fresh.closed else {'enabled': False, 'actions': []}


def cmd_autonomy(args):
    ws = runtime.workspace(args)
    action = args.action
    if action == 'watch':
        if not args.token:
            raise AutonomyError('watch is managed by autonomy enable/resume')
        return run_watcher(ws, args.token, stdout=getattr(args, 'stdout', False))
    if action in ('enable', 'resume'):
        if is_claude(ws):
            claude_adapter.capabilities()
            if observe_thread(ws, args.coordinator)['status']['type'] == 'notLoaded':
                raise AutonomyError('coordinator session is not live on this host')
        else:
            caps = runtime.check_capabilities(ws)
            if not caps.get('queue'):
                raise AutonomyError('codex queue is unavailable; autonomy cannot be enabled')
            observe_thread(ws, args.coordinator)  # Prove access to the owning shared server before writes.
    if action == 'status':
        _, data = registry(ws)
        result = {'settings': data['autonomy'], 'coordinator': data.get('coordinator'), 'watcher': read_watch(ws)}
    elif action in ('claim', 'recover'):
        if ws.config.get('client', 'claude') not in ('codex', 'claude') or (ws.config.get('sessions') or 'local') != 'local':
            raise AutonomyError('autonomy is available to local Codex or Claude Code programs only')
        live = observe_thread(ws, args.coordinator)
        private_binding = codex_transport.private_coordinator(args.coordinator, live.get('cwd'), args.pid)
        if codex_transport.private_mode() and not private_binding:
            raise AutonomyError('coordinator does not match protected private-owner registration')
        if not private_binding and (not live.get('cwd') or Path(live['cwd']).resolve() not in (ws.root.resolve(), Path(ws.git_top).resolve())):
            raise AutonomyError('coordinator thread must belong to this program workspace/checkout')
        if live.get('pid') and live['pid'] != args.pid:
            raise AutonomyError('PID does not belong to the live coordinator session')
        proof = process_identity(args.pid)
        if not args.evidence:
            raise AutonomyError('claim requires confirmation of coordinator process/session binding')
        with state_io.transaction(ws.root):
            _, data = registry(ws); previous = data.get('coordinator') or {}
            if previous and not previous.get('released'):
                if action != 'recover' or not args.previous_stopped:
                    raise AutonomyError('active owner exists; lease expiry does not permit takeover')
                # Explicit owner-confirmed recovery; old reservations/outbox stay
                # intact and block replacement assignments until reconciliation.
                data.setdefault('ownership_history', []).append({**previous, 'recovery_evidence': args.previous_stopped})
            data['generation'] += 1
            result = {'thread_id': args.coordinator, 'generation': data['generation'], 'process': proof,
                      'identity': thread_identity(live), 'evidence': args.evidence, 'released': False,
                      'lease_until': time.time() + 1800}
            data['coordinator'] = result; persist(ws, data)
    elif action == 'consume':
        result = consume(ws, args.signal, args.coordinator, args.generation, args.evidence)
    else:
        with state_io.transaction(ws.root):
            _, data = registry(ws)
            if action != 'pause':
                owner(data, args.coordinator, args.generation)
            if action == 'release':
                data['coordinator']['released'] = True
            elif action == 'pause':
                data['autonomy']['enabled'] = False
            elif action in ('enable', 'resume'):
                ws.require_open('enable autonomy')
                if ws.config.get('client', 'claude') not in ('codex', 'claude') or (ws.config.get('sessions') or 'local') != 'local':
                    raise AutonomyError('autonomy requires a local Codex or Claude Code program')
                settings = data['autonomy']
                for name in ('max_parallel_sessions', 'interval_seconds', 'session_reuse'):
                    value = getattr(args, name, None)
                    if value is not None:
                        settings[name] = value
                if settings['max_parallel_sessions'] < 1 or settings['interval_seconds'] < 10:
                    raise AutonomyError('positive parallel limit and interval >= 10 seconds are required')
                settings['enabled'] = True
            result = data['autonomy']; persist(ws, data)
        if action in ('enable', 'resume'):
            result = {**result, **start_watcher(ws)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_session(args):
    if args.action == 'compacted':
        # PostCompact hook of a module session: never fails the hook, writes a runtime receipt only.
        try:
            payload = json.loads(sys.stdin.read() or '{}')
            claude_adapter.record_compaction(Path(getattr(args, 'workspace', None) or '.').resolve(), payload)
        except (OSError, ValueError, claude_adapter.ClaudeError):
            pass
        return 0
    ws = runtime.workspace(args)
    if args.action not in ('discover', 'attach', 'compact', 'reconcile-send'):
        if not args.assignment or args.assignment not in registry(ws)[1]['assignments']:
            raise AutonomyError('session action requires a known --assignment ID')
    if args.action == 'discover' and is_claude(ws):
        _, data = registry(ws)
        repos = {m.repo.key: m.repo for m in ws.streams()[1].values()}
        rows = claude_adapter.agents()
        found = []
        for repo in repos.values():
            for worktree in streams.worktrees(repo):
                path = Path(worktree['path']).resolve()
                for row in rows:
                    if row.get('cwd') and Path(row['cwd']).resolve() == path:
                        live = claude_adapter.normalize(row)
                        found.append({'thread_id': live['id'], 'name': live['name'], 'pid': live['pid'],
                                      'worktree': str(path), 'status': live['status'], 'repo': repo.id,
                                      'registered': 'claude:' + live['id'] in data['instances'],
                                      'confirmation_required': True})
        result = {'sessions': found}
    elif args.action == 'discover':
        found = []
        _, data = registry(ws)
        repos = {m.repo.key: m.repo for m in ws.streams()[1].values()}
        with codex_transport.server(shared=True, remote=endpoint(ws)) as api:
            for repo in repos.values():
                for worktree in streams.worktrees(repo):
                    cursor = None
                    while True:
                        params = {'cwd': str(Path(worktree['path']).resolve()), 'limit': 100,
                                  'sourceKinds': ['cli', 'vscode', 'appServer']}
                        if cursor:
                            params['cursor'] = cursor
                        page = api.call('thread/list', params)
                        for thread in page['data']:
                            found.append({'thread_id': thread['id'], 'worktree': thread['cwd'],
                                          'status': thread.get('status'), 'repo': repo.id,
                                          'registered': 'codex:' + thread['id'] in data['instances'],
                                          'confirmation_required': True})
                        cursor = page.get('nextCursor')
                        if not cursor:
                            break
        result = {'sessions': found}
    elif args.action == 'reconcile-send':
        _, before = registry(ws); owner(before, args.coordinator, args.generation)
        entry = before['outbox'].get(args.request_id)
        if not entry or entry.get('assignment_id'):
            raise AutonomyError('reconcile-send requires a legacy --request-id')
        live = observe_thread(ws, entry['thread_id'], history=True)
        consumed = any(turn.get('status') == 'completed' and any(
            item.get('type') == 'userMessage' and ''.join(p.get('text', '') for p in item.get('content', []) if p.get('type') == 'text') == entry['message']
            for item in turn.get('items', [])) for turn in live.get('turns', []))
        if consumed:
            with state_io.transaction(ws.root):
                _, data = registry(ws); owner(data, args.coordinator, args.generation)
                if data['revision'] != before['revision']:
                    raise AutonomyError('legacy outbox changed during observation; retry reconcile-send')
                data['outbox'][args.request_id].update(sending=False, outcome_unknown=False, delivered=True, consumed=True)
                persist(ws, data)
        result = {'result': 'consumed' if consumed else 'outcome_unknown', 'request_id': args.request_id}
    elif args.action == 'attach':
        result = attach(ws, args)
    elif args.action == 'transition':
        result = transition(ws, args.assignment, args.thread)
    elif args.action in ('started', 'reconcile'):
        result = reconcile(ws, args.assignment, args.coordinator, args.generation, args.evidence)
    elif args.action == 'assign':
        result = reserve(ws, args.wp, args.coordinator, args.generation)
    elif args.action == 'send':
        result = send_assignment(ws, args.assignment, args.coordinator, args.generation)
    elif args.action == 'sent':
        if args.outcome not in ('queued', 'outcome_unknown', 'not_sent') or not args.evidence:
            raise AutonomyError('sent requires queued|outcome_unknown|not_sent and transport evidence; never infer non-delivery')
        if args.outcome == 'not_sent' and not is_claude(ws):
            raise AutonomyError('not_sent records an explicit Claude SendMessage refusal only')
        with state_io.transaction(ws.root):
            _, data = registry(ws); owner(data, args.coordinator, args.generation)
            a = data['assignments'][args.assignment]
            if args.outcome == 'not_sent':
                # Proven non-delivery (tool returned "Not sent" or the recipient declined it):
                # the reservation stays, the send intent is cleared for a later checked retry.
                if a['state'] != 'sending':
                    raise AutonomyError('not_sent applies to the pending send only; reconcile instead')
                a['state'] = 'reserved'
                data['outbox'][args.assignment].update(evidence=args.evidence, sending=False, not_sent=True)
            else:
                if a['state'] not in ('started', 'completed'):
                    a['state'] = args.outcome
                data['outbox'][args.assignment].update(evidence=args.evidence, sending=args.outcome == 'outcome_unknown')
            persist(ws, data); result = a
    elif args.action == 'cancel':
        _, before = registry(ws)
        assignment = before['assignments'].get(args.assignment)
        if not assignment or assignment['state'] not in ('reserved', 'sending', 'queued', 'outcome_unknown'):
            raise AutonomyError('cancel is only for a not-yet-started assignment')
        if not args.evidence:
            raise AutonomyError('cancel requires concrete evidence that the recipient writer was stopped')
        instance = before['instances'][assignment['session']]
        proof = instance.get('confirmation') or {}
        observation = process_observation(proof.get('process'))
        if observation['state'] == 'unavailable':
            raise AutonomyError('recipient process observation unavailable; retain reservation: ' + observation['reason'])
        if observation['state'] == 'live':
            raise AutonomyError('confirmed recipient process still exists; stop/reconcile it before cancellation')
        live = observe_thread(ws, instance['thread_id'])
        if live.get('status', {}).get('type') not in ('idle', 'notLoaded'):
            raise AutonomyError('recipient is active or its state is unknown; retain reservation')
        with state_io.transaction(ws.root):
            _, data = registry(ws); owner(data, args.coordinator, args.generation)
            if data['revision'] != before['revision']:
                raise AutonomyError('assignment changed during cancellation; reconcile again')
            if runtime.api().Workspace(ws.root).wp_rows()[assignment['wp']]['status'] != 'DISPATCHING':
                raise AutonomyError('WP has advanced; do not cancel its reservation')
            for lock in runtime.api().locks(ws):
                if lock['holder'] == assignment['wp']:
                    runtime.api().release(ws, lock['lock'], assignment['wp'])
            data['assignments'][args.assignment].update(state='cancelled', stop_evidence=args.evidence)
            data['instances'][assignment['session']].update(state='stopped', assignment_id=None)
            for record in data['sessions'].values():
                if record['thread_id'] == instance['thread_id']:
                    record['state'] = 'stopped'
            runtime.api().cmd_set(argparse.Namespace(workspace=str(ws.root), wp=assignment['wp'], column='status',
                                                     text='READY', quiet=True, evidence=args.evidence))
            persist(ws, data); result = {'result': 'cancelled', 'assignment_id': args.assignment}
    elif args.action == 'recover-transition':
        _, data = registry(ws); owner(data, args.coordinator, args.generation)
        assignment = data['assignments'][args.assignment]
        instance = data['instances'][assignment['session']]
        if not args.evidence or observe_thread(ws, instance['thread_id']).get('status', {}).get('type') != 'idle':
            raise AutonomyError('transition recovery requires an idle recipient and evidence that setup effects were inspected')
        receipt = transition_path(ws, args.assignment)
        with state_io.transaction(ws.root):
            _, current = registry(ws); owner(current, args.coordinator, args.generation)
            if current['revision'] != data['revision']:
                raise AutonomyError('assignment changed during transition recovery')
            with state_io.transaction(receipt.parent):
                saved = json.loads(receipt.read_text(encoding='utf-8'))
                if saved.get('complete') or git_snapshot(Path(instance['worktree']))['branch'] != assignment['branch']:
                    raise AutonomyError('transition is complete or the branch changed; reconcile instead')
                saved.update(setup_started=False, recovery_evidence=args.evidence)
                state_io.atomic(receipt, json.dumps(saved).encode())
        result = {'result': 'transition_retry_authorized', 'assignment_id': args.assignment}
    elif args.action == 'compact' and is_claude(ws):
        result = compact_claude(ws, args)
    elif args.action == 'compact':
        _, data = registry(ws); owner(data, args.coordinator, args.generation)
        key = 'codex:' + str(args.thread)
        instance = data['instances'].get(key)
        if not instance:
            raise AutonomyError('compact requires a registered thread')
        if instance.get('assignment_id') and data['assignments'][instance['assignment_id']]['state'] not in ('completed', 'cancelled', 'started'):
            raise AutonomyError('reconcile pending assignment before compaction')
        live = observe_thread(ws, args.thread)
        if live.get('status', {}).get('type') != 'idle':
            raise AutonomyError('compaction requires an idle session')
        with state_io.transaction(ws.root):
            _, data = registry(ws); owner(data, args.coordinator, args.generation)
            data['instances'][key]['context_state'] = 'compacting'; persist(ws, data)
        result = codex_transport.compact(args.thread, remote=endpoint(ws))
        with state_io.transaction(ws.root):
            _, data = registry(ws)
            data['instances'][key]['context_state'] = 'ready' if result.get('completed') else 'outcome_unknown'
            persist(ws, data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('result') != 'outcome_unknown' else 2


def compact_claude(ws, args):
    """Claude never executes slash commands from messages. The owner types /compact in
    the module window; the module's PostCompact hook leaves a receipt that this call checks."""
    _, data = registry(ws); owner(data, args.coordinator, args.generation)
    key = 'claude:' + str(args.thread)
    instance = data['instances'].get(key)
    if not instance:
        raise AutonomyError('compact requires a registered session')
    if instance.get('assignment_id') and data['assignments'][instance['assignment_id']]['state'] not in ('completed', 'cancelled', 'started'):
        raise AutonomyError('reconcile pending assignment before compaction')
    receipt = claude_adapter.read_compaction(ws.root, args.thread) or {}
    requested = instance.get('compact_requested_at')
    if instance.get('context_state') == 'compacting' and requested:
        done = receipt.get('at', 0) > requested and receipt.get('cwd') and \
            Path(receipt['cwd']).resolve() == Path(instance['worktree']).resolve()
        live = observe_thread(ws, args.thread)
        if done and live['status']['type'] == 'idle':
            with state_io.transaction(ws.root):
                _, data = registry(ws); owner(data, args.coordinator, args.generation)
                data['instances'][key].update(context_state='ready', compacted=receipt)
                persist(ws, data)
            return {'result': 'compacted', 'session': key, 'receipt': receipt}
        return {'result': 'outcome_unknown', 'session': key,
                'reason': 'no PostCompact receipt after the request, or the session is not idle; reuse stays blocked'}
    if observe_thread(ws, args.thread)['status']['type'] != 'idle':
        raise AutonomyError('compaction requires an idle session')
    with state_io.transaction(ws.root):
        _, data = registry(ws); owner(data, args.coordinator, args.generation)
        data['instances'][key].update(context_state='compacting', compact_requested_at=time.time())
        persist(ws, data)
    return {'result': 'owner_action', 'session': key,
            'instruction': f'Owner: type in the window of session {instance.get("name")!r}: /compact keep the contracts '
                           'of the stream, open locks and the handover of the previous package. Then run this compact '
                           'command again to verify the PostCompact receipt.'}


def add_parsers(sub, common):
    p = sub.add_parser('next', parents=[common], help='read-only deterministic lifecycle actions and compatible dispatch wave')
    p.add_argument('--json', action='store_true'); p.set_defaults(func=cmd_next)
    p = sub.add_parser('autonomy', parents=[common], help='opt-in Codex/Claude coordinator ownership and local observation')
    p.add_argument('action', choices=('status', 'claim', 'recover', 'release', 'enable', 'pause', 'resume', 'watch', 'consume'))
    p.add_argument('--coordinator'); p.add_argument('--generation', type=int); p.add_argument('--pid', type=int)
    p.add_argument('--evidence'); p.add_argument('--previous-stopped')
    p.add_argument('--session-reuse', choices=('auto', 'ask', 'never'))
    p.add_argument('--max-parallel-sessions', type=int); p.add_argument('--interval-seconds', type=int)
    p.add_argument('--signal'); p.add_argument('--token')
    p.add_argument('--stdout', action='store_true', help='Claude: print signals for the coordinator Monitor')
    p.set_defaults(func=cmd_autonomy)
