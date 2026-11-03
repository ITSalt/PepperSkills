#!/usr/bin/env python3
"""Regression of the six-hour failure with both recorded subagents and native workers."""
import argparse
import json
import time
import unittest
from pathlib import Path
import autonomy as a
import continuation_selftest
import research
import orch


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.h = continuation_selftest.ContinuationTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.research()
        self.ws = self.h.ws
        self.wp = 'WP-A-02'
        (self.ws.root / 'reports').mkdir(exist_ok=True)
        (self.ws.root / 'reports/result.md').write_text('source evidence; graph unavailable; budget unknown\n')
        # Static source findings plus an experiment that the graph outage blocks (the NaCl WP-01 shape).
        _, data = a.registry(self.ws)
        data['research'][self.wp] = research.update(self.ws, None, 'contract', {
            'question': 'read fixture', 'decision': 'accept fixture', 'artifact': 'reports/result.md',
            'criteria': {'source': {'evidence_standard': 'exact text', 'unknown_allowed': False},
                         'experiment': {'evidence_standard': 'measured A/B pair', 'unknown_allowed': False}}})
        a.persist(self.ws, data)

    def event(self, kind, payload):
        _, data = a.registry(self.ws)
        before = data['research'][self.wp]
        after = research.update(self.ws, before, kind, payload, wp=self.wp)
        data['research'][self.wp] = after
        a.persist(self.ws, data)
        return after

    def collect(self, number):
        self.event('start', {'id': f'wave-{number}', 'tasks': [{'id': 'subagent', 'criterion': 'source',
                   'missing_fact': 'source text', 'decision': 'accept static result'}]})
        return self.event('result', {'id': f'result-{number}', 'task': 'subagent', 'evidence': 'reports/result.md'})

    def verdict(self, value, status, experiment='blocked', remainder=None):
        rnd = str(a.registry(self.ws)[1]['research'][self.wp]['round'])
        payload = {'id': 'verdict-' + value + '-' + rnd, 'verdict': value, 'criteria': {
            'source': {'status': status, 'reason': 'bounded static evidence', 'evidence': 'reports/result.md'},
            'experiment': {'status': experiment, 'reason': 'graph unavailable', 'evidence': 'reports/result.md'}}}
        if remainder is not None:
            payload['remainder'] = remainder
        return self.event('verdict', payload)

    def to_experiment(self):
        return {'experiment': {'owner_wp': 'WP-A-01', 'condition': 'graph restore confirmed and budget known'}}

    def test_returned_subagent_forces_review_and_cosmetic_edits_do_not_wake(self):
        self.collect(1)
        before = a.next_actions(self.ws)
        self.assertTrue(any(x.get('wp') == self.wp and x['kind'] == 'review_research' for x in before['actions']))
        self.ws.journal('cosmetic link fix', evidence='reports/result.md')
        (self.ws.root / 'reports/result.md').write_text('same static evidence, punctuation fixed\n')
        after = a.next_actions(orch.Workspace(self.ws.root))
        self.assertEqual(before['fingerprint'], after['fingerprint'])
        self.assertEqual(research.action(a.registry(self.ws)[1]['research'][self.wp]), 'review_research')

    def test_defect_gets_one_revision_then_partial_remainder(self):
        self.collect(1)
        self.verdict('revise', 'blocked')
        self.collect(2)
        with self.assertRaises(a.streams.StreamError):
            self.verdict('revise', 'blocked')
        with self.assertRaisesRegex(a.streams.StreamError, 'owner of every unresolved'):
            self.verdict('partial', 'satisfied')
        self.verdict('partial', 'satisfied', remainder=self.to_experiment())
        _, data = a.registry(self.ws)
        self.assertEqual(a.active_slots(self.ws, data, a.observations(self.ws, data)), 0)
        with self.assertRaises(a.streams.StreamError):
            self.event('start', {'id': 'adjacent-question', 'tasks': []})
        self.assertEqual(research.action(a.registry(self.ws)[1]['research'][self.wp]), 'finalize_research')

    def test_partial_result_is_accepted_and_releases_dependents(self):
        self.collect(1)
        with self.assertRaisesRegex(a.streams.StreamError, 'another existing WP'):
            self.verdict('partial', 'satisfied', remainder={'experiment': {'owner_wp': self.wp, 'condition': 'x'}})
        with self.assertRaisesRegex(a.streams.StreamError, 'at least one resolved'):
            self.verdict('partial', 'blocked', remainder={**self.to_experiment(),
                                                          'source': {'owner_wp': 'WP-A-01', 'condition': 'x'}})
        self.verdict('partial', 'satisfied', remainder=self.to_experiment())
        plan = a.next_actions(orch.Workspace(self.ws.root))
        self.assertTrue(any(x['kind'] == 'finalize_research' and x.get('wp') == self.wp for x in plan['actions']))
        for status in ('ACCEPTED', 'DONE'):
            orch.cmd_set(argparse.Namespace(workspace=str(self.ws.root), wp=self.wp, column='status',
                                           text=status, evidence='partial verdict', quiet=True))
        self.assertIn(orch.Workspace(self.ws.root).wp_rows()[self.wp]['status'], a.streams.SATISFIED)
        with self.assertRaisesRegex(a.streams.StreamError, 'blocked open criterion'):
            self.event('unblock', {'id': 'late', 'criterion': 'experiment', 'evidence': 'reports/result.md'})

    def test_blocked_names_condition_and_unblock_returns_to_review(self):
        self.collect(1)
        with self.assertRaisesRegex(a.streams.StreamError, 'condition'):
            self.verdict('blocked', 'blocked', remainder={'source': {}, 'experiment': {}})
        self.verdict('blocked', 'blocked', remainder={'source': {'condition': 'source access'},
                                                      'experiment': {'condition': 'graph restore'}})
        self.assertEqual(self.event('unblock', {'id': 'u', 'criterion': 'source', 'evidence': 'reports/result.md'})['phase'], 'review')

    def test_contract_criteria_are_bounded(self):
        many = {f'c{i}': {'evidence_standard': 'x', 'unknown_allowed': True} for i in range(research.MAX_CRITERIA + 1)}
        with self.assertRaisesRegex(a.streams.StreamError, 'at most'):
            research.update(self.ws, None, 'contract', {'question': 'q', 'decision': 'd',
                                                        'artifact': 'reports/result.md', 'criteria': many})

    def test_forgotten_collection_is_raised_as_stalled(self):
        self.collect(1)
        _, data = a.registry(self.ws)
        data['research'][self.wp].update(phase='collecting', updated_at=int(time.time()) - 3600)
        a.persist(self.ws, data)
        plan = a.next_actions(orch.Workspace(self.ws.root))
        stalled = [x for x in plan['actions'] if x['kind'] == 'stalled' and x['wp'] == self.wp]
        self.assertEqual(len(stalled), 1)
        again = a.next_actions(orch.Workspace(self.ws.root))
        self.assertEqual(plan['fingerprint'], again['fingerprint'])  # One condition, one stable signal.

    def test_idle_executor_worktree_is_stalled_unless_session_busy(self):
        ws = orch.Workspace(self.ws.root)
        orch.cmd_set(argparse.Namespace(workspace=str(ws.root), wp='WP-A-01', column='status',
                                       text='IN_PROGRESS', evidence='fixture', quiet=True))
        ws = orch.Workspace(self.ws.root)
        _, data = a.registry(ws)
        observed = {'sessions': {}, 'prs': {}, 'errors': []}
        later = time.time() + 2 * 3600
        found = a.stall.scan(ws, data, observed, later, orch.wp_context)
        self.assertEqual([x['wp'] for x in found], ['WP-A-01'])
        self.assertEqual(a.stall.scan(ws, data, observed, time.time(), orch.wp_context), [])
        data['instances']['codex:busy'] = {'key': 'codex:busy', 'wp': 'WP-A-01', 'client': 'codex', 'state': 'running'}
        observed['sessions']['codex:busy'] = {'thread': {'status': {'type': 'active'}}}
        self.assertEqual(a.stall.scan(ws, data, observed, later, orch.wp_context), [])

    def test_unknown_graph_cannot_become_accepted_but_static_can(self):
        self.collect(1)
        with self.assertRaises(a.streams.StreamError):
            self.verdict('accepted', 'unknown')
        self.verdict('accepted', 'satisfied', experiment='satisfied')
        record = a.registry(self.ws)[1]['research'][self.wp]
        self.assertEqual(record['phase'], 'accepted')
        self.assertEqual(research.action(record), 'finalize_research')

    def test_results_are_idempotent_across_reloaded_registry(self):
        self.collect(1)
        payload = {'id': 'result-1', 'task': 'subagent', 'evidence': 'reports/result.md'}
        before = a.registry(orch.Workspace(self.ws.root))[1]['research'][self.wp]
        self.assertEqual(before, research.update(self.ws, before, 'result', payload))
        with self.assertRaises(a.streams.StreamError):
            research.update(self.ws, before, 'result', {**payload, 'evidence': 'another.md'})
        self.assertEqual(before['round'], 1)

    def test_normal_status_command_rejects_unreviewed_acceptance(self):
        import argparse
        with self.assertRaises(orch.OrchError):
            orch.cmd_set(argparse.Namespace(workspace=str(self.ws.root), wp=self.wp,
                                           column='status', text='ACCEPTED', evidence='claim'))

    def test_native_result_and_foreground_result_share_review(self):
        self.collect(1)
        _, data = a.registry(self.ws)
        data['launches'][self.wp] = {'state': 'started', 'thread_id': 'worker', 'turn_id': 'turn'}
        data['instances']['codex:worker'] = {'key': 'codex:worker', 'wp': self.wp, 'client': 'codex',
            'state': 'stopped', 'assignment_id': None}
        a.persist(self.ws, data)
        observed = a.observations(self.ws, data)
        observed['sessions']['codex:worker'] = {'thread': {'turns': [{'id': 'turn', 'status': 'completed'}]}}
        plan = a.next_actions(self.ws, observed=observed)
        self.assertTrue(any(x['kind'] == 'review_research' and x.get('wp') == self.wp for x in plan['actions']))
        _, data = a.registry(self.ws)
        data['autonomy']['enabled'] = False
        a.persist(self.ws, data)
        self.assertEqual(a.next_actions(self.ws, observed=observed)['situation'], 'paused')


    def test_owner_only_wait_is_repeated_less_often(self):
        from unittest.mock import patch
        plan = {'actions': [{'kind': 'owner', 'item': 'P-1', 'reason': 'product fork'}], 'waiting': [],
                'fingerprint': 'same', 'next_check_seconds': 600}
        with patch.object(a, 'next_actions', return_value=plan):
            state, message = a.watch_tick(self.ws, {'fingerprint': 'same', 'next_due': 0}, clock=1000)
            self.assertIsNotNone(message)
            self.assertEqual(state['next_due'], 1000 + 600 * a.OWNER_REPEAT)
            state['pending'] = None
            self.assertIsNone(a.watch_tick(self.ws, state, clock=1700)[1])

if __name__ == '__main__':
    unittest.main()
