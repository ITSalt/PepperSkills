"""Client-neutral coordination commands. Network operations never hold state locks."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid

import codex_adapter
import codex_transport
import id_allocator
import project_instructions
import safe_edit
import state_io
import streams


def api():
    import sys
    main = sys.modules.get('__main__')
    if main and Path(getattr(main, '__file__', '')).name == 'orch.py':
        return main
    import orch
    return orch


def workspace(args):
    o = api()
    return o.Workspace(o.find_workspace(args.workspace))


def state_version(ws):
    paths = [ws.status, ws.decisions, ws.root / 'orch.yaml', *sorted(ws.wp_dir.glob('WP-*.md'))]
    return {str(p): state_io.digest(p) for p in paths}


def allocate(ws, namespace, legacy, request_id=None):
    numbering = ws.config.get('numbering') or {}
    if not numbering:
        # Old programs stay compatible. The entire local RMW is serialized by invoke().
        return legacy
    return id_allocator.reserve(numbering['scope'], namespace, request_id or str(uuid.uuid4()))['first']


def save(path, text):
    if path.exists():
        old = path.read_text(encoding='utf-8')
        if old != text:
            safe_edit.replace_once(path, old, text)
    else:
        safe_edit.create(path, text)


def invoke(args):
    short = {'cmd_new_wp', 'cmd_set', 'cmd_model', 'cmd_cloud_env', 'cmd_journal', 'cmd_owner',
             'cmd_decide', 'cmd_settings', 'cmd_lock', 'cmd_merge', 'cmd_upgrade', 'cmd_reopen'}
    if args.func.__name__ in short:
        with state_io.transaction(workspace(args).root):
            return args.func(args)
    return args.func(args)


def check_sequence(ws, repo, name):
    resource = repo.sequences[name]
    if repo.sessions == 'cloud':
        raise id_allocator.AllocationError('local sequences cannot retire Claude cloud numbering locks')
    scope = ((ws.config.get('numbering') or {}).get('scope') if resource.get('scope') == 'program'
             else id_allocator.repo_scope(repo.local))
    if not scope:
        raise id_allocator.AllocationError('sequence requires an explicitly migrated allocator')
    con = id_allocator.connect(scope)
    try:
        if not con.execute('SELECT 1 FROM counters WHERE namespace=?', (resource['namespace'],)).fetchone():
            raise id_allocator.AllocationError('sequence namespace not imported: ' + resource['namespace'])
    finally:
        con.close()


def check_capabilities(ws):
    caps = codex_transport.capabilities()
    if not caps['available']:
        raise streams.StreamError('Codex CLI unavailable; install it before dispatch')
    required = (ws.config.get('codex') or {}).get('required_mcp') or []
    import session_settings
    disabled = {x.removeprefix('mcp__').removesuffix('__*') for x in session_settings._prod_servers(ws.config)}
    if set(required) & disabled:
        raise streams.StreamError('required MCP disabled by production policy: ' + ', '.join(sorted(set(required) & disabled)))
    if required:
        try:
            p = subprocess.run(['codex', 'mcp', 'list', '--json'], capture_output=True, text=True, encoding='utf-8', timeout=20)
            data = json.loads(p.stdout) if p.returncode == 0 else []
        except (OSError, ValueError, subprocess.TimeoutExpired):
            data = []
        found = {x.get('name') for x in data if x.get('enabled')}
        missing = set(required) - found
        if missing:
            raise streams.StreamError('required MCP not configured/enabled: ' + ', '.join(sorted(missing)))
    return caps


def cmd_id(args):
    o = api()
    if args.scope.startswith('repo:'):
        root = Path(args.scope[5:]).expanduser().resolve()
        scope = id_allocator.repo_scope(root)
        p = streams.git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
        binding = Path(p.stdout.strip()) / 'info/pepper-orchestrator-scope.json'
        if binding.exists():
            scope = json.loads(binding.read_text(encoding='utf-8'))['scope']
        ws = None
    elif args.scope == 'program':
        ws = workspace(args)
        with state_io.transaction(ws.root):
            ws = workspace(args)
            root, binding = ws.root, ws.root / 'orch.yaml'
            scope = (ws.config.get('numbering') or {}).get('scope')
    else:
        ws = None
        root, binding, scope = Path(args.root or '.').resolve(), None, args.scope
        if args.action == 'migrate':
            # Raw scope IDs are for already registered stores, not unanchored reset paths.
            id_allocator.connect(scope).close()
    if args.action == 'reserve':
        if not args.namespace or not args.request_id:
            raise id_allocator.AllocationError('reserve requires --namespace and --request-id')
        if not scope:
            raise id_allocator.AllocationError('old program: run id migrate --scope program --apply first')
        result = id_allocator.reserve(scope, args.namespace, args.request_id, args.count)
    else:
        if ws and ws.config.get('sessions') == 'cloud':
            raise id_allocator.AllocationError('local allocator is unavailable to Claude cloud; no migration')
        seeds = id_allocator.import_seeds(root, namespaces=[args.namespace] if args.namespace else [])
        if args.namespace:
            regex = re.compile(r'(?<![A-Za-z0-9_-])' + re.escape(args.namespace) + r'[-_](\d+)\b')
            for p in root.rglob('*'):
                if p.is_file() and p.suffix in ('.md', '.sql', '.json', '.yaml', '.yml') and '.git' not in p.parts:
                    for n in regex.findall(p.read_text(encoding='utf-8', errors='replace')):
                        seeds[args.namespace] = max(seeds.get(args.namespace, 0), int(n))
        if args.seed is not None:
            if not args.namespace:
                raise id_allocator.AllocationError('--seed requires --namespace')
            seeds[args.namespace] = max(seeds.get(args.namespace, 0), args.seed)
        if ws and ws.has_table(ws.status, 'merge'):
            seeds['MERGE'] = max([int(x['n']) for x in ws.table(ws.status, 'merge')[2] if x['n'].isdigit()], default=0)
        result = {'scope': scope or '(new program scope on apply)', 'seeds': seeds, 'applied': args.apply,
                  'runtime': str(state_io.runtime_dir()), 'source': str(root)}
        if args.apply:
            with state_io.transaction(state_io.root_for(binding or root)):
                # A durable program/repository binding proves that this store was connected previously.
                if (ws and scope) or (not ws and binding and binding.exists()):
                    id_allocator.connect(scope).close()
                if ws:
                    current = o.Workspace(ws.root)
                    ws = current
                    scope = (current.config.get('numbering') or {}).get('scope') or id_allocator.new_scope()
                    for name, value in id_allocator.import_seeds(root).items():
                        seeds[name] = max(seeds.get(name, 0), value)
                id_allocator.register(scope, seeds)
                if ws and not ws.config.get('numbering'):
                    old = binding.read_text(encoding='utf-8')
                    save(binding, old + '\nnumbering:\n  scope: ' + scope + '\n  version: 1\n')
                    ws.journal('local ID allocator connected; existing numbers imported', evidence='orch.py id migrate')
                elif binding and not ws and not binding.exists():
                    state_io.atomic(binding, json.dumps({'scope': scope}).encode())
                result['scope'] = scope
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == 'reserve':
        print(' '.join(str(n) for n in result['numbers']))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_instructions(args):
    root = Path(args.repo).expanduser().resolve()
    if args.action == 'sync':
        if not args.text_file or not args.expected_claude or not args.expected_agents:
            raise project_instructions.InstructionError('sync requires --text-file and both expected hashes (or missing)')
        shared = Path(args.text_file).read_text(encoding='utf-8')
        result = project_instructions.sync(root, shared, args.expected_claude, args.expected_agents, args.apply)
    elif args.action == 'check':
        result = project_instructions.check_tree(root)
    else:
        result = project_instructions.status(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == 'check':
        return 0 if all(item['synchronized'] for item in result) else 1
    return 0


def registry(ws):
    p = ws.root / 'orchestration/sessions.json'
    return p, json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'version': 1, 'sessions': {}, 'outbox': {}}


def cmd_session(args):
    if args.action == 'capabilities':
        print(json.dumps(codex_transport.capabilities(), indent=2))
        return 0
    ws = workspace(args)
    p, data = registry(ws)
    if args.action == 'list':
        # Git is checked independently of messages and app-server history.
        for record in data['sessions'].values():
            record['current_branch'] = streams.current_branch(Path(record['worktree']))
            record['worktree_exists'] = Path(record['worktree']).is_dir()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    if not args.wp:
        raise streams.StreamError('session action requires --wp')
    if args.action == 'register':
        _, module, meta = api().wp_context(ws, args.wp)
        client = ws.config.get('client', 'claude')
        if not args.thread or not args.worktree:
            raise streams.StreamError('register requires --thread and --worktree')
        directory = Path(args.worktree).expanduser().resolve()
        if streams.common_dir(directory) != streams.common_dir(module.repo.local) or streams.current_branch(directory) != meta['branch']:
            raise streams.StreamError('registered worktree must belong to the WP repository and branch')
        if client == 'codex':
            thread = codex_transport.read_thread(args.thread)
            cwd = (thread.get('thread') or thread).get('cwd')
            if not cwd or Path(cwd).resolve() != directory:
                raise streams.StreamError('App Server thread cwd does not match worktree')
        record = {'program': ws.config['program'], 'module': module.id, 'wp': args.wp, 'client': client,
                  'thread_id': args.thread, 'worktree': str(directory), 'branch': meta['branch'],
                  'state': 'running'}
        with state_io.transaction(ws.root):
            p, data = registry(ws)
            previous = data['sessions'].get(args.wp)
            if previous and previous['state'] == 'running' and previous['thread_id'] != args.thread:
                raise streams.StreamError('previous writing session must be stopped before replacement')
            data['sessions'][args.wp] = record
            save(p, json.dumps(data, indent=2) + '\n')
        print(json.dumps(record, indent=2))
        return 0
    record = data['sessions'].get(args.wp)
    if not record:
        raise streams.StreamError('no registered session; use register after owner launch')
    if args.action == 'read':
        if record['client'] != 'codex':
            raise streams.StreamError('App Server reads Codex sessions only; Claude retains its native messaging')
        print(json.dumps(codex_transport.read_thread(record['thread_id'], include_turns=True), ensure_ascii=False, indent=2))
        return 0
    if args.action == 'stopped':
        if not args.evidence:
            raise streams.StreamError('stopped requires owner evidence that the writing process was stopped')
        with state_io.transaction(ws.root):
            p, data = registry(ws)
            data['sessions'][args.wp].update(state='stopped', stop_evidence=args.evidence)
            save(p, json.dumps(data, indent=2) + '\n')
        return 0
    if record['client'] != 'codex' or record['state'] != 'running':
        raise streams.StreamError('send requires a running Codex session')
    if not args.message_file or not args.request_id:
        raise streams.StreamError('send requires --message-file and stable --request-id')
    message = Path(args.message_file).read_text(encoding='utf-8')
    with state_io.transaction(ws.root):
        p, data = registry(ws)
        old = data['outbox'].get(args.request_id)
        entry = {'wp': args.wp, 'thread_id': record['thread_id'], 'message': message, 'delivered': False}
        if old and any(old[k] != entry[k] for k in ('wp', 'thread_id', 'message')):
            raise streams.StreamError('message request-id reused with different parameters')
        if old and old.get('delivered'):
            print(json.dumps(old, ensure_ascii=False, indent=2))
            return 0
        if old and old.get('sending'):
            raise streams.StreamError('delivery outcome unknown; read thread before explicit retry with a new request-id')
        entry['sending'] = True
        data['outbox'][args.request_id] = entry
        save(p, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    result = codex_transport.send(record['thread_id'], message)
    with state_io.transaction(ws.root):
        p, data = registry(ws)
        data['outbox'][args.request_id].update(result, sending=result.get('outcome_unknown', False))
        save(p, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['delivered']:
        print('OWNER HANDOVER:\n' + message)
    return 0 if result['delivered'] else 2


def cmd_client(args):
    ws = workspace(args)
    current = ws.config.get('client', 'claude')
    if args.action == 'status':
        print(current)
        return 0
    if not args.target or not args.stopped_evidence:
        raise streams.StreamError('switch requires --target and --stopped-evidence from the owner')
    if args.target == 'codex' and any(m.cloud for m in ws.streams()[1].values()):
        raise streams.StreamError('Codex v1 requires local sessions; keep Claude cloud on its existing path')
    with state_io.transaction(ws.root):
        ws = workspace(args)
        current = ws.config.get('client', 'claude')
        _, sessions = registry(ws)
        if any(s['state'] == 'running' for s in sessions['sessions'].values()):
            raise streams.StreamError('stop and record all old writing sessions before switching')
        if current == args.target:
            print('client unchanged')
            return 0
        # Preserve independent per-client package model assignments and all launch text/branches.
        models_path = ws.root / 'orchestration/client-models.json'
        models = json.loads(models_path.read_text(encoding='utf-8')) if models_path.exists() else {}
        for wp, r in ws.wp_rows().items():
            path = ws.wp_path(r['wp'])
            text = path.read_text(encoding='utf-8')
            header = streams.wp_header(text)
            values = models.setdefault(wp, {})
            values[current] = {key: header.get(next((x for x in streams.WP_LABELS[key] if x in header), ''), '—')
                               for key in ('model', 'effort', 'model_reason')}
            target = values.get(args.target, {})
            for key in ('model', 'effort', 'model_reason'):
                label = next((x for x in streams.WP_LABELS[key] if x in header), None)
                if label:
                    line = next(x for x in text.splitlines() if x.startswith('| ' + label + ' |'))
                    text = text.replace(line, '| ' + label + ' | ' + target.get(key, '—') + ' |', 1)
            save(path, text)
        save(models_path, json.dumps(models, ensure_ascii=False, indent=2) + '\n')
        p = ws.root / 'orch.yaml'
        text = p.read_text(encoding='utf-8')
        if re.search(r'(?m)^client:', text):
            text = re.sub(r'(?m)^client:.*$', 'client: ' + args.target, text)
        else:
            text = 'client: ' + args.target + '\n' + text
        save(p, text)
        ws = workspace(args)
        api().write_settings(ws, 'all')
        ws.journal('client changed ' + current + ' -> ' + args.target, evidence=args.stopped_evidence)
    print('client: ' + args.target + '; work packages and branches preserved')
    print(api().orchestrator_start(ws))
    return 0


def cmd_prepare(args):
    ws = workspace(args)
    if ws.config.get('client') != 'codex':
        raise streams.StreamError('prepare is for Codex worktrees')
    print(codex_adapter.prepare(ws, args.wp))
    return 0


def add_parsers(sub, common):
    p = sub.add_parser('id', parents=[common], help='durable local ID reservation or explicit legacy migration')
    p.add_argument('action', choices=('reserve', 'migrate'))
    p.add_argument('--scope', required=True, help='program | repo:PATH | explicit registered scope')
    p.add_argument('--namespace')
    p.add_argument('--request-id')
    p.add_argument('--count', type=int, default=1)
    p.add_argument('--seed', type=int)
    p.add_argument('--root')
    p.add_argument('--apply', action='store_true')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_id)
    p = sub.add_parser('instructions', parents=[common], help='module-owned paired project instructions')
    p.add_argument('action', choices=('status', 'check', 'sync'))
    p.add_argument('--repo', default='.')
    p.add_argument('--text-file')
    p.add_argument('--expected-claude')
    p.add_argument('--expected-agents')
    p.add_argument('--apply', action='store_true')
    p.set_defaults(func=cmd_instructions)
    p = sub.add_parser('session', parents=[common], help='independent owner-launched session registry and transport')
    p.add_argument('action', choices=('capabilities', 'list', 'register', 'read', 'send', 'stopped'))
    p.add_argument('--wp')
    p.add_argument('--thread')
    p.add_argument('--worktree')
    p.add_argument('--evidence')
    p.add_argument('--message-file')
    p.add_argument('--request-id')
    p.set_defaults(func=cmd_session)
    p = sub.add_parser('client', parents=[common], help='sequential client switch, never a mixed writer program')
    p.add_argument('action', choices=('status', 'switch'))
    p.add_argument('--target', choices=('claude', 'codex'))
    p.add_argument('--stopped-evidence')
    p.set_defaults(func=cmd_client)
    p = sub.add_parser('prepare', parents=[common], help='prepare a Codex Git worktree before owner launch')
    p.add_argument('wp')
    p.set_defaults(func=cmd_prepare)
