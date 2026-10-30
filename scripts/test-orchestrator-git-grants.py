#!/usr/bin/env python3
"""Offline checks of bounded native-grant decisions and provenance; no model/auth."""
import copy
import hashlib
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

    def test_resolved_approval_history_is_not_a_new_request_for_later_turn(self):
        from types import SimpleNamespace
        old = copy.deepcopy(self.request)
        current = copy.deepcopy(self.request); current['id'] = 4; current['params']['turnId'] = 'next'
        other = copy.deepcopy(current); other['id'] = 5; other['params']['threadId'] = 'coordinator'
        api = SimpleNamespace(approvals=[old, current, other])
        self.assertEqual(p.approvals_for_turn(api, 'module', 'next', set()), [current])
        self.assertEqual(p.approvals_for_turn(api, 'module', 'next', {4}), [])
        self.assertEqual(p.approvals_for_turn(api, 'module', 'expired', set()), [])

    def test_missing_overlap_events_cannot_prove_active_sibling_isolation(self):
        self.assertFalse(p.sibling_overlaps_grant({'events': []}, {}))
        self.assertFalse(p.sibling_overlaps_grant({'events': []}, {
            'granted': {'shell_result': {'sibling_barrier_released': True}}, 'sibling': {}}))

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


    def evidence(self):
        root = Path(__file__).resolve().parent.parent / 'docs/validation/evidence/orchestrator-git-approved-linux'
        return root, json.loads((root / 'git-approved-final.json').read_text(encoding='utf-8'))

    def test_recorded_fixture_proves_native_results_and_executed_source(self):
        root, r = self.evidence()
        canonical = lambda path: Path(path).read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(r['source_sha256'], hashlib.sha256(canonical(p.__file__)).hexdigest())
        self.assertEqual(r['library_sha256'], hashlib.sha256(canonical(p.LIB)).hexdigest())
        self.assertEqual(r['overall'], 'GIT_APPROVED_FIXTURE_PASS')
        self.assertEqual(p.assess(r), r['verdicts'])
        self.assertTrue(all(v == 'PASS' for v in r['verdicts'].values()))
        self.assertEqual(r['model_turns_requested'], 5)
        self.assertEqual(r['native_turns_started'], 5)
        self.assertTrue(all(p.native_result_matches(r, t) for t in r['turns']))
        for role, thread in r['threads'].items():
            self.assertEqual(thread['sandbox']['type'], 'workspaceWrite')
            self.assertTrue(thread['sandbox']['networkAccess'])
            self.assertEqual(thread['sandbox']['writableRoots'], [])
            self.assertEqual(thread['runtimeWorkspaceRoots'], [thread['cwd']])
            self.assertEqual(thread['approvalPolicy'], 'on-request')
            self.assertEqual(thread['approvalsReviewer'], 'user')
        self.assertEqual(r['protected_hashes_before'], r['protected_hashes_after'])

    def test_exact_grant_has_native_request_response_and_sibling_overlap(self):
        _, r = self.evidence()
        phases = {t['phase']: t for t in r['turns']}
        g = phases['granted']; request = g['approval_requests'][0]; decision = g['approval_decisions'][0]
        self.assertEqual(len(g['approval_requests']), 1)
        self.assertEqual(request['method'], 'item/permissions/requestApproval')
        self.assertEqual(request['params']['threadId'], g['thread'])
        self.assertEqual(request['params']['turnId'], g['turn'])
        roots = r['fixture']['grant_roots']
        self.assertEqual(len(roots), 6)
        self.assertEqual(set(request['params']['permissions']['fileSystem']['write']), set(roots))
        self.assertEqual(set(decision['result']['permissions']['fileSystem']['write']), set(roots))
        self.assertEqual(decision['result']['scope'], 'turn')
        replies = [e for e in r['events'] if e['direction'] == 'owner_to_native'
            and 'permissions' in e['message'].get('result', {})]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]['message'], {'id': request['id'], 'result': decision['result']})
        self.assertTrue(p.sibling_overlaps_grant(r, phases))
        for phase in ('baseline', 'sibling', 'expired', 'recovered'):
            self.assertFalse(phases[phase]['approval_decisions'])
            access = phases[phase]['shell_result']['grant_access']
            self.assertEqual(set(access), set(roots))
            self.assertTrue(all(not a['ok'] and a['errno'] == 30 for a in access.values()))
        self.assertEqual(r['resume']['thread']['id'], r['threads']['module']['thread']['id'])
        self.assertTrue(r['before_restart_stop']['waited'])

    def test_surface_cleanup_and_checksums_match_owner_records(self):
        root, r = self.evidence()
        surface = json.loads((root / 'surface-summary.json').read_text(encoding='utf-8'))
        self.assertTrue(all(v == 'undefined' for v in surface['types'].values()))
        self.assertEqual(len(surface['tool_names']), 13)
        self.assertIn('request_permissions', surface['tool_names'])
        self.assertIn('Object.getOwnPropertyNames(globalThis)', surface['native_source'])
        self.assertEqual(surface['observed_values'].count('unsupported import in exec'), 2)
        calls = [e['message']['params']['item'] for e in r['events']
            if e['message'].get('method') == 'rawResponseItem/completed'
            and e['message']['params'].get('threadId') == surface['threadId']
            and e['message']['params'].get('turnId') == surface['turnId']]
        self.assertTrue(any(i.get('type') == 'custom_tool_call' and i.get('call_id') == surface['native_call_id']
            and i.get('input') == surface['native_source'] for i in calls))
        self.assertTrue(any(i.get('type') == 'custom_tool_call_output' and i.get('call_id') == surface['native_call_id']
            and any(json.dumps(surface['tool_names'], separators=(',', ':')) == c.get('text') for c in i.get('output', [])) for i in calls))
        cleanup = json.loads((root / 'cleanup.json').read_text(encoding='utf-8'))
        self.assertEqual(cleanup['owned_fixture_cwd_processes'], [])
        for owner in cleanup['owners']:
            self.assertTrue(owner['auth_copy_absent'])
            self.assertTrue(all(not v for v in owner['known_pids_exist'].values()))
        self.assertTrue(r['cleanup']['auth_removed'])
        self.assertTrue(r['cleanup']['runtime_stopped'])
        self.assertTrue(all('result' in a['response'] for a in r['archived_threads']))
        for line in (root / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
            expected, name = line.split(None, 1)
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected, name)


if __name__ == '__main__':
    unittest.main()
