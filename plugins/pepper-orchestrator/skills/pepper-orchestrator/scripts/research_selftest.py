#!/usr/bin/env python3
"""Regression of the six-hour failure with both recorded subagents and native workers."""
import json
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

    def event(self, kind, payload):
        _, data = a.registry(self.ws)
        before = data['research'][self.wp]
        after = research.update(self.ws, before, kind, payload)
        data['research'][self.wp] = after
        a.persist(self.ws, data)
        return after

    def collect(self, number):
        self.event('start', {'id': f'wave-{number}', 'tasks': [{'id': 'subagent', 'criterion': 'source',
                   'missing_fact': 'source text', 'decision': 'accept static result'}]})
        return self.event('result', {'id': f'result-{number}', 'task': 'subagent', 'evidence': 'reports/result.md'})

    def verdict(self, value, status):
        return self.event('verdict', {'id': 'verdict-' + value + '-' + str(a.registry(self.ws)[1]['research'][self.wp]['round']), 'verdict': value, 'criteria': {
            'source': {'status': status, 'reason': 'bounded static evidence', 'evidence': 'reports/result.md'}}})

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
        self.verdict('partial', 'blocked')
        _, data = a.registry(self.ws)
        self.assertEqual(a.active_slots(self.ws, data, a.observations(self.ws, data)), 0)
        with self.assertRaises(a.streams.StreamError):
            self.event('start', {'id': 'adjacent-question', 'tasks': []})
        self.assertIsNone(research.action(a.registry(self.ws)[1]['research'][self.wp]))

    def test_unknown_graph_cannot_become_accepted_but_static_can(self):
        self.collect(1)
        with self.assertRaises(a.streams.StreamError):
            self.verdict('accepted', 'unknown')
        self.verdict('accepted', 'satisfied')
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


if __name__ == '__main__':
    unittest.main()
