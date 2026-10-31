#!/usr/bin/env python3
"""Offline provenance/authorization regressions; no model, auth or network."""
import importlib.util
import io
import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('private_stdio',
    Path(__file__).with_name('probe-orchestrator-private-stdio.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class PrivateStdioTests(unittest.TestCase):
    def binding(self):
        b = probe.Binding('epoch')
        b.roles = {'coord': 'coordinator', 'module': 'module'}
        b.active = {'module': 'turn'}
        b.started = {('module', 'turn', 'call')}
        p = {'threadId': 'module', 'turnId': 'turn', 'callId': 'call',
             'tool': 'pepper_context', 'arguments': {}}
        return b, p

    def test_module_cannot_select_coordinator_even_with_schema_valid_arguments(self):
        b, p = self.binding()
        self.assertEqual(b.dispatch(p, 'epoch', 'coordinator_probe')['reason'], 'role_forbidden')
        self.assertEqual(b.handler_calls, 0)
        self.assertTrue(b.dispatch(p, 'epoch')['allowed'])
        self.assertEqual(b.handler_calls, 1)

    def test_argument_forgery_never_changes_native_subject(self):
        b, p = self.binding()
        p['arguments'] = {'threadId': 'coord', 'turnId': 'coord-turn', 'role': 'coordinator'}
        result = b.dispatch(p, 'epoch')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['role'], 'module')
        self.assertEqual(b.dispatch(p, 'epoch', 'coordinator_probe')['reason'], 'role_forbidden')
        self.assertEqual(b.handler_calls, 0)

    def test_epoch_replay_registration_and_active_item_are_required(self):
        b, p = self.binding()
        self.assertEqual(b.dispatch(p, 'old')['reason'], 'stale_epoch')
        self.assertFalse(b.dispatch({**p, 'threadId': 'unknown'}, 'epoch')['allowed'])
        self.assertFalse(b.dispatch({**p, 'turnId': 'unknown'}, 'epoch')['allowed'])
        self.assertFalse(b.dispatch({**p, 'callId': 'unknown'}, 'epoch')['allowed'])
        self.assertFalse(b.dispatch({**p, 'tool': 'shell'}, 'epoch')['allowed'])
        self.assertTrue(b.dispatch(p, 'epoch')['allowed'])
        self.assertEqual(b.dispatch(p, 'epoch')['reason'], 'replay')
        self.assertEqual(b.handler_calls, 1)

    def test_empty_evidence_exceptions_and_timeouts_are_not_pass(self):
        for report in ({}, {'error': 'TypeError'}, {'error': 'TimeoutError'},
                       {'shell_result': {'denied': True}}, {'resume': {'error': 'unsupported'}}):
            self.assertTrue(all(v != 'PASS' for v in probe.assess(report).values()))

    def test_editable_shell_json_without_native_command_cannot_prove_anything(self):
        report = {'shell_result': {'host_write_attempts': {'code': {'ok': False, 'errno': 30}},
            'isolated_import': {'returncode': 0, 'stdout': 'stdlib/json.py\n1\n'},
            'git': [{'returncode': 0}] * 5, 'setup': {'ok': True}}}
        v = probe.assess(report)
        self.assertEqual(v['host_integrity'], 'INCONCLUSIVE')
        self.assertEqual(v['Git_preparation'], 'INCONCLUSIVE')

    def test_exact_native_command_is_required(self):
        item = {'type': 'commandExecution', 'status': 'completed', 'exitCode': 0,
                'cwd': '/fixture/module', 'command': "/bin/bash -lc 'python3 -I -S /protected/probe.py'"}
        command = 'python3 -I -S /protected/probe.py'
        self.assertTrue(probe.exact_command(item, command, '/fixture/module'))
        for change in ({'cwd': '/other'}, {'exitCode': 1}, {'status': 'inProgress'},
                       {'command': command + '; echo forged'}, {'type': 'agentMessage'}):
            self.assertFalse(probe.exact_command({**item, **change}, command, '/fixture/module'))

    def test_pending_approval_is_never_authorization(self):
        v = probe.assess({'approval_observation': {'requests': [{'id': 1}],
            'still_pending': True, 'owner_approval_responses': []}})
        self.assertEqual(v['approvals'], 'PASS')
        self.assertEqual(v['Git_preparation'], 'INCONCLUSIVE')
        self.assertEqual(probe.assess({'approval_observation': {'owner_approval_responses': [{}]}})['approvals'], 'FAIL')

    def test_unknown_server_request_fails_closed_and_approval_gets_no_reply(self):
        messages = [{'id': 1, 'method': 'new/unknown/request', 'params': {}},
                    {'id': 2, 'method': 'item/commandExecution/requestApproval',
                     'params': {'threadId': 'module', 'turnId': 'turn'}}]
        client = probe.Client.__new__(probe.Client)
        client.process = SimpleNamespace(stdout=io.StringIO(''.join(json.dumps(m) + '\n' for m in messages)))
        client.epoch = 'epoch'; client.events = []; client.errors = []; client.approvals = []
        sent = []
        client.send = sent.append
        client.read()
        self.assertEqual(client.errors, [])
        self.assertEqual(sent, [{'id': 1, 'error': {'code': -32601, 'message': 'unsupported server request'}}])
        self.assertEqual(client.approvals, [messages[1]])

    def test_local_fixture_bootstrap_needs_no_model_or_user_repository(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'fixture'
            probe.fixture(root)
            self.assertTrue((root / 'remote.git' / 'HEAD').is_file())
            self.assertTrue((root / 'module' / '.git').is_file())
            self.assertTrue((root / 'coordinator' / '.git').is_file())
            self.assertTrue((root / 'module' / 'README').is_file())

    def test_committed_evidence_has_exact_native_command_and_source_provenance(self):
        evidence = Path(__file__).resolve().parent.parent / 'docs/validation/evidence/orchestrator-private-stdio-linux-20261030'
        r = json.loads((evidence / 'linux-private-stdio.json').read_text())
        self.assertEqual(r['environment']['owner_code_sha256'], hashlib.sha256(Path(probe.__file__).read_bytes()).hexdigest())
        module = r['threads']['module']
        matches = [e['message']['params']['item'] for e in r['events']
            if e['direction'] == 'native_to_owner' and e['message'].get('method') == 'item/completed'
            and e['message']['params'].get('threadId') == module['thread']['id']
            and e['message']['params'].get('turnId') == r['module_turn']
            and probe.exact_command(e['message']['params']['item'], r['shell_command'], module['cwd'])]
        self.assertEqual(len(matches), 1)
        self.assertEqual(json.loads(matches[0]['aggregatedOutput']), r['shell_result'])
        self.assertEqual(matches[0], r['native_shell_item'])
        self.assertEqual(r['shell_result']['caller'], module['thread']['id'])
        self.assertEqual(module['runtimeWorkspaceRoots'], [module['cwd']])
        self.assertTrue(module['sandbox']['networkAccess'])
        self.assertEqual(module['sandbox']['writableRoots'], [])
        self.assertEqual(module['approvalPolicy'], 'on-request')
        self.assertEqual(module['approvalsReviewer'], 'user')
        self.assertEqual(probe.assess(r), r['verdicts'])
        self.assertEqual(r['verdicts']['RPC_FD_isolation'], 'INCONCLUSIVE')
        self.assertEqual(r['verdicts']['Git_preparation'], 'BLOCKED_GIT_PREPARATION')
        self.assertTrue(r['cleanup']['auth_copy_removed'])

    def test_native_dynamic_lifecycle_and_pending_approval_have_owner_events(self):
        evidence = Path(__file__).resolve().parent.parent / 'docs/validation/evidence/orchestrator-private-stdio-linux-20261030'
        r = json.loads((evidence / 'linux-private-stdio.json').read_text())
        events = r['events']
        for call in r['calls_epoch1'] + r['calls_epoch2']:
            p = call['request']['params']
            starts = [e for e in events if e['epoch'] == call['decision'].get('epoch', r['calls_epoch1'][0]['decision']['epoch'])
                and e['message'].get('method') == 'item/started'
                and e['message']['params'].get('threadId') == p['threadId']
                and e['message']['params'].get('turnId') == p['turnId']
                and e['message']['params'].get('item', {}).get('id') == p['callId']]
            self.assertEqual(len(starts), 1)
            self.assertTrue(any(e['direction'] == 'native_to_owner' and e['message'] == call['request'] for e in events))
            self.assertTrue(any(e['message'].get('method') == 'item/completed'
                and e['message']['params'].get('item', {}).get('id') == p['callId'] for e in events))
        approvals = r['approval_observation']
        self.assertTrue(approvals['still_pending'])
        for request in approvals['requests']:
            self.assertTrue(any(e['direction'] == 'native_to_owner' and e['message'] == request for e in events))
            self.assertFalse(any(e['direction'] == 'owner_to_native' and e['epoch'] == r['calls_epoch2'][0]['decision']['epoch']
                and e['message'].get('id') == request['id'] for e in events))


if __name__ == '__main__':
    unittest.main()
