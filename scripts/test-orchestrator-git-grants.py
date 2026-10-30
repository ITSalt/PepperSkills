#!/usr/bin/env python3
"""Offline checks of bounded native-grant decisions and provenance; no model/auth."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('git_grants', Path(__file__).with_name('probe-orchestrator-git-grants.py'))
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


class GitGrantsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.roots = [str(self.root / str(i)) for i in range(6)]
        for path in self.roots:
            Path(path).mkdir()
        self.request = {'id': 3, 'method': 'item/permissions/requestApproval', 'params': {
            'threadId': 'module', 'turnId': 'turn', 'cwd': str(self.root),
            'permissions': {'fileSystem': {'write': self.roots}}}}

    def decide(self, req=None, **changes):
        args = dict(thread='module', turn='turn', cwd=str(self.root), allowed_roots=self.roots, authorized=True)
        args.update(changes)
        return p.grant_decision(req or self.request, **args)

    def test_exact_native_permission_request_gets_only_turn_scope(self):
        self.assertEqual(self.decide(), {'permissions': {'fileSystem': {'write': sorted(self.roots)}}, 'scope': 'turn'})
        self.assertNotIn('strictAutoReview', self.decide())

    def test_network_reads_other_roots_and_profile_fields_are_rejected(self):
        profiles = [{'fileSystem': {'write': self.roots + [str(self.root.parent)]}},
            {'fileSystem': {'write': self.roots[:-1]}},
            {'fileSystem': {'write': self.roots, 'read': [str(self.root)]}},
            {'fileSystem': {'write': self.roots}, 'network': {'enabled': True}},
            {'fileSystem': {'write': self.roots}, 'sandbox': 'danger-full-access'}]
        for profile in profiles:
            with self.subTest(profile=profile):
                req = copy.deepcopy(self.request); req['params']['permissions'] = profile
                with self.assertRaises(ValueError): self.decide(req)

    def test_special_and_glob_paths_are_rejected(self):
        for path in ({'type': 'special', 'value': {'kind': 'root'}},
                     {'type': 'glob_pattern', 'pattern': '**'}):
            req = copy.deepcopy(self.request)
            req['params']['permissions'] = {'fileSystem': {'entries': [{'access': 'write', 'path': path}]}}
            with self.assertRaises(ValueError): self.decide(req)

    def test_native_entries_schema_and_write_array_have_same_bounded_authority(self):
        req = copy.deepcopy(self.request)
        req['params']['permissions'] = {'fileSystem': {'entries': [
            {'access': 'write', 'path': {'type': 'path', 'path': x}} for x in self.roots]}}
        self.assertEqual(self.decide(req), self.decide())

    def test_wrong_actor_turn_cwd_or_command_escalation_is_not_approved(self):
        for key, value in [('threadId', 'coordinator'), ('turnId', 'old'), ('cwd', str(self.root.parent))]:
            req = copy.deepcopy(self.request); req['params'][key] = value
            with self.assertRaises(ValueError): self.decide(req)
        req = copy.deepcopy(self.request); req['method'] = 'item/commandExecution/requestApproval'
        with self.assertRaises(ValueError): self.decide(req)
        with self.assertRaises(ValueError): self.decide(authorized=False)

    def test_extra_unknown_profile_fields_are_not_granted(self):
        req = copy.deepcopy(self.request)
        req['params']['permissions']['fileSystem']['unrestricted'] = True
        with self.assertRaises(ValueError): self.decide(req)

    def test_empty_mutable_json_errors_and_timeout_cannot_pass(self):
        for report in ({}, {'error': 'TimeoutError'}, {'turns': [{'phase': 'granted',
                'native_command_matches': 1, 'shell_result': {'grant_access': {'x': {'ok': True}}},
                'approval_decisions': [{'result': {'scope': 'turn'}}]}]}):
            self.assertTrue(all(v != 'PASS' for v in p.assess(report).values()))

    def test_native_event_stdout_actor_phase_and_command_must_match(self):
        shell = {'caller': 'module', 'cwd': '/fixture/module', 'phase': 'expired'}
        item = {'type': 'commandExecution', 'status': 'completed', 'exitCode': 0,
            'cwd': shell['cwd'], 'command': 'python3 -I protected.py', 'aggregatedOutput': json.dumps(shell)}
        turn = {'epoch': 'epoch', 'thread': 'module', 'turn': 'turn', 'phase': 'expired',
            'command': item['command'], 'cwd': item['cwd'], 'native_command': item, 'shell_result': shell}
        report = {'events': [{'epoch': 'epoch', 'direction': 'native_to_owner', 'message': {
            'method': 'item/completed', 'params': {'threadId': 'module', 'turnId': 'turn', 'item': item}}}]}
        self.assertTrue(p.native_result_matches(report, turn))
        for key, value in [('thread', 'other'), ('phase', 'granted'), ('command', item['command'] + '; echo forged')]:
            changed = {**turn, key: value}
            self.assertFalse(p.native_result_matches(report, changed))
        changed = copy.deepcopy(turn); changed['shell_result']['caller'] = 'forged'
        self.assertFalse(p.native_result_matches(report, changed))

    def test_local_upstream_has_unfetched_new_commit_and_valid_canary_refs(self):
        f = p.make_fixture(self.root / 'fixture')
        self.assertNotEqual(f['initial_head'], f['upstream_head'])
        self.assertEqual(p.must(Path(f['root']) / 'module', 'rev-parse', 'HEAD'), f['initial_head'])
        self.assertEqual(len(f['grant_roots']), 6)
        self.assertEqual(p.git(Path(f['root']) / 'module', 'show-ref')['returncode'], 0)
        self.assertNotIn(str(Path(f['common']) / 'config'), f['grant_roots'])
        self.assertNotIn(f['sibling'], f['grant_roots'])


if __name__ == '__main__':
    unittest.main()
