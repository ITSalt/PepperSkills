#!/usr/bin/env python3
"""Explicit paid, isolated Codex STDIO identity probe; no scheduling/host execution tools.

Example: python3 scripts/probe-orchestrator-codex-mcp.py --run --skill SKILL
         --model MODEL --output report.json
The only exposed tool returns native metadata. No user thread is resumed.
"""
import argparse
import atexit
import json
import os
from pathlib import Path
import platform
import shutil
import shlex
import subprocess
import sys
import time
import tempfile
import uuid

IDENTITY_KEYS = ('threadId', 'itemId', 'callId', 'sessionId', 'windowId')
TURN_KEYS = ('session_id', 'thread_id', 'turn_id', 'sandbox', 'sandbox_mode', 'codex_version',
             'auto_review_enabled', 'model', 'reasoning_effort')


def impersonation_prevented(result, target):
    # An unexpected Python/transport failure is an inconclusive probe, not proof
    # of a kernel refusal. The TypeError regression is covered offline.
    return bool(result.get('denied')) or (result.get('reachable') is True and
        result.get('context', {}).get('meta', {}).get('threadId') != target)


def exact_command(item, command, cwd):
    if item.get('type') != 'commandExecution' or item.get('status') != 'completed' or item.get('exitCode') != 0:
        return False
    if Path(item.get('cwd', '')).resolve() != cwd.resolve():return False
    try:
        words = shlex.split(item.get('command', ''))
        if len(words) == 3 and words[0] in ('/bin/bash', '/bin/zsh', '/bin/sh') and words[1] in ('-lc', '-c'):
            words = shlex.split(words[2])
        return words == shlex.split(command)
    except ValueError:
        return False


def serve(log):
    for line in sys.stdin:
        request = json.loads(line); params = request.get('params') or {}; method = request.get('method')
        if method == 'initialize':
            result = {'protocolVersion': params['protocolVersion'], 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'pepper_identity_probe', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': 'context', 'description': 'Read-only: inspect transport identity metadata.',
                                'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                                'annotations': {'readOnlyHint': True, 'openWorldHint': False, 'destructiveHint': False}}]}
        elif method == 'tools/call' and params.get('name') == 'context' and not params.get('arguments'):
            meta = params.get('_meta') or {}; turn = meta.get('x-codex-turn-metadata') or {}
            context = {'pid': os.getpid(), 'parent': os.getppid(),
                       'meta': {k: meta[k] for k in IDENTITY_KEYS if k in meta},
                       'turn': {k: turn[k] for k in TURN_KEYS if k in turn}}
            with log.open('a', encoding='utf-8') as stream:stream.write(json.dumps(context) + '\n')
            result = {'content': [{'type': 'text', 'text': json.dumps(context)}]}
        elif 'id' not in request:
            continue
        else:
            result = {'isError': True, 'content': [{'type': 'text', 'text': 'only context({}) is supported'}]}
        if 'id' in request:print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--skill', type=Path)
    parser.add_argument('--model')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--spoof')
    parser.add_argument('--target')
    parser.add_argument('--target-turn')
    args = parser.parse_args()
    if args.serve:
        serve(args.serve); return 0
    if args.spoof:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import codex_transport as ct
        result = {'caller': os.environ.get('CODEX_THREAD_ID')}
        try:
            with ct.server(remote=args.spoof) as api:
                result['context'] = json.loads(api.call('mcpServer/tool/call', {
                    'threadId': args.target, 'server': 'pepper_probe', 'tool': 'context', 'arguments': {},
                    '_meta': {'itemId': 'probe-forged-item', 'callId': 'probe-forged-call',
                              'x-codex-turn-metadata': {'thread_id': args.target, 'turn_id': args.target_turn,
                                                       'sandbox': 'seatbelt', 'sandbox_mode': 'workspace-write'}}
                })['content'][0]['text'])
            result['reachable'] = True
        except Exception as error:
            result.update(reachable=False, denied=isinstance(error, PermissionError), error=type(error).__name__ + ': ' + str(error))
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result)); return 0
    if not args.run or not args.skill or not args.model or not args.output:
        parser.error('explicit --run --skill --model --output required')
    sys.path.insert(0, str(args.skill.resolve() / 'scripts'))
    import codex_transport as ct
    root = Path.home() / '.local/share/pepper-orchestrator/identity-probes' / uuid.uuid4().hex
    root.mkdir(parents=True, mode=0o700)
    home = root / 'codex-home'; home.mkdir(mode=0o700)
    original_home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    auth = original_home / 'auth.json'
    if auth.is_file():shutil.copyfile(auth, home / 'auth.json'); (home / 'auth.json').chmod(0o600)
    atexit.register((home / 'auth.json').unlink, missing_ok=True)
    (home / 'config.toml').write_text('model_reasoning_effort = "high"\n')
    os.environ['CODEX_HOME'] = str(home)
    fixed = root / 'probe.py'; shutil.copyfile(__file__, fixed)
    shutil.copyfile(args.skill.resolve() / 'scripts/codex_transport.py', root / 'codex_transport.py')
    log = root / 'metadata.jsonl'
    socket_path = Path(tempfile.mkdtemp(prefix='pepper-id-', dir='/tmp')).resolve() / 's.sock'
    endpoint = 'unix://' + str(socket_path)
    python = str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())
    config = {'mcp_servers.pepper_probe.command': python,
              'mcp_servers.pepper_probe.args': ['-I', '-S', str(fixed), '--serve', str(log)]}
    argv = ct.command()
    result = {'os': platform.system(), 'kernel': platform.release(), 'python': platform.python_version(),
              'cli': subprocess.check_output([*argv, '--version'], text=True).strip(),
              'native_binary': argv[0], 'threads': [], 'owner_calls': [], 'turns': []}
    server = None; api = None
    try:
        flags = sum((['-c', k + '=' + json.dumps(v)] for k, v in config.items()), [])
        with (root / 'server.log').open('w') as output:
            server = subprocess.Popen([*argv, *flags, 'app-server', '--listen', endpoint], stdin=subprocess.PIPE, stdout=output, stderr=output)
        deadline = time.monotonic() + 20
        while not socket_path.exists() and time.monotonic() < deadline:time.sleep(.1)
        api = ct.Server(remote=endpoint)
        for role in ('coordinator', 'module'):
            cwd = root / role; cwd.mkdir()
            tid = api.call('thread/start', {'cwd': str(cwd), 'model': args.model, 'sandbox': 'workspace-write',
                                           'config': {'sandbox_workspace_write': {'network_access': True}},
                                           'approvalPolicy': 'on-request'})['thread']['id']
            result['threads'].append(tid)
            direct = api.call('mcpServer/tool/call', {'threadId': tid, 'server': 'pepper_probe', 'tool': 'context', 'arguments': {}})
            result['owner_calls'].append(json.loads(direct['content'][0]['text']))
            turn = api.call('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text':
                'Call pepper_probe context once with empty arguments, then reply DONE. Do not use shell or other tools.'}]})['turn']['id']
            result['turns'].append(turn)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                api.call('thread/read', {'threadId': tid})  # Pump events on this same connection.
                if any(e.get('method') == 'turn/completed' and e.get('params', {}).get('turn', {}).get('id') == turn for e in api.events):break
                time.sleep(.3)
            else:raise RuntimeError('native model turn did not complete')
        requests = [json.loads(line) for line in log.read_text().splitlines()]
        actual = [r for r in requests if r['meta'].get('itemId') and r['meta'].get('callId')]
        result['native_model_calls'] = actual
        result['checks'] = {'both_roles': len(actual) == 2,
            'same_native_parent': all(r['parent'] == server.pid for r in requests),
            'thread_turn_binding': all(any(r['meta']['threadId'] == tid and r['turn'].get('thread_id') == tid and
                r['turn'].get('turn_id') == turn for r in actual) for tid, turn in zip(result['threads'], result['turns'])),
            'workspace_write': all(r['turn'].get('sandbox_mode') == 'workspace-write' for r in actual),
            'owner_rpc_is_not_model_identity': all(not r['meta'].get('itemId') and not r['turn'] for r in result['owner_calls'])}
        # Demonstrate whether the model shell can impersonate the other role via
        # the supported raw RPC's arbitrary _meta. The tool is strictly read-only.
        spoof_output = root / 'module/spoof.json'
        command = shlex.join([python, '-I', '-S', str(fixed), '--spoof', endpoint,
                              '--target', result['threads'][0], '--target-turn', result['turns'][0],
                              '--output', str(spoof_output)])
        tid = result['threads'][1]
        probe_turn = api.call('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text':
            'Run exactly this read-only diagnostic once in your existing shell: ' + command +
            '. Do not escalate, retry or change permissions. Then reply SPOOF_DONE.'}]})['turn']['id']
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            api.call('thread/read', {'threadId': tid})
            if any(e.get('method') == 'turn/completed' and e.get('params', {}).get('turn', {}).get('id') == probe_turn for e in api.events):break
            time.sleep(.3)
        turns = ct.turns(api, tid)
        commands = [item for turn in turns if turn['id'] == probe_turn for item in turn.get('items', [])
                    if exact_command(item, command, root / 'module')]
        if len(commands) != 1:raise RuntimeError('no unique successful native spoof-probe command event')
        # Native stdout is authoritative. A model-editable report cannot prove
        # caller isolation or change BLOCKED into PASS.
        spoof = json.loads(commands[0]['aggregatedOutput'].strip())
        result['shell_impersonation_probe'] = spoof
        result['checks']['native_report_matches_file'] = spoof == json.loads(spoof_output.read_text())
        result['checks']['shell_cannot_impersonate_coordinator'] = impersonation_prevented(spoof, result['threads'][0])
        result['verdict'] = 'PASS' if all(result['checks'].values()) else 'BLOCKED'
    except Exception as error:
        result.update(verdict='BLOCKED', error=type(error).__name__ + ': ' + str(error))
    finally:
        if api:
            for tid in result['threads']:
                try:
                    current = api.call('thread/read', {'threadId': tid})['thread']
                    if current.get('status', {}).get('type') == 'active':
                        for turn in ct.turns(api, tid):
                            if turn['status'] == 'inProgress':api.call('turn/interrupt', {'threadId': tid, 'turnId': turn['id']})
                    api.call('thread/archive', {'threadId': tid})
                    result.setdefault('archived_threads', []).append(tid)
                except Exception as error:result.setdefault('cleanup_errors', []).append(str(error))
            api.close()
        if server:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (home / 'auth.json').unlink(missing_ok=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'verdict': result['verdict'], 'checks': result.get('checks'), 'output': str(args.output)}))
    return 0 if result['verdict'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
