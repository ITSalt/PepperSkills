#!/usr/bin/env python3
"""Regressions for ordinary local continuation and effective launch permissions."""
import argparse
import contextlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, MagicMock

import autonomy as a
import autonomy_selftest
import codex_adapter
import codex_transport as transport
import orch


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = autonomy_selftest.AutonomyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.h = self.fixture.h
        self.root = self.fixture.root
        p = self.root / 'orch.yaml'
        s = p.read_text().replace('sandbox_mode: workspace-write', 'sandbox_mode: danger-full-access')
        s = s.replace('approval_policy: on-request', 'approval_policy: never')
        p.write_text(s + '\ncontinuation: auto\n')
        self.ws = orch.Workspace(self.root)

    def research(self, wp='WP-A-02'):
        p = self.ws.wp_path(self.ws.wp_rows()[wp]['wp'])
        s = p.read_text()
        pos = s.index('\n', s.index('\n|'))
        p.write_text(s[:pos] + '\n| Execution | research |' + s[pos:])
        self.ws = orch.Workspace(self.root)

    def test_permissions_capture_yolo_and_explicit_descriptor(self):
        home = self.h.root / 'capture'
        (home / 'sessions/2026/11/02').mkdir(parents=True)
        tid = '12345678-1234-1234-1234-123456789012'
        (home / 'sessions/2026/11/02' / ('rollout-' + tid + '.jsonl')).write_text(json.dumps({
            'type': 'turn_context', 'payload': {'approval_policy': 'never', 'sandbox_policy': {'type': 'danger-full-access'}}}) + '\n')
        with patch.dict(os.environ, {'CODEX_HOME': str(home), 'CODEX_THREAD_ID': tid}):
            self.assertEqual(codex_adapter.current_permissions(), {'approval_policy': 'never', 'sandbox_mode': 'danger-full-access'})
        flags = codex_adapter.descriptor(self.ws, 'a')['argv']
        self.assertIn('danger-full-access', flags)
        self.assertIn('never', flags)

    def test_announced_daemon_socket_for_newer_cli(self):
        reply = subprocess.CompletedProcess([], 0, json.dumps({'status': 'running', 'socketPath': '/tmp/local.sock', 'appServerVersion': '0.166.0'}))
        with patch.object(transport.subprocess, 'run', return_value=reply), patch.object(transport, 'command', return_value=['codex']):
            self.assertEqual(transport.daemon_endpoint(), 'unix:///tmp/local.sock')
        with patch.object(transport, 'daemon_endpoint', return_value='unix:///tmp/local.sock'), patch.object(transport, 'Server') as server:
            with transport.server(shared=True):
                pass
            server.assert_called_once_with(shared=True, remote='unix:///tmp/local.sock')

    def test_claim_from_main_module_checkout(self):
        self.fixture.extra_threads = {'new': {'id': 'new', 'createdAt': 2, 'cwd': str(self.fixture.repo), 'status': {'type': 'idle'}}}
        args = argparse.Namespace(workspace=str(self.root), action='recover', coordinator='new', pid=os.getpid(),
                                  evidence='owner selected this loaded module coordinator', previous_stopped='old chat idle and stopped writing')
        with contextlib.redirect_stdout(io.StringIO()):
            a.cmd_autonomy(args)
        self.assertEqual(a.registry(self.ws)[1]['coordinator']['thread_id'], 'new')

    def test_research_resumes_and_does_not_require_merge(self):
        self.research()
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'IN_PROGRESS')
        self.assertIn('continue_research', [x['kind'] for x in a.next_actions(orch.Workspace(self.root))['actions']])
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'ACCEPTED')
        actions = a.next_actions(orch.Workspace(self.root))['actions']
        self.assertTrue(any(x['kind'] == 'finalize_research' for x in actions))
        self.assertFalse(any(x.get('wp') == 'WP-A-02' and x['kind'] == 'deliver' for x in actions))

    def test_launch_records_turn_and_never_duplicates_unknown_start(self):
        self.research()
        api = MagicMock()
        api.call.side_effect = [{'thread': {'id': 'research-thread'}}, {'turn': {'id': 'research-turn'}}]
        with patch.object(transport, 'server') as server:
            server.return_value.__enter__.return_value = api
            result = a.launch_local(self.ws, 'WP-A-02', 'coord', 1)
        self.assertEqual(result['result'], 'started')
        self.assertEqual(api.call.call_args_list[0].args[1]['sandbox'], 'danger-full-access')
        self.assertEqual(api.call.call_args_list[0].args[1]['approvalPolicy'], 'never')
        with self.assertRaises(a.AutonomyError):
            a.launch_local(orch.Workspace(self.root), 'WP-A-02', 'coord', 1)
        self.fixture.extra_threads = {'research-thread': {'id': 'research-thread', 'status': {'type': 'idle'},
                                      'turns': [{'id': 'research-turn', 'status': 'completed'}]}}
        self.assertIn('review_research', [x['kind'] for x in a.next_actions(orch.Workspace(self.root))['actions']])

    def test_failed_start_keeps_reservation(self):
        self.research()
        with patch.object(transport, 'server') as server:
            server.return_value.__enter__.return_value.call.side_effect = transport.TransportError('lost connection')
            with self.assertRaises(transport.TransportError):
                a.launch_local(self.ws, 'WP-A-02', 'coord', 1)
        self.assertEqual(a.registry(self.ws)[1]['launches']['WP-A-02']['state'], 'preparing')
        with self.assertRaises(a.AutonomyError):
            a.launch_local(orch.Workspace(self.root), 'WP-A-02', 'coord', 1)

    def test_codex_init_has_no_claude_worktree_question(self):
        owner_rows = self.ws.table(self.ws.status, 'owner')[2]
        self.assertFalse(any('.worktreeinclude' in row['text'] for row in owner_rows))

    def test_research_dependency(self):
        self.research()
        p = self.ws.wp_path(self.ws.wp_rows()['WP-A-02']['wp'])
        text = p.read_text()
        text = re.sub(r'(?m)^\| Depends on \|.*$', '| Depends on | WP-A-01 |', text)
        p.write_text(text)
        self.h.cli('--workspace', self.root, 'set', 'WP-A-01', 'status', 'IN_PROGRESS')
        plan = a.next_actions(orch.Workspace(self.root))
        self.assertFalse(any(x.get('wp') == 'WP-A-02' and x['kind'] == 'continue_research' for x in plan['actions']))
        self.assertTrue(any(x.get('wp') == 'WP-A-02' for x in plan['waiting']))

    def test_research_parallel_limit(self):
        self.research()
        self.h.cli('--workspace', self.root, 'set', 'WP-A-01', 'status', 'IN_PROGRESS')
        _, data = a.registry(self.ws)
        data['autonomy']['max_parallel_sessions'] = 1
        a.persist(self.ws, data)
        actions = a.next_actions(orch.Workspace(self.root))['actions']
        self.assertFalse(any(x.get('wp') == 'WP-A-02' and x['kind'] == 'continue_research' for x in actions))

    def test_manual_mode_pauses_and_retains_records(self):
        with contextlib.redirect_stdout(io.StringIO()):
            a.cmd_autonomy(argparse.Namespace(workspace=str(self.root), action='configure', continuation='manual', evidence='owner chose manual'))
        self.assertFalse(a.registry(self.ws)[1]['autonomy']['enabled'])
        self.assertEqual(orch.Workspace(self.root).config['continuation'], 'manual')


if __name__ == '__main__':
    unittest.main()
