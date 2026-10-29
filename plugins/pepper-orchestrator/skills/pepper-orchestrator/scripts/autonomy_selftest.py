#!/usr/bin/env python3
"""Offline regressions for reservation truth, reuse, fencing and quiet observation."""
import argparse
import concurrent.futures
import contextlib
import io
import json
import os
import queue
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import autonomy as a
import codex_transport
import orch
import runtime_commands as runtime
import runtime_selftest
import state_io
import streams


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        self.h = runtime_selftest.RuntimeTests(); self.h.setUp(); self.addCleanup(self.h.tearDown)
        self.repo, self.root = self.h.fixture('codex')
        self.h.cli('--workspace', self.root, 'new-wp', 'a', 'first')
        self.h.cli('--workspace', self.root, 'new-wp', 'a', 'second')
        self.ws = orch.Workspace(self.root)
        _, module, meta = orch.wp_context(self.ws, 'WP-A-01')
        self.wt = self.h.root / 'writer'
        self.h.git(self.repo, 'worktree', 'add', '-b', meta['branch'], self.wt, 'main')
        a.codex_adapter.prepare(self.ws, 'WP-A-01')
        self.sha = self.h.git(self.wt, 'rev-parse', 'HEAD')
        self.h.cli('--workspace', self.root, 'set', 'WP-A-01', 'status', 'DONE')
        self.h.cli('--workspace', self.root, 'set', 'WP-A-01', 'pr', 'https://github.com/example/repo/pull/1')
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'READY')
        self.ws = orch.Workspace(self.root)
        self.ws.journal('WP-A-01: accepted at ' + self.sha, wp='WP-A-01', evidence='report fixture')
        self.thread = {'id': 'module-a', 'createdAt': 1, 'cwd': str(self.wt), 'model': 'fixture',
                       'reasoningEffort': 'high', 'status': {'type': 'idle'}, 'turns': []}
        self.patches = [patch.object(a, 'observe_thread', side_effect=self.live),
                        patch.object(a, 'pr_observation', return_value={'state': 'MERGED', 'headRefOid': self.sha,
                                                                      'mergeCommit': {'oid': self.sha}}),
                        patch.object(runtime, 'check_capabilities', return_value={'available': True, 'queue': True}),
                        patch.object(a, 'start_watcher', return_value={'result': 'fixture_watcher'})]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        env = patch.dict(os.environ, {'CODEX_THREAD_ID': 'module-a'})
        env.start(); self.addCleanup(env.stop)
        a.attach(self.ws, argparse.Namespace(wp='WP-A-01', thread='module-a', worktree=str(self.wt),
                                             pid=os.getpid(), evidence='fixture process binding'))
        _, data = a.registry(self.ws)
        data['autonomy']['enabled'] = True
        data['coordinator'] = {'thread_id': 'coord', 'generation': 1, 'process': a.process_identity(os.getpid()), 'released': False}
        data['generation'] = 1
        a.persist(self.ws, data)

    def live(self, ws, tid, history=False):
        if tid in getattr(self, 'extra_threads', {}):
            return self.extra_threads[tid]
        return json.loads(json.dumps(self.thread if tid == 'module-a' else {
            'id': 'coord', 'createdAt': 1, 'cwd': str(self.root), 'status': {'type': 'idle'}, 'turns': []}))

    def reserve(self):
        return a.reserve(orch.Workspace(self.root), 'WP-A-02', 'coord', 1)

    def assigned(self, state='queued'):
        assigned = self.reserve(); self.assertEqual(assigned['result'], 'assigned')
        aid = assigned['assignment_id']; _, data = a.registry(self.ws)
        data['assignments'][aid]['state'] = state; a.persist(self.ws, data)
        return aid

    def test_legacy_migration_preserves_outbox_and_dry_run_is_read_only(self):
        path, data = a.registry(self.ws)
        legacy = {'version': 1, 'sessions': data['sessions'], 'outbox': {'unknown': {'sending': True, 'message': 'TASK'}}}
        path.write_text(json.dumps(legacy))
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = a.next_actions(orch.Workspace(self.root))
        after = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after); self.assertFalse(result['enabled'])
        _, migrated = a.registry(self.ws)
        self.assertEqual(migrated['outbox'], legacy['outbox'])
        self.assertIsNone(migrated['instances']['codex:module-a']['confirmation'])

    def test_reuse_waiting_dirty_accepted_config_and_pid(self):
        self.assertEqual(a.next_actions(self.ws)['actions'][0]['kind'], 'dispatch')
        for status in ({'type': 'active', 'activeFlags': ['waitingOnApproval']}, {'type': 'notLoaded'}, {'type': 'systemError'}):
            self.thread['status'] = status
            self.assertNotIn('dispatch', [x['kind'] for x in a.next_actions(self.ws)['actions']])
        self.thread['status'] = {'type': 'idle'}
        (self.wt / 'dirty').write_text('unsaved')
        self.assertEqual(a.next_actions(self.ws)['actions'][0]['kind'], 'owner')
        (self.wt / 'dirty').unlink()
        self.h.cli('--workspace', self.root, 'set', 'WP-A-01', 'status', 'ACCEPTED')
        result = a.next_actions(orch.Workspace(self.root))
        self.assertNotIn('dispatch', [x['kind'] for x in result['actions']])
        self.h.cli('--workspace', self.root, 'set', 'WP-A-01', 'status', 'DONE')
        self.thread['model'] = 'changed'
        self.assertEqual(a.next_actions(orch.Workspace(self.root))['actions'][0]['kind'], 'owner')
        self.thread['model'] = 'fixture'
        _, data = a.registry(self.ws); data['instances']['codex:module-a']['confirmation']['process']['started'] = 'reused PID'
        a.persist(self.ws, data)
        self.assertEqual(a.next_actions(orch.Workspace(self.root))['actions'][0]['kind'], 'owner')

    def test_squash_merge_requires_exact_saved_head_not_ahead_base(self):
        (self.wt / 'a/readme.md').write_text('changed\n')
        self.h.git(self.wt, 'add', '.'); self.h.git(self.wt, 'commit', '-m', 'saved')
        sha = self.h.git(self.wt, 'rev-parse', 'HEAD')
        self.assertNotEqual(sha, self.sha)
        # A local extra commit cannot be discarded just because the PR is merged.
        self.assertEqual(a.next_actions(self.ws)['actions'][0]['kind'], 'owner')
        self.ws.journal('WP-A-01: accepted at ' + sha, wp='WP-A-01', evidence='report exact')
        with patch.object(a, 'pr_observation', return_value={'state': 'MERGED', 'headRefOid': sha, 'mergeCommit': {'oid': 'f' * 40}}):
            self.assertEqual(a.next_actions(self.ws)['actions'][0]['kind'], 'dispatch')

    def test_compare_and_swap_and_generation_fence(self):
        plan = a.next_actions(self.ws)
        _, data = a.registry(self.ws); data['revision'] += 1; a.persist(self.ws, data)
        with self.assertRaisesRegex(a.AutonomyError, 'state changed'):
            a.reserve(self.ws, 'WP-A-02', 'coord', 1, plan)
        with self.assertRaisesRegex(a.AutonomyError, 'generation mismatch'):
            a.reserve(self.ws, 'WP-A-02', 'coord', 0)
        _, data = a.registry(self.ws); data['coordinator']['lease_until'] = 0; a.persist(self.ws, data)
        args = argparse.Namespace(workspace=str(self.root), action='claim', coordinator='coord', pid=os.getpid(), evidence='new', previous_stopped=None)
        with self.assertRaisesRegex(a.AutonomyError, 'lease expiry'):
            a.cmd_autonomy(args)

    def test_concurrent_dispatch_has_one_reservation_and_slot(self):
        def attempt():
            try:return self.reserve()['result']
            except a.AutonomyError:return 'changed'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(results.count('assigned'), 1)
        _, data = a.registry(self.ws); self.assertEqual(len(data['assignments']), 1)
        self.assertEqual(a.active_slots(orch.Workspace(self.root), data, a.observations(self.ws, data)), 1)

    def test_unknown_send_retains_reservation_no_handover_or_repeat(self):
        aid = self.reserve()['assignment_id']
        with patch.object(codex_transport, 'send', return_value={'delivered': False, 'outcome_unknown': True}) as send:
            result = a.send_assignment(self.ws, aid, 'coord', 1)
            self.assertEqual(result['result'], 'outcome_unknown')
            with self.assertRaisesRegex(a.AutonomyError, 'outcome unknown'):
                a.send_assignment(self.ws, aid, 'coord', 1)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(orch.Workspace(self.root).wp_rows()['WP-A-02']['status'], 'DISPATCHING')
        self.assertEqual(a.reconcile(self.ws, aid, 'coord', 1)['result'], 'outcome_unknown')

    def test_start_ack_before_sender_record_and_repeated_task(self):
        aid = self.assigned('sending')
        _, data = a.registry(self.ws); assignment = data['assignments'][aid]
        self.h.git(self.wt, 'switch', '-c', assignment['branch'])
        receipt = a.transition_path(self.ws, aid); state_io.atomic(receipt, b'{"complete": true}')
        self.thread['turns'] = [{'items': [{'type': 'agentMessage', 'text': 'STARTED assignment_id=' + aid}]}]
        result = a.reconcile(self.ws, aid, 'coord', 1)
        self.assertEqual(result['result'], 'started')
        args = argparse.Namespace(workspace=str(self.root), action='sent', assignment=aid,
                                   coordinator='coord', generation=1, outcome='queued', evidence='late sender')
        with contextlib.redirect_stdout(io.StringIO()):a.cmd_session(args)
        self.assertEqual(a.registry(self.ws)[1]['assignments'][aid]['state'], 'started')
        self.assertEqual(orch.Workspace(self.root).wp_rows()['WP-A-02']['status'], 'IN_PROGRESS')
        self.assertEqual(a.reconcile(self.ws, aid, 'coord', 1)['result'], 'started')

    def test_echoed_user_task_is_not_a_start_ack(self):
        aid = self.assigned()
        self.thread['turns'] = [{'items': [{'type': 'userMessage', 'text': 'STARTED assignment_id=' + aid}]}]
        self.assertEqual(a.reconcile(self.ws, aid, 'coord', 1)['result'], 'outcome_unknown')

    def test_transition_is_idempotent_and_never_writes_program_documents(self):
        aid = self.assigned()
        before = runtime.state_version(self.ws)
        old = Path.cwd(); os.chdir(self.wt)
        try:
            atomic = state_io.atomic
            def protected(path, *args, **kwargs):
                if '.codex' in Path(path).parts:
                    raise PermissionError('native protected client directory')
                return atomic(path, *args, **kwargs)
            with patch.object(state_io, 'atomic', side_effect=protected):
                result = a.transition(self.ws, aid, 'module-a')
            again = a.transition(self.ws, aid, 'module-a')
        finally:os.chdir(old)
        self.assertEqual(result, again)
        self.assertEqual(before, runtime.state_version(self.ws))
        self.assertEqual(orch.Workspace(self.root).wp_rows()['WP-A-02']['status'], 'DISPATCHING')
        self.assertEqual(self.h.git(self.wt, 'branch', '--show-current'), orch.wp_context(self.ws, 'WP-A-02')[2]['branch'])

    def test_transition_setup_failure_is_not_blindly_replayed(self):
        aid = self.assigned(); old = Path.cwd(); os.chdir(self.wt)
        try:
            with patch.object(a.codex_adapter, 'prepare_reuse', side_effect=RuntimeError('setup crashed')):
                with self.assertRaises(RuntimeError):a.transition(self.ws, aid, 'module-a')
            with self.assertRaisesRegex(a.AutonomyError, 'setup outcome unknown'):
                a.transition(self.ws, aid, 'module-a')
        finally:os.chdir(old)

    def test_watcher_deduplicates_busy_coalesces_and_deadline(self):
        state, message = a.watch_tick(self.ws, {}, clock=100)
        self.assertIn('signal_id=', message)
        unchanged, message = a.watch_tick(self.ws, state, clock=900)
        self.assertIsNone(message); self.assertEqual(unchanged['pending'], state['pending'])
        state['pending'] = None
        _, message = a.watch_tick(self.ws, state, clock=101)
        self.assertIsNone(message)
        _, message = a.watch_tick(self.ws, state, clock=701)
        self.assertIsNotNone(message)
        real = self.live
        with patch.object(a, 'observe_thread', side_effect=lambda ws, tid, history=False:
                          {**real(ws, tid, history), 'status': {'type': 'active', 'activeFlags': []}} if tid == 'coord' else real(ws, tid, history)):
            waiting, message = a.watch_tick(self.ws, {}, clock=100)
            self.assertIsNone(message); self.assertIn('coalesced', waiting)

    def test_pause_after_queued_signal_consumes_without_actions(self):
        state, _ = a.watch_tick(self.ws, {}, clock=100); a.write_watch(self.ws, state)
        _, data = a.registry(self.ws); data['autonomy']['enabled'] = False; a.persist(self.ws, data)
        args = argparse.Namespace(workspace=str(self.root), action='consume', coordinator='coord', generation=1,
                                   signal=state['pending']['id'], evidence=None)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):a.cmd_autonomy(args)
        self.assertEqual(json.loads(output.getvalue()), {'enabled': False, 'actions': []})
        with self.assertRaisesRegex(a.AutonomyError, 'paused'):
            a.send_assignment(self.ws, 'anything', 'coord', 1)

    def test_empty_tick_no_model_or_writes_and_observation_error_is_distinct(self):
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'DRAFT')
        self.h.cli('--workspace', self.root, 'owner', 'close', 'P-1', 'fixture decision: no ignored settings')
        ws = orch.Workspace(self.root); before = runtime.state_version(ws)
        with patch.object(codex_transport, 'send') as send:
            state, message = a.watch_tick(ws, {}, clock=100)
            self.assertEqual(state, {}); self.assertIsNone(message); send.assert_not_called()
        self.assertEqual(before, runtime.state_version(ws))
        with patch.object(a, 'observe_thread', side_effect=codex_transport.TransportError('offline')):
            plan = a.next_actions(ws)
            self.assertIn('observation_error', [x.get('kind') for x in plan['waiting']])

    def test_transport_nonzero_and_timeout_are_unknown_without_fallback(self):
        with patch.object(codex_transport, 'capabilities', return_value={'queue': True}), \
             patch.object(codex_transport, 'command', return_value=['codex']):
            for effect in (subprocess.CompletedProcess([], 1, '', 'lost response'), subprocess.TimeoutExpired('queue', 30)):
                with patch.object(codex_transport.subprocess, 'run', side_effect=effect if isinstance(effect, Exception) else None,
                                  return_value=effect):
                    result = codex_transport.send('id', 'TASK')
                    self.assertTrue(result['outcome_unknown']); self.assertIsNone(result['fallback'])

    def second_stream(self):
        for name in ('first', 'second'):
            self.h.cli('--workspace', self.root, 'new-wp', 'b', name)
        self.h.cli('--workspace', self.root, 'set', 'WP-B-01', 'status', 'DONE')
        self.h.cli('--workspace', self.root, 'set', 'WP-B-01', 'pr', 'https://github.com/example/repo/pull/2')
        self.h.cli('--workspace', self.root, 'set', 'WP-B-02', 'status', 'READY')
        ws = orch.Workspace(self.root); branch = orch.wp_context(ws, 'WP-B-01')[2]['branch']
        wt = self.h.root / 'writer-b'; self.h.git(self.repo, 'worktree', 'add', '-b', branch, wt, 'main')
        a.codex_adapter.prepare(ws, 'WP-B-01')
        self.extra_threads = {'module-b': {**self.thread, 'id': 'module-b', 'cwd': str(wt)}}
        ws.journal('WP-B-01: accepted at ' + self.sha, wp='WP-B-01', evidence='report fixture')
        a.attach(ws, argparse.Namespace(wp='WP-B-01', thread='module-b', worktree=str(wt), pid=os.getpid(), evidence='fixture binding'))
        return ws

    def test_independent_wave_limit_and_reserved_slot(self):
        ws = self.second_stream()
        plan = a.next_actions(ws)
        self.assertEqual([x['wp'] for x in plan['actions'] if x['kind'] == 'dispatch'], ['WP-A-02', 'WP-B-02'])
        _, data = a.registry(ws); data['autonomy']['max_parallel_sessions'] = 1; a.persist(ws, data)
        plan = a.next_actions(ws)
        self.assertEqual(len([x for x in plan['actions'] if x['kind'] == 'dispatch']), 1)
        self.reserve()
        plan = a.next_actions(orch.Workspace(self.root))
        self.assertFalse(any(x['kind'] == 'dispatch' for x in plan['actions']))
        self.assertTrue(any('parallel session limit' in str(x) for x in plan['waiting']))

    def test_wave_conflicting_shared_locks_not_individually_compatible(self):
        ws = self.second_stream()
        config = self.root / 'orch.yaml'
        config.write_text(config.read_text().replace('    resources: []', '    resources: [stand]'))
        ws = orch.Workspace(self.root)
        for wp in ('WP-A-02', 'WP-B-02'):
            path = ws.wp_path(ws.wp_rows()[wp]['wp']); text = path.read_text()
            line = next(x for x in text.splitlines() if x.startswith('| Resources (locks) |'))
            path.write_text(text.replace(line, '| Resources (locks) | `stand` |'))
        _, data = a.registry(ws)
        for instance in data['instances'].values():
            instance['confirmation']['configuration'] = a.configuration(ws, instance)
        a.persist(ws, data)
        plan = a.next_actions(ws)
        self.assertEqual(len([x for x in plan['actions'] if x['kind'] == 'dispatch']), 1)
        self.assertIn('locks conflict', str(plan['waiting']))

    def test_cancel_requires_stopped_process_and_preserves_unknown_outbox(self):
        aid = self.assigned('outcome_unknown')
        args = argparse.Namespace(workspace=str(self.root), action='cancel', assignment=aid,
                                   coordinator='coord', generation=1, evidence='owner stopped recipient')
        with self.assertRaisesRegex(a.AutonomyError, 'still exists'):a.cmd_session(args)
        child = self.h.child('import time; time.sleep(10)')
        proof = a.process_identity(child.pid); child.kill(); child.communicate()
        _, data = a.registry(self.ws); data['instances']['codex:module-a']['confirmation']['process'] = proof
        a.persist(self.ws, data)
        with contextlib.redirect_stdout(io.StringIO()):a.cmd_session(args)
        _, data = a.registry(self.ws)
        self.assertEqual(data['assignments'][aid]['state'], 'cancelled')
        self.assertIn(aid, data['outbox'])
        self.assertEqual(orch.Workspace(self.root).wp_rows()['WP-A-02']['status'], 'READY')

    def test_old_owner_unknown_assignments_block_replacement(self):
        aid = self.assigned('outcome_unknown')
        _, data = a.registry(self.ws); data['coordinator']['generation'] = 2; data['generation'] = 2; a.persist(self.ws, data)
        with self.assertRaisesRegex(a.AutonomyError, 'generation mismatch'):
            a.send_assignment(self.ws, aid, 'coord', 1)
        self.assertEqual(a.reconcile(self.ws, aid, 'coord', 2)['result'], 'outcome_unknown')
        self.assertEqual(a.registry(self.ws)[1]['assignments'][aid]['state'], 'outcome_unknown')

    def test_legacy_unknown_send_blocks_reuse_until_observed_consumption(self):
        _, data = a.registry(self.ws)
        data['outbox']['old-send'] = {'thread_id': 'module-a', 'wp': 'WP-A-01', 'message': 'legacy TASK', 'sending': True}
        a.persist(self.ws, data)
        self.assertNotIn('dispatch', [x['kind'] for x in a.next_actions(self.ws)['actions']])
        args = argparse.Namespace(workspace=str(self.root), action='reconcile-send', coordinator='coord', generation=1, request_id='old-send')
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(a.cmd_session(args), 2)
        self.thread['turns'] = [{'status': 'completed', 'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text': 'legacy TASK'}]}]}]
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(a.cmd_session(args), 0)
        self.assertIn('dispatch', [x['kind'] for x in a.next_actions(self.ws)['actions']])

    def test_dependency_cycle_is_deadlock_not_ordinary_wait(self):
        self.h.cli('--workspace', self.root, 'new-wp', 'b', 'cycle')
        ws = orch.Workspace(self.root)
        for wp, dep in [('WP-A-02', 'WP-B-01'), ('WP-B-01', 'WP-A-02')]:
            path = ws.wp_path(ws.wp_rows()[wp]['wp']); text = path.read_text()
            old = next(x for x in text.splitlines() if x.startswith('| Depends on |'))
            path.write_text(text.replace(old, '| Depends on | ' + dep + ' |'))
        self.h.cli('--workspace', self.root, 'set', 'WP-B-01', 'status', 'READY')
        plan = a.next_actions(orch.Workspace(self.root))
        self.assertEqual(plan['situation'], 'deadlock')
        self.assertTrue(any(x.get('reason') == 'dependency cycle' for x in plan['actions']))

    def test_rpc_server_approval_request_is_not_a_matching_response(self):
        server = object.__new__(codex_transport.Server)
        server.responses = queue.Queue(); server.events = []; server.next_id = 0; server.send = lambda value: None
        server.responses.put({'id': 1, 'method': 'item/commandExecution/requestApproval', 'params': {'command': 'fixture'}})
        server.responses.put({'id': 1, 'result': {'observed': True}})
        self.assertEqual(server.call('thread/read', {}), {'observed': True})
        self.assertEqual(server.events[0]['method'], 'item/commandExecution/requestApproval')

    def test_new_base_client_config_requires_owner_preparation_before_switch(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(exist_ok=True)
        config.write_text('model = "changed-by-new-base"\n')
        self.h.git(self.repo, 'add', '.codex/config.toml'); self.h.git(self.repo, 'commit', '-m', 'new base configuration')
        aid = self.assigned(); old_branch = self.h.git(self.wt, 'branch', '--show-current')
        previous = Path.cwd(); os.chdir(self.wt)
        try:
            with self.assertRaisesRegex(a.AutonomyError, 'new base changes native'):
                a.transition(self.ws, aid, 'module-a')
        finally:os.chdir(previous)
        self.assertEqual(self.h.git(self.wt, 'branch', '--show-current'), old_branch)
        self.assertEqual(a.registry(self.ws)[1]['assignments'][aid]['state'], 'queued')

    def test_permission_wait_is_actionable_without_releasing_assignment(self):
        aid = self.assigned('started')
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'IN_PROGRESS')
        self.thread['status'] = {'type': 'active', 'activeFlags': ['waitingOnApproval']}
        plan = a.next_actions(orch.Workspace(self.root))
        self.assertTrue(any(x.get('reason') == 'session requires user input/approval' for x in plan['actions']))
        self.assertEqual(a.registry(self.ws)[1]['assignments'][aid]['state'], 'started')

    def test_verified_test_and_completion_offer_gated_next_steps(self):
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'VERIFIED_TEST')
        plan = a.next_actions(orch.Workspace(self.root))
        self.assertTrue(any(x['kind'] == 'release' for x in plan['actions']))
        self.h.cli('--workspace', self.root, 'set', 'WP-A-02', 'status', 'DONE')
        self.h.cli('--workspace', self.root, 'owner', 'close', 'P-1', 'fixture completion decision')
        plan = a.next_actions(orch.Workspace(self.root))
        self.assertTrue(any('work packages complete' in x.get('reason', '') for x in plan['actions']))


if __name__ == '__main__':
    unittest.main()
