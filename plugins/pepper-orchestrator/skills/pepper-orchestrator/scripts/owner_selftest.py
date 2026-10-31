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
from unittest.mock import patch
from types import SimpleNamespace

import codex_transport
import owner_observation
import private_owner
import owner_main
import autonomy
import state_io
import zipfile


class OwnerArchiveTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX owner lock; live Windows mode is unsupported')
    def test_path_aliases_and_program_identity_prevent_second_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); program = root / 'program'; program.mkdir()
            alias = root / 'alias'; alias.symlink_to(program, target_is_directory=True)
            self.assertTrue(owner_main.within(alias / 'future-state', program))
            with patch.object(owner_main.Path, 'home', return_value=root):
                with owner_main.program_mutex(program):
                    with self.assertRaisesRegex(RuntimeError, 'another private owner'):
                        with owner_main.program_mutex(alias):
                            self.fail('same program acquired twice through an alias')
                with owner_main.program_mutex(alias):
                    pass
            (program / '.git').mkdir()
            with self.assertRaisesRegex(RuntimeError, 'outside Git'):
                owner_main.outside_repository(alias)

    def test_archive_hash_installed_bytes_and_no_extra_imports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); skill = root / 'skill'; skill.mkdir()
            archive = root / 'candidate.zip'
            files = {n: b'# verified fixture\n' for n in ('scripts/orch.py', 'scripts/owner_main.py',
                'scripts/private_owner.py', 'scripts/module_prepare.py', 'scripts/codex_transport.py')}
            files.update({f'references/{n}.md': b'fixture\n' for n in range(5)})
            with zipfile.ZipFile(archive, 'w') as z:
                for name, data in files.items():
                    z.writestr('pepper-orchestrator/' + name, data)
                    target = skill / name; target.parent.mkdir(exist_ok=True); target.write_bytes(data)
            sha = owner_main.file_sha(archive)
            owner_main.verify_archive(archive, sha, skill)
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                owner_main.verify_archive(archive, '0' * 64, skill)
            extra = skill / 'scripts/subprocess.py'; extra.write_text('raise RuntimeError("unverified import")\n')
            with self.assertRaisesRegex(RuntimeError, 'unverified'):
                owner_main.verify_archive(archive, sha, skill)
            extra.unlink(); (skill / 'scripts/orch.py').write_text('# modified\n')
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                owner_main.verify_archive(archive, sha, skill)

    @unittest.skipIf(os.name == 'nt', 'private owner live mode is Linux/macOS')
    def test_recovery_requires_positive_exit_same_code_config_and_known_terminal_lifetime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); workspace = root / 'workspace'; workspace.mkdir()
            (workspace / 'orch.yaml').write_text('program: fixture\n')
            native = root / 'native'; native.write_bytes(b'fixture native')
            home = root / 'codex-home'; home.mkdir()
            config = home / 'config.toml'
            config.write_text(owner_main.CONFIG + '\n[projects."/fixture"]\ntrust_level = "trusted"\n')
            log = root / 'events.jsonl'; log.write_text('')
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            try:
                saved = {'workspace': str(workspace.resolve()), 'process': autonomy.process_identity(child.pid),
                    'native_sha256': codex_transport.file_sha256(native),
                    'codex_home': str(home), 'isolated_config_sha256': state_io.digest(config), 'actor_roots': [], 'roles': {},
                    'code_sha256': {p.name: state_io.digest(p) for p in Path(private_owner.__file__).parent.glob('*.py')},
                    'config_sha256': state_io.digest(workspace / 'orch.yaml'), 'event_log': str(log)}
                (root / 'roles.json').write_text(json.dumps(saved))
                with self.assertRaisesRegex(private_owner.OwnerError, 'positively stopped'):
                    private_owner.PrivateOwner.validate_recovery(root, native, workspace)
            finally:
                child.terminate(); child.wait(timeout=5)
            event = {'direction': 'native_to_owner', 'message': {'method': 'item/started', 'params': {
                'threadId': 'module', 'item': {'type': 'commandExecution', 'id': 'command', 'status': 'inProgress', 'exitCode': None}}}}
            log.write_text(json.dumps(event) + '\n')
            with self.assertRaisesRegex(private_owner.OwnerError, 'unknown lifetime'):
                private_owner.PrivateOwner.validate_recovery(root, native, workspace)
            event['message']['method'] = 'item/completed'; event['message']['params']['item'].update(status='completed', exitCode=0)
            log.write_text(json.dumps(event) + '\n')
            self.assertEqual(private_owner.PrivateOwner.validate_recovery(root, native, workspace)['process'], saved['process'])
            config.write_text(config.read_text() + '# even an unrelated post-bootstrap change\n')
            with self.assertRaisesRegex(private_owner.OwnerError, 'native configuration changed'):
                private_owner.PrivateOwner.validate_recovery(root, native, workspace)
            config.write_text(owner_main.CONFIG + '\n[projects."/fixture"]\ntrust_level = "trusted"\n')
            event['message']['params']['item'].update(status='failed', exitCode=1)
            log.write_text(json.dumps(event) + '\n')
            self.assertEqual(private_owner.PrivateOwner.validate_recovery(root, native, workspace)['process'], saved['process'])
            event['message']['params']['item']['exitCode'] = None
            log.write_text(json.dumps(event) + '\n')
            with self.assertRaisesRegex(private_owner.OwnerError, 'unknown lifetime'):
                private_owner.PrivateOwner.validate_recovery(root, native, workspace)
            (workspace / 'orch.yaml').write_text('program: changed\n')
            with self.assertRaisesRegex(private_owner.OwnerError, 'configuration changed'):
                private_owner.PrivateOwner.validate_recovery(root, native, workspace)


class NativeAuthorizationTests(unittest.TestCase):
    def test_post_bootstrap_native_config_drift_blocks_before_workspace_operations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'orch.yaml').write_text('fixture')
            config = root / 'config.toml'; config.write_text(owner_main.CONFIG)
            owner = private_owner.PrivateOwner.__new__(private_owner.PrivateOwner)
            owner.workspace = root; owner.config = state_io.digest(root / 'orch.yaml')
            owner.api = SimpleNamespace(home=root, closed=False, failure=None)
            owner.isolated_config = state_io.digest(config)
            config.write_text(owner_main.CONFIG + '# unconfirmed drift\n')
            with self.assertRaisesRegex(private_owner.OwnerError, 'native config drift'):
                owner.workspace_now()

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
    def test_effective_config_cannot_hide_an_active_project_layer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            api = codex_transport.PrivateServer.__new__(codex_transport.PrivateServer)
            api.actor_roots = {str(root)}
            cfg = {'approval_policy':'on-request','approvals_reviewer':'user','sandbox_mode':'workspace-write',
                'sandbox_workspace_write':{'network_access':True}, 'project_root_markers':[],
                'projects':{str(root):{'trust_level':'untrusted'}},
                'features':dict.fromkeys(('apps','plugins','remote_plugin','browser_use','computer_use',
                    'image_generation','multi_agent','hooks','shell_snapshot','daemon_auto_start'),False)
                    | {'skip_host_skill_discovery':True,'request_permissions_tool':True}}
            layer = {'name':{'type':'project'}, 'config':{'mcp_servers':{'untrusted':{'command':'never-run'}}},
                'disabledReason':'explicitly untrusted actor root'}
            calls=[]
            def call(method, params):
                calls.append(method)
                return {'config':cfg,'layers':[layer]} if method == 'config/read' else {'thread':{'id':'fixture'}}
            api.call=call
            api.start_thread(root,'fixture',[], 'fixture')
            self.assertEqual(calls, ['config/read','thread/start'])
            calls.clear(); layer['disabledReason']=None
            with self.assertRaisesRegex(codex_transport.TransportError,'must remain disabled'):
                api.start_thread(root,'fixture',[], 'fixture')
            self.assertEqual(calls,['config/read'])
            layer['disabledReason']='untrusted'; cfg['projects'][str(root)]['trust_level']='trusted'
            with self.assertRaisesRegex(codex_transport.TransportError,'isolation flags'):
                api.check_configuration(root)

    def test_undeclared_cwd_is_refused_before_native_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); api=codex_transport.PrivateServer.__new__(codex_transport.PrivateServer)
            api.actor_roots=set()
            api.call=lambda *a: self.fail('native loading must not be reached')
            with self.assertRaisesRegex(codex_transport.TransportError,'declared actor root'):
                api.start_thread(root,'fixture',[], 'fixture')

    def test_unfinished_commands_prevent_idle_observation_and_compaction(self):
        api = codex_transport.PrivateServer.__new__(codex_transport.PrivateServer)
        api.commands = {('thread', 'command'): {'status': 'completed', 'exitCode': None}}
        api.active = {}; api.events = []
        api.call = lambda *a, **k: {'thread': {'status': {'type': 'idle'}}}
        with codex_transport.owner_transport(api):
            self.assertEqual(codex_transport.read_thread('thread')['thread']['status']['type'], 'active')
            with self.assertRaisesRegex(codex_transport.TransportError, 'unresolved'):
                codex_transport.compact('thread')
        api.commands[('thread', 'command')]['exitCode'] = 0
        self.assertEqual(api.running_commands('thread'), [])
        api.commands[('thread', 'command')].update(status='failed', exitCode=1)
        self.assertEqual(api.running_commands('thread'), [])
        api.commands[('thread', 'command')]['exitCode'] = None
        self.assertTrue(api.running_commands('thread'))

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
  'sandbox_workspace_write':{'network_access':True},'project_root_markers':[], 'projects':{__import__('os').getcwd():{'trust_level':'untrusted'}},'features':dict.fromkeys(['apps','plugins','remote_plugin','browser_use',
  'computer_use','image_generation','multi_agent','hooks','shell_snapshot','daemon_auto_start'],False)|{'skip_host_skill_discovery':True,'request_permissions_tool':True}}
 result={'status':'disabled'} if method=='remoteControl/status/read' else {'data':[]} if method=='mcpServerStatus/list' else {'config':config} if method=='config/read' else {}
 send({'id':r['id'],'result':result})
''')
            native.chmod(0o700)
            api = codex_transport.PrivateServer(native, root, root, root / 'events.jsonl', actor_roots=[root])
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
