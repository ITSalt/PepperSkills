"""Explicit private-STDIO adapter over the existing portable scheduler.

The owner registers existing native threads. There is no listener, file inbox,
generic RPC/shell runner, session creation tool or approval handler in dispatch.
Program state, config, installed code and owner receipts are outside model roots.
"""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shlex
import sys
import threading
import time
import uuid

import autonomy
import codex_transport
import owner_observation
import runtime_commands as runtime
import state_io
import streams
from owner_main import within, outside_repository


class OwnerError(RuntimeError):
    pass


def permission_roots(profile):
    if not isinstance(profile, dict) or set(profile) - {'fileSystem', 'network'} or profile.get('network') not in (None, {'enabled': False}):
        raise OwnerError('additional network or unknown authority is forbidden')
    fs = profile.get('fileSystem')
    if not isinstance(fs, dict) or set(fs) - {'read', 'write', 'entries', 'globScanMaxDepth'} or fs.get('read') or fs.get('globScanMaxDepth'):
        raise OwnerError('only exact filesystem writes are supported')
    roots = list(fs.get('write') or [])
    for entry in fs.get('entries') or []:
        if set(entry) != {'access', 'path'} or entry['access'] != 'write':
            raise OwnerError('unexpected filesystem entry')
        target = entry['path']
        if not isinstance(target, dict) or set(target) != {'type', 'path'} or target['type'] != 'path':
            raise OwnerError('special/glob authority is forbidden')
        roots.append(target['path'])
    if not roots or any(not isinstance(v, str) or not Path(v).is_absolute() or str(Path(v).resolve()) != v for v in roots):
        raise OwnerError('permission paths must be canonical and absolute')
    return sorted(set(roots))


TOOL = {'type': 'function', 'name': 'pepper_orchestrator',
    'description': 'Program-scoped coordination. Actor identity comes from the native runtime; never supply actor IDs. '
        'Module: context, prepare, prepared. Coordinator: context, next, consume, dispatch, reconcile.',
    'inputSchema': {'type': 'object', 'properties': {
        'operation': {'type': 'string', 'enum': ['context', 'next', 'consume', 'dispatch', 'reconcile', 'prepare', 'prepared']},
        'wp': {'type': 'string'}, 'assignment': {'type': 'string'}, 'signal': {'type': 'string'}},
        'required': ['operation'], 'additionalProperties': False}}


class PrivateOwner:
    @staticmethod
    def validate_recovery(directory, native, workspace):
        """Must run BEFORE creating a replacement App Server. No implicit takeover."""
        directory = Path(directory).resolve()
        saved = json.loads((directory / 'roles.json').read_text(encoding='utf-8'))
        if saved['workspace'] != str(Path(workspace).resolve()):
            raise OwnerError('saved owner belongs to another program')
        observed = autonomy.process_observation(saved.get('process'))
        if observed.get('state') != 'exited':
            raise OwnerError('old native runtime is not positively stopped: ' + str(observed))
        if codex_transport.file_sha256(native) != saved.get('native_sha256'):
            raise OwnerError('native binary changed; explicit owner migration required')
        code = Path(__file__).resolve().parent
        current = {p.name: state_io.digest(p) for p in code.glob('*.py')}
        if current != saved.get('code_sha256'):
            raise OwnerError('installed runtime changed; explicit owner migration required')
        if state_io.digest(Path(workspace) / 'orch.yaml') != saved.get('config_sha256'):
            raise OwnerError('program configuration changed during recovery')
        if state_io.digest(Path(saved['codex_home']) / 'config.toml') != saved.get('isolated_config_sha256'):
            raise OwnerError('isolated native configuration changed during recovery')
        if set(saved.get('actor_roots', [])) != {r['worktree'] for r in saved.get('roles', {}).values()}:
            raise OwnerError('saved native actor root declarations are incomplete or changed')
        # Native command launch rights can survive a turn. Unknown terminals are
        # never assumed dead just because their parent App Server stopped.
        log = Path(saved['event_log'])
        commands = {}
        for line in log.read_text(encoding='utf-8').splitlines():
            e = json.loads(line); m = e['message']; p = m.get('params', {})
            if e['direction'] == 'native_to_owner' and m.get('method') in ('item/started', 'item/completed') and p.get('item', {}).get('type') == 'commandExecution':
                commands[(p['threadId'], p['item']['id'])] = p['item']
        if any(codex_transport.unresolved_command(c) for c in commands.values()):
            raise OwnerError('old native commands have unknown lifetime; inspect and stop them before recovery')
        with (directory / 'recovery-history.jsonl').open('a', encoding='utf-8') as history:
            history.write(json.dumps({'previous': saved, 'observation': observed}) + '\n')
        return saved

    def __init__(self, api, workspace, directory):
        if os.name == 'nt':
            raise OwnerError('private owner live mode requires Linux or macOS')
        self.api = api
        self.directory = Path(directory).resolve(strict=True)
        self.workspace = Path(workspace).resolve(strict=True)
        self.config = state_io.digest(self.workspace / 'orch.yaml')
        self.isolated_config = None  # Pin after native bootstrap adds its project trust records.
        self.code = Path(__file__).resolve().parent
        outside_repository(self.code)
        self.roles = {}
        self.seen = set()
        self.preparations = {}
        self.generation = None
        self.coordinator = None
        self.observer = owner_observation.GitObserver(self.directory / 'git-observer')
        self.worker_stop = threading.Event()
        self.worker = None
        self.error = None
        self.code_hashes = {str(p): state_io.digest(p) for p in self.code.glob('*.py')}
        self.integrity_canary = self.directory / 'integrity-canary'
        if not self.integrity_canary.exists():
            state_io.atomic(self.integrity_canary, b'owner integrity canary\n', 0o600)
        if not state_io.runtime_dir().is_relative_to(self.directory):
            raise OwnerError('private owner requires a dedicated protected runtime directory')
        for protected in (self.directory, self.workspace, self.code, self.api.home):
            if any(protected.is_relative_to(Path(p).resolve()) for p in ('/tmp', '/private/tmp', os.environ.get('TMPDIR', '/tmp'))):
                raise OwnerError('owner code/state/config cannot use shared writable temporary roots')
        initial = runtime.api().Workspace(self.workspace)
        if initial.config.get('client') != 'codex' or initial.config.get('sessions') != 'local' or (
                initial.config.get('codex') or {}).get('remote') or (initial.config.get('codex') or {}).get('required_mcp'):
            raise OwnerError('private owner requires local Codex with no alternate endpoint or required MCP')
        self.observer.toplevels[str(self.workspace)] = str(initial.git_top)
        for repo in initial.streams()[0].values():
            if repo.local.is_dir():
                self.observer.register(repo.local)

    @contextmanager
    def core(self):
        with codex_transport.owner_transport(self.api), streams.git_observations(self.observer):
            yield

    def workspace_now(self):
        if self.api.closed or self.api.failure:
            raise OwnerError('owner runtime unavailable; retain assignments and recover explicitly')
        if state_io.digest(self.workspace / 'orch.yaml') != self.config:
            raise OwnerError('program config drift; explicit owner reconfirmation required')
        if self.isolated_config and state_io.digest(self.api.home / 'config.toml') != self.isolated_config:
            raise OwnerError('isolated native config drift; stop and recover explicitly')
        if any(state_io.digest(p) != sha for p, sha in self.code_hashes.items()):
            raise OwnerError('installed owner code drift; stop and recover explicitly')
        # The protected program tree must never redirect host reads/writes elsewhere.
        if any(p.is_symlink() or p.is_file() and p.stat().st_nlink != 1 for p in self.workspace.rglob('*')):
            raise OwnerError('symlink or hardlinked file in protected program state')
        ws = runtime.api().Workspace(self.workspace)
        _, data = autonomy.registry(ws)
        for instance in data['instances'].values():
            registered = self.roles.get(instance['thread_id'])
            if not registered or registered['role'] != 'module' or registered['worktree'] != instance['worktree'] or registered['module'] != instance['module']:
                raise OwnerError('session registry differs from protected native registration')
        return ws

    def register(self, response, role, module=None, branch_prefix=None):
        """Owner bootstrap only. Never reachable through a dynamic tool."""
        if role not in ('coordinator', 'module') or self.worker:
            raise OwnerError('register fixed roles before starting the owner worker')
        tid = response['thread']['id']; cwd = Path(response['cwd']).resolve(strict=True)
        if str(cwd) not in self.api.actor_roots:
            raise OwnerError('native cwd is outside the immutable actor root declarations')
        if tid in self.roles or any(within(cwd, r['worktree']) or within(r['worktree'], cwd) for r in self.roles.values()):
            raise OwnerError('duplicate thread or overlapping actor roots')
        sb = response.get('sandbox', {})
        if (sb.get('type') != 'workspaceWrite' or sb.get('writableRoots') != []
                or sb.get('networkAccess') is not True or response.get('runtimeWorkspaceRoots') != [str(cwd)]
                or sb.get('excludeTmpdirEnvVar') is not False or sb.get('excludeSlashTmp') is not False
                or response.get('approvalPolicy') != 'on-request' or response.get('approvalsReviewer') != 'user'):
            raise OwnerError('unsupported native permission profile')
        protected_directories = (self.directory, self.workspace, self.code.parent, self.api.home,
            Path(self.api.native).parent, Path.home() / '.local/share/pepper-orchestrator/owner-locks')
        for protected in protected_directories:
            if within(protected, cwd) or protected.exists() and within(cwd, protected):
                raise OwnerError('model root would expose owner authority to writes')
        for executable in (Path(self.observer.git_binary), Path(sys.executable).resolve()):
            if within(executable, cwd):
                raise OwnerError('model root would expose an owner executable')
        for other in self.roles.values():
            if other['role'] == 'module' and (within(cwd, other['git']['common']) or within(other['git']['common'], cwd)):
                raise OwnerError('actor root overlaps foreign Git metadata')
        row = {'role': role, 'thread': tid, 'worktree': str(cwd), 'module': module,
            'profile': copy.deepcopy({k: response[k] for k in ('sandbox', 'approvalPolicy', 'approvalsReviewer', 'model', 'runtimeWorkspaceRoots')})}
        self.api.check_configuration(cwd)
        if self.api.call('mcpServerStatus/list', {'threadId': tid, 'detail': 'toolsAndAuthOnly'}).get('data') != []:
            raise OwnerError('per-thread MCP surface is not empty')
        if role == 'module':
            if not module or not branch_prefix or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_/-]*', branch_prefix) or '..' in branch_prefix:
                raise OwnerError('module requires an owner-registered branch namespace')
            row['branch_prefix'] = branch_prefix.rstrip('/') + '/'
            pin = self.observer.register(cwd)
            if os.path.samefile(pin['private'], pin['common']):
                raise OwnerError('private owner modules require separate linked worktrees')
            row['git'] = {k: str(pin[k]) for k in ('private', 'common')}
            for relative in ('refs/heads', 'logs/refs/heads'):
                (pin['common'] / relative / row['branch_prefix']).mkdir(parents=True, exist_ok=True)
            for relative in ('refs/remotes/origin', 'logs/refs/remotes/origin'):
                (pin['common'] / relative).mkdir(parents=True, exist_ok=True)
            for actor in [*self.roles.values(), row]:
                if within(actor['worktree'], pin['common']) or within(pin['common'], actor['worktree']):
                    raise OwnerError('actor roots and common Git metadata must not overlap')
                if actor['role'] == 'module':
                    other_common = Path(actor['git']['common'])
                    if within(cwd, other_common) or within(other_common, cwd):
                        raise OwnerError('actor roots and foreign Git metadata must not overlap')
                    if actor is not row and os.path.samefile(other_common, pin['common']):
                        a = pin['common'] / 'refs/heads' / row['branch_prefix']
                        b = other_common / 'refs/heads' / actor['branch_prefix']
                        if within(a, b) or within(b, a):
                            raise OwnerError('module Git branch namespaces must not overlap')
            authority = [self.workspace, self.code.parent, self.api.home, state_io.runtime_dir(),
                self.directory / 'roles.json', self.directory / 'preparations', self.directory / 'permissions.jsonl',
                Path(self.api.native), Path(self.observer.git_binary), Path(sys.executable).resolve(), Path(self.api.log.name)]
            if any(within(target, root) for root in self.grant_roots(row) for target in authority):
                raise OwnerError('Git grant would expose owner authority or executable code')
        elif self.coordinator:
            raise OwnerError('only one coordinator per owner')
        else:
            self.coordinator = tid
            self.api.coordinator_binding = {'thread': tid, 'cwd': str(cwd)}
        self.roles[tid] = row
        self.api.registered_threads.add(tid)
        self.save_manifest()

    def save_manifest(self):
        state_io.atomic(self.directory / 'roles.json', json.dumps({'epoch': self.api.epoch,
            'process': autonomy.process_identity(self.api.proc.pid), 'workspace': str(self.workspace),
            'code_sha256': {Path(p).name: sha for p, sha in self.code_hashes.items()},
            'config_sha256': self.config, 'native': self.api.native,
            'codex_home': str(self.api.home),
            'actor_roots': sorted(self.api.actor_roots),
            'isolated_config_sha256': self.isolated_config or state_io.digest(self.api.home / 'config.toml'),
            'native_sha256': self.api.native_sha256,
            'event_log': str(Path(self.api.log.name).resolve()),
            'roles': self.roles, 'generation': self.generation}, indent=2).encode(), 0o600)

    @staticmethod
    def grant_roots(row):
        common = Path(row['git']['common']); prefix = row['branch_prefix'].rstrip('/')
        return [row['git']['private'], str(common / 'objects'), str(common / 'refs/heads' / prefix),
            str(common / 'logs/refs/heads' / prefix), str(common / 'refs/remotes/origin'),
            str(common / 'logs/refs/remotes/origin')]

    def resolve_git_approval(self, ident, *, owner_decision):
        """Explicit local owner UI action. Never invoked by tools or watcher."""
        if not isinstance(owner_decision, str) or not owner_decision.strip():
            raise OwnerError('a concrete owner decision is required')
        request = self.api.approvals.get(ident, {}); p = request.get('params', {})
        tid, turn = p.get('threadId'), p.get('turnId'); row = self.roles.get(tid, {})
        plans = [v for v in list(self.preparations.values()) if v['thread'] == tid and v['turn'] == turn and v['epoch'] == self.api.epoch]
        if request.get('method') != 'item/permissions/requestApproval' or row.get('role') != 'module' or len(plans) != 1:
            raise OwnerError('only a registered module preparation filesystem request is supported')
        if p.get('cwd') != row['worktree'] or plans[0]['expires_at'] < time.time():
            raise OwnerError('approval context expired or changed')
        if plans[0].get('grant_attempted'):
            raise OwnerError('this preparation grant was already attempted; reconcile before any retry')
        roots = self.grant_roots(row)
        if permission_roots(p.get('permissions')) != sorted(roots):
            raise OwnerError('approval must request exactly the six canonical Git directories')
        with self.core():
            ws = self.workspace_now()
            assignment, _ = self.assignment(ws, row, plans[0]['assignment_id'])
            if assignment['state'] not in ('sending', 'queued', 'outcome_unknown'):
                raise OwnerError('assignment no longer awaits this preparation grant')
        result = {'permissions': {'fileSystem': {'write': sorted(roots)}}, 'scope': 'turn'}
        record = {'epoch': self.api.epoch, 'request': request, 'result': result,
            'assignment': plans[0]['assignment_id'], 'owner_decision': owner_decision}
        with (self.directory / 'permissions.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(record) + '\n'); log.flush(); os.fsync(log.fileno())
        plans[0]['grant_attempted'] = True
        self.api.reply_approval(ident, result)
        return result

    def bind_generation(self, generation):
        if {r['worktree'] for r in self.roles.values()} != set(self.api.actor_roots):
            raise OwnerError('all fixed native actor roots must be registered before enabling work')
        with self.core():
            ws = self.workspace_now(); _, data = autonomy.registry(ws)
            autonomy.owner(data, self.coordinator, generation)
            self.api.check_configuration()
        self.isolated_config = state_io.digest(self.api.home / 'config.toml')
        self.generation = generation; self.save_manifest()

    def authorize(self, request):
        p = request.get('params', {}); tid, turn, call = (p.get(k) for k in ('threadId', 'turnId', 'callId'))
        row = self.roles.get(tid); args = p.get('arguments')
        if request.get('method') != 'item/tool/call' or p.get('tool') != TOOL['name'] or not row:
            raise OwnerError('unknown native caller/tool')
        if self.api.active.get(tid) != turn or (tid, turn, call) not in self.api.items:
            raise OwnerError('inactive native turn or missing native item')
        key = (self.api.epoch, tid, turn, call)
        if key in self.seen:
            raise OwnerError('duplicate native call; no operation repeated')
        if not isinstance(args, dict) or set(args) - {'operation', 'wp', 'assignment', 'signal'}:
            raise OwnerError('unknown arguments; actor IDs are never accepted')
        op = args.get('operation')
        allowed = {'context', 'next', 'consume', 'dispatch', 'reconcile'} if row['role'] == 'coordinator' else {'context', 'prepare', 'prepared'}
        if op not in allowed:
            raise OwnerError('operation forbidden for native role')
        fields = {'context': set(), 'next': set(), 'consume': {'signal'}, 'dispatch': {'wp'},
                  'reconcile': {'assignment'}, 'prepare': {'assignment'}, 'prepared': {'assignment'}}[op]
        if set(args) != fields | {'operation'} or any(not isinstance(args[k], str) for k in fields):
            raise OwnerError('operation argument mismatch')
        if 'wp' in fields and not re.fullmatch(r'WP-[A-Z0-9]+-\d+', args['wp']):
            raise OwnerError('invalid WP')
        for k in fields & {'assignment', 'signal'}:
            if not re.fullmatch(r'[0-9a-f-]{36}', args[k]):
                raise OwnerError('invalid assignment/signal')
        self.seen.add(key)
        return row, args, turn

    def handle(self, request):
        row, args, turn = self.authorize(request)
        with self.core(), codex_transport.native_operation(row['thread'], turn, request['params']['callId']):
            ws = self.workspace_now(); op = args['operation']
            if op == 'context':
                return {'role': row['role'], 'thread': row['thread'], 'epoch': self.api.epoch,
                    'generation': self.generation, 'workspace': str(self.workspace)}
            if self.generation is None:
                raise OwnerError('owner generation is not bound')
            if op == 'next':
                return autonomy.public_plan(autonomy.next_actions(ws))
            if op == 'dispatch':
                plan = autonomy.next_actions(ws)
                result = autonomy.reserve(ws, args['wp'], row['thread'], self.generation, plan)
                if result.get('result') == 'assigned':
                    result = autonomy.send_assignment(ws, result['assignment_id'], row['thread'], self.generation)
                return result
            if op == 'reconcile':
                return autonomy.reconcile(ws, args['assignment'], row['thread'], self.generation)
            if op == 'consume':
                return autonomy.consume(ws, args['signal'], row['thread'], self.generation)
            if op == 'prepare':
                return self.prepare(ws, row, args['assignment'], turn)
            return self.prepared(ws, row, args['assignment'], turn)

    def assignment(self, ws, row, aid):
        _, data = autonomy.registry(ws); autonomy.require_enabled(ws, data)
        autonomy.owner(data, self.coordinator, self.generation)
        a = data['assignments'].get(aid)
        if not a or a['generation'] != self.generation or a['session'] != 'codex:' + row['thread']:
            raise OwnerError('assignment belongs to another native module/generation')
        instance = data['instances'][a['session']]
        if instance.get('assignment_id') != aid:
            raise OwnerError('assignment was replaced')
        return a, instance

    def prepare(self, ws, row, aid, turn):
        a, instance = self.assignment(ws, row, aid)
        path = autonomy.transition_path(ws, aid)
        if path.exists() or aid in self.preparations:
            raise OwnerError('preparation already attempted; reconcile its outcome, never retry blindly')
        if a['state'] not in ('sending', 'queued', 'outcome_unknown'):
            raise OwnerError('assignment is not awaiting preparation')
        if self.api.running_commands(row['thread']):
            raise OwnerError('module still has unresolved native commands; preparation/reuse blocked')
        live = autonomy.observe_thread(ws, row['thread'])
        errors = autonomy.compatible(ws, instance, {**live, 'status': {'type': 'idle'}}, {})
        facts = autonomy.git_snapshot(Path(row['worktree']))
        if errors or facts['dirty'] or facts['branch'] != a['previous_branch'] or facts['head'] != a['previous_head']:
            raise OwnerError('preparation preflight failed: ' + '; '.join(errors) + repr(facts))
        if not a['branch'].startswith(row['branch_prefix']):
            raise OwnerError('branch is outside the registered module namespace')
        _, module, _ = runtime.api().wp_context(ws, a['wp'])
        plan = {'assignment_id': aid, 'nonce': uuid.uuid4().hex, 'thread': row['thread'],
            'turn': turn, 'epoch': self.api.epoch, 'generation': self.generation,
            'worktree': row['worktree'], 'previous_branch': a['previous_branch'],
            'previous_head': a['previous_head'], 'branch': a['branch'], 'base': module.repo.base,
            'setup': module.repo.worktree_setup, 'expires_at': time.time() + 240,
            'configuration': autonomy.configuration(ws, instance),
            'git_executable': self.observer.git_binary,
            'private_gitdir': row['git']['private'], 'common_gitdir': row['git']['common']}
        controls = {str(os.getpid()): [self.api.proc.stdin.fileno(), self.api.proc.stdout.fileno()],
                    str(self.api.proc.pid): [0, 1]}
        plan['boundary'] = {'controls': controls, 'home': str(self.api.home), 'native': self.api.native,
            'integrity_canary': str(self.integrity_canary),
            'coordinator': self.coordinator, 'protected_paths': [str(self.code / 'private_owner.py'),
                str(self.code / 'module_prepare.py'), str(self.api.home / 'config.toml'),
                str(self.directory / 'roles.json'), str(self.workspace / 'orch.yaml'),
                str(self.workspace / 'status.md'), str(path), str(Path(row['git']['common']) / 'config'),
                str(self.integrity_canary)]}
        _, registered = autonomy.registry(ws)
        for other in self.roles.values():
            if other['role'] == 'module' and other['thread'] != row['thread']:
                plan['boundary']['protected_paths'].append(str(Path(other['git']['private']) / 'HEAD'))
                instance_other = registered['instances'].get('codex:' + other['thread'])
                if instance_other:
                    plan['boundary']['protected_paths'].append(str(Path(other['git']['common']) / 'refs/heads' / instance_other['branch']))
        planpath = self.directory / 'preparations' / (aid + '.json')
        codex_transport.check_native_operation()
        state_io.atomic(planpath, json.dumps(plan).encode(), 0o600)
        command = shlex.join([sys.executable, '-I', '-S', '-B', str(self.code / 'module_prepare.py'), '--plan', str(planpath)])
        plan['command'] = command
        # Commit the intent before returning a command which can have effects.
        state_io.atomic(path, json.dumps({'complete': False, 'setup_started': True,
            'owner_epoch': self.api.epoch, 'native_turn': turn, 'nonce': plan['nonce']}).encode(), 0o600)
        self.preparations[aid] = plan
        roots = self.grant_roots(row)
        return {'command': command, 'permission_request': {'permissions': {'file_system': {'write': roots}},
            'reason': 'Prepare only this registered module Git worktree for assignment ' + aid},
            'scope': 'turn', 'next': 'Request native permissions and wait for the owner decision. If granted, '
                'run the exact finite command once without escalation. Then call prepared with this assignment. '
                'On failure retain the assignment and request reconciliation; never retry setup.'}

    def prepared(self, ws, row, aid, turn):
        a, instance = self.assignment(ws, row, aid)
        plan = self.preparations.get(aid)
        if not plan or plan['epoch'] != self.api.epoch or plan['turn'] != turn or plan['expires_at'] < time.time():
            raise OwnerError('preparation evidence expired or belongs to another native turn/epoch')
        def matches(item):
            if item.get('type') != 'commandExecution' or item.get('status') != 'completed' or item.get('exitCode') != 0 or item.get('cwd') != row['worktree']:
                return False
            try:
                words = shlex.split(item['command'])
                if len(words) == 3 and words[0] in ('/bin/bash', '/bin/sh', '/bin/zsh') and words[1] in ('-lc', '-c'):
                    words = shlex.split(words[2])
                return words == shlex.split(plan['command'])
            except (ValueError, KeyError):
                return False
        commands = [e['params']['item'] for e in self.api.events if e.get('method') == 'item/completed'
            and e.get('params', {}).get('threadId') == row['thread'] and e['params'].get('turnId') == turn
            and matches(e['params'].get('item', {}))]
        if len(commands) != 1:
            raise OwnerError('missing or ambiguous exact native preparation command')
        result = json.loads(commands[0]['aggregatedOutput'].strip())
        facts = autonomy.git_snapshot(Path(row['worktree']))
        if (result.get('nonce') != plan['nonce'] or result.get('assignment_id') != aid
                or result.get('thread') != row['thread'] or result.get('complete') is not True
                or result.get('branch') != a['branch'] or facts['branch'] != a['branch']
                or facts['head'] != result.get('head') or result.get('base') != result.get('head')
                or result.get('helper_sha256') != self.code_hashes[str(self.code / 'module_prepare.py')]
                or result.get('boundary', {}).get('safe') is not True
                or autonomy.configuration(ws, instance) != plan['configuration']):
            raise OwnerError('native preparation result/configuration does not match current facts')
        with state_io.transaction(ws.root):
            self.assignment(ws, row, aid)
            state_io.atomic(autonomy.transition_path(ws, aid), json.dumps({**result, 'complete': True,
                'owner_epoch': self.api.epoch, 'native_turn': turn, 'native_command_item': commands[0]['id'],
                'generation': self.generation, 'configuration': plan['configuration']}).encode(), 0o600)
            started = autonomy.record_started(ws, aid)
        return {**started, 'acknowledgement': 'STARTED assignment_id=' + aid}

    def start(self):
        if self.worker:
            raise OwnerError('owner worker already started')
        def work():
            while not self.worker_stop.is_set() and not self.api.failure:
                try:
                    request = self.api.requests.get(timeout=.2)
                except queue.Empty:
                    continue
                try:
                    result = self.handle(request)
                    reply = {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(result)}]}
                except Exception as error:
                    reply = {'success': False, 'contentItems': [{'type': 'inputText',
                        'text': type(error).__name__ + ': ' + str(error)}]}
                try:
                    self.api.send({'id': request['id'], 'result': reply})
                except codex_transport.TransportError as error:
                    self.error = str(error); return
        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    def tick(self):
        """Passive watcher, same core decision and queue journal; never dispatches."""
        with self.core():
            ws = self.workspace_now(); state = autonomy.read_watch(ws)
            updated, message = autonomy.watch_tick(ws, state)
            with state_io.transaction(ws.root):
                fresh = self.workspace_now(); _, data = autonomy.registry(fresh)
                if fresh.closed or not data['autonomy']['enabled']:
                    return
                autonomy.owner(data, self.coordinator, self.generation)
                with state_io.transaction(autonomy.watch_path(ws).parent):
                    if autonomy.read_watch(ws).get('pending') != state.get('pending'):
                        return
                    if updated != state:
                        autonomy.write_watch(ws, updated)
            if message:
                pending = updated['pending']
                message += '\nPrivate owner mode: call pepper_orchestrator with operation=consume and signal=' + pending['id'] + '; do not run the shell consume command.'
                result = self.api.enqueue(self.coordinator, message)
                with state_io.transaction(autonomy.watch_path(ws).parent):
                    latest = autonomy.read_watch(ws)
                    if (latest.get('pending') or {}).get('id') == pending['id']:
                        latest['pending']['state'] = 'queued' if result.get('queued') else 'outcome_unknown'
                        autonomy.write_watch(ws, latest)

    def stop(self):
        self.worker_stop.set()
        if self.worker:
            self.worker.join(timeout=35)
            if self.worker.is_alive():
                raise OwnerError('owner worker still active; do not resume a second runtime')
