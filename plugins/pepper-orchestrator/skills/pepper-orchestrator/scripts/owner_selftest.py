#!/usr/bin/env python3
"""Private owner adapter regressions. Offline, no model or user configuration."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

import codex_transport
import owner_observation
import private_owner


class NativeAuthorizationTests(unittest.TestCase):
    def fixture(self, role='module'):
        owner = private_owner.PrivateOwner.__new__(private_owner.PrivateOwner)
        owner.api = SimpleNamespace(epoch='epoch', active={'module': 'turn'}, items={('module', 'turn', 'call')})
        owner.roles = {'module': {'role': role, 'thread': 'module'}}
        owner.seen = set()
        request = {'id': 1, 'method': 'item/tool/call', 'params': {'threadId': 'module',
            'turnId': 'turn', 'callId': 'call', 'tool': 'pepper_orchestrator', 'arguments': {'operation': 'context'}}}
        return owner, request

    def test_role_check_precedes_handlers_and_arguments_cannot_supply_actor(self):
        owner, request = self.fixture()
        request['params']['arguments'] = {'operation': 'next'}
        with self.assertRaisesRegex(private_owner.OwnerError, 'forbidden'): owner.authorize(request)
        request['params']['arguments'] = {'operation': 'context', 'threadId': 'coordinator'}
        with self.assertRaisesRegex(private_owner.OwnerError, 'actor IDs'): owner.authorize(request)
        self.assertEqual(owner.seen, set())

    def test_native_active_item_and_single_call_are_required(self):
        owner, request = self.fixture()
        owner.authorize(request)
        with self.assertRaisesRegex(private_owner.OwnerError, 'duplicate'): owner.authorize(request)
        owner, request = self.fixture(); request['params']['turnId'] = 'old'
        with self.assertRaisesRegex(private_owner.OwnerError, 'inactive'): owner.authorize(request)
        owner, request = self.fixture(); owner.api.items.clear()
        with self.assertRaisesRegex(private_owner.OwnerError, 'missing'): owner.authorize(request)

    def test_no_generic_method_path_shell_approval_or_owner_operations(self):
        for operation in ('merge', 'deploy', 'grant', 'approve', 'spawn', 'thread/start', 'shell', 'writeFile'):
            owner, request = self.fixture('coordinator')
            request['params']['arguments'] = {'operation': operation}
            with self.assertRaises(private_owner.OwnerError): owner.authorize(request)

    def test_native_permission_entries_cannot_add_reads_network_or_other_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            root = str(Path(temp).resolve())
            native = {'network': None, 'fileSystem': {'read': None, 'write': [root],
                'entries': [{'access': 'write', 'path': {'type': 'path', 'path': root}}]}}
            self.assertEqual(private_owner.permission_roots(native), [root])
            native['fileSystem']['entries'].append({'access': 'read', 'path': {'type': 'path', 'path': root}})
            with self.assertRaises(private_owner.OwnerError): private_owner.permission_roots(native)
            for profile in ({'network': {'enabled': True}, 'fileSystem': {'write': [root]}},
                            {'fileSystem': {'entries': [{'access': 'write', 'path': {'type': 'glob_pattern', 'pattern': '**'}}]}}):
                with self.assertRaises(private_owner.OwnerError): private_owner.permission_roots(profile)

    def test_native_interruption_invalidates_inflight_authority(self):
        api = SimpleNamespace(epoch='epoch', active={'thread': 'turn'}, items={('thread', 'turn', 'call')})
        with codex_transport.owner_transport(api), codex_transport.native_operation('thread', 'turn', 'call'):
            api.active.clear()
            with self.assertRaisesRegex(codex_transport.TransportError, 'interrupted'):
                codex_transport.check_native_operation()


@unittest.skipIf(os.name == 'nt', 'private owner mode is Linux/macOS; native Windows core is separate')
class OwnerObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Fixture'); self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'file').write_text('one\n')
        self.git('add', '.'); self.git('commit', '-m', 'fixture')

    def git(self, *args):
        p = subprocess.run(['git', '-C', str(self.repo), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def test_host_status_never_runs_configured_filter_or_fsmonitor(self):
        marker = self.root / 'HOST_EXECUTED'
        evil = self.root / 'evil.py'
        evil.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        command = '"' + sys.executable + '" "' + str(evil) + '"'
        self.git('config', 'filter.fixture.clean', command)
        self.git('config', 'core.fsmonitor', command)
        (self.repo / '.gitattributes').write_text('file filter=fixture\n')
        (self.repo / 'file').write_text('two\n')
        observer = owner_observation.GitObserver(self.root / 'observer'); observer.register(self.repo)
        result = observer(self.repo, 'status', '--porcelain')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('file', result.stdout)
        self.assertFalse(marker.exists())

    def test_writable_gitfile_and_commondir_do_not_select_host_repository(self):
        work = self.root / 'module'
        self.git('worktree', 'add', '-b', 'module', str(work))
        observer = owner_observation.GitObserver(self.root / 'observer'); pin = observer.register(work)
        (work / '.git').write_text('gitdir: /nonexistent/untrusted\n')
        (pin['private'] / 'commondir').write_text('/nonexistent/untrusted\n')
        result = observer(work, 'branch', '--show-current')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'module')
        result = observer(work, 'status', '--porcelain')
        self.assertEqual(result.returncode, 0, result.stderr)
        for args in (('rev-parse', '--git-dir'), ('rev-parse', '--path-format=absolute', '--git-dir')):
            self.assertEqual(observer(work, *args).stdout.strip(), str(pin['private']))

    def test_config_drift_includes_and_implicit_fetch_are_rejected(self):
        observer = owner_observation.GitObserver(self.root / 'observer'); observer.register(self.repo)
        for args in (('fetch', 'origin'), ('switch', 'main'), ('branch', '-D', 'main'),
                     ('remote', 'set-url', 'origin', 'example.invalid')):
            with self.assertRaises(owner_observation.ObservationError): observer(self.repo, *args)
        self.git('config', 'core.fsmonitor', 'changed')
        with self.assertRaises(owner_observation.ObservationError): observer(self.repo, 'status', '--porcelain')
        self.git('config', 'include.path', 'untrusted-config')
        with self.assertRaises(owner_observation.ObservationError): observer.register(self.repo)
        self.git('config', '--unset', 'include.path')
        self.git('config', 'remote.origin.promisor', 'true')
        with self.assertRaises(owner_observation.ObservationError): observer.register(self.repo)


class PrivateTransportTests(unittest.TestCase):
    def test_queue_add_ack_is_enough_and_unknown_add_is_not_retried(self):
        api = codex_transport.PrivateServer.__new__(codex_transport.PrivateServer)
        api.active = {}; api.registered_threads = {'thread'}
        calls = []
        def call(method, params):
            calls.append(method)
            if method == 'thread/read': return {'thread': {'status': {'type': 'idle'}}}
            raise codex_transport.TransportError('lost add reply')
        api.call = call
        self.assertTrue(api.enqueue('thread', 'TASK')['outcome_unknown'])
        self.assertEqual(calls, ['thread/read', 'thread/queue/add'])
        def acknowledged(method, params):
            calls.append(method)
            return {'thread': {'status': {'type': 'idle'}}} if method == 'thread/read' else {'queuedSubmission': {'id': 'submission'}}
        calls.clear(); api.call = acknowledged
        self.assertTrue(api.enqueue('thread', 'TASK')['queued'])
        self.assertEqual(calls, ['thread/read', 'thread/queue/add'])
        api.call = lambda method, params: {'thread': {'status': {'type': 'active'}}}
        self.assertFalse(api.enqueue('thread', 'TASK').get('queued'))

    def test_persistent_transport_does_not_reuse_old_compaction_completion(self):
        old = {'method': 'item/completed', 'params': {'threadId': 'thread',
            'item': {'id': 'old', 'type': 'contextCompaction'}}}
        api = SimpleNamespace(events=[old])
        def call(method, params):
            return {'thread': {'status': {'type': 'idle'}}}
        api.call = call
        with codex_transport.owner_transport(api):
            self.assertFalse(codex_transport.compact('thread', timeout=.01)['completed'])

    @unittest.skipIf(os.name == 'nt', 'POSIX executable protocol fixture; native Windows smoke is separate')
    def test_reader_multiplexes_concurrent_rpc_and_preserves_pending_native_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            native = root / 'native'
            native.write_text('''#!/usr/bin/env python3
import sys,json
if sys.argv[1:]==['--version']:
 print('codex-cli 0.165.0');raise SystemExit(0)
echoes=[]
for line in sys.stdin:
 r=json.loads(line); method=r.get('method'); p=r.get('params',{})
 if not method or 'id' not in r:continue
 def send(v):print(json.dumps(v),flush=True)
 if method=='echo':
  echoes.append(r)
  if len(echoes)==8:
   for e in reversed(echoes):send({'id':e['id'],'result':e['params']})
  continue
 if method=='probe':
  send({'method':'turn/started','params':{'threadId':'module','turn':{'id':'turn'}}})
  send({'method':'item/started','params':{'threadId':'module','turnId':'turn','item':{'type':'dynamicToolCall','id':'call'}}})
  send({'id':77,'method':'item/tool/call','params':{'threadId':'module','turnId':'turn','callId':'call','tool':'pepper_next','arguments':{}}})
  send({'id':78,'method':'item/commandExecution/requestApproval','params':{'threadId':'module','turnId':'turn'}})
 config={'approval_policy':'on-request','approvals_reviewer':'user','sandbox_mode':'workspace-write',
  'sandbox_workspace_write':{'network_access':True},'features':dict.fromkeys(['apps','plugins','remote_plugin','browser_use',
  'computer_use','image_generation','multi_agent','hooks','shell_snapshot','daemon_auto_start'],False)|{'skip_host_skill_discovery':True,'request_permissions_tool':True}}
 result={'status':'disabled'} if method=='remoteControl/status/read' else {'data':[]} if method=='mcpServerStatus/list' else {'config':config} if method=='config/read' else {}
 send({'id':r['id'],'result':result})
''')
            native.chmod(0o700)
            api = codex_transport.PrivateServer(native, root, root, root / 'events.jsonl')
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda n: api.call('echo', {'number': n}, timeout=5), range(8)))
                self.assertEqual(results, [{'number': n} for n in range(8)])
                self.assertEqual(api.call('probe', {}), {})
                request = api.requests.get(timeout=5)
                self.assertEqual(request['params']['callId'], 'call')
                self.assertIn(78, api.approvals)
                self.assertEqual(api.active, {'module': 'turn'})
                self.assertIn(('module', 'turn', 'call'), api.items)
                with codex_transport.owner_transport(api):
                    with codex_transport.server(shared=True) as same:
                        self.assertIs(same, api)
                    self.assertFalse(api.closed)
            finally:
                api.close()
            records = [json.loads(s) for s in (root / 'events.jsonl').read_text().splitlines()]
            self.assertFalse(any(e['direction'] == 'owner_to_native' and e['message'].get('id') == 78 for e in records))
            self.assertIsNotNone(api.proc.returncode)


if __name__ == '__main__':
    unittest.main()
