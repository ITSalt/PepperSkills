#!/usr/bin/env python3
"""Offline macOS boundary grading tests; no credentials or model calls."""
import importlib.util
import copy
import hashlib
import json
from pathlib import Path
import os
import socket
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('mac_gate', Path(__file__).with_name('probe-orchestrator-macos-stdio.py'))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class MacBoundaryTests(unittest.TestCase):
    def snap(self, unix='', internet='', **changes):
        r = {'unix': {'returncode': 1, 'stdout': unix, 'stderr': ''},
             'internet': {'returncode': 1, 'stdout': internet, 'stderr': ''}}
        r.update(changes)
        return r

    def test_anonymous_connected_pairs_are_not_named_rpc_listeners(self):
        r = self.snap('COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n'
            'codex 12 fixture 8u unix 0x123 0t0 ->0xabcd\n',
            'COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n'
            'codex 12 fixture 33u IPv4 0x123 0t0 TCP 192.0.2.1:5000->192.0.2.2:443 (ESTABLISHED)\n')
        self.assertTrue(gate.no_reachable_listener(r))

    def test_named_unconnected_listening_unknown_rows_and_errors_block(self):
        header = 'COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n'
        for row in ('codex 12 fixture 8u unix 0x123 0t0 /fixture/owner.sock\n',
                    'codex 12 fixture 8u unix 0x123 0t0\n', 'unexpected row\n'):
            self.assertFalse(gate.no_reachable_listener(self.snap(header + row)))
        self.assertFalse(gate.no_reachable_listener(self.snap(internet=header +
            'codex 12 fixture 33u IPv4 0x123 0t0 TCP 127.0.0.1:5000 (LISTEN)\n')))
        self.assertFalse(gate.no_reachable_listener({}))
        r = self.snap(); r['unix']['stderr'] = 'permission denied'
        self.assertFalse(gate.no_reachable_listener(r))

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS lsof positive control')
    def test_real_named_owner_listener_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp, socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(Path(temp) / 'listener.sock')); sock.listen(1)
            self.assertFalse(gate.snapshot(os.getpid())['no_listener'])

    def test_empty_fake_timeout_and_missing_surface_evidence_never_pass(self):
        for r in ({}, {'error': 'timeout'}, {'shell_result': {'writes': {'x': {'ok': False, 'errno': 1}}}}):
            self.assertTrue(all(v != 'PASS' for v in gate.assess(r).values()))
            self.assertIsNone(gate.tool_surface(r))

    def evidence(self):
        p = Path(__file__).resolve().parents[1] / 'docs/validation/evidence/orchestrator-private-stdio-macos-20261031'
        return p, json.loads((p / 'native-run.json').read_text(encoding='utf-8'))

    def test_recorded_native_provenance_regrade_profile_and_cleanup(self):
        p, r = self.evidence()
        normalize = lambda f: f.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(r['environment']['source_sha256'], hashlib.sha256(normalize(p / 'executed-probe-v1.py')).hexdigest())
        self.assertEqual(r['environment']['library_sha256'], hashlib.sha256(normalize(gate.LIB)).hexdigest())
        assessment = json.loads((p / 'assessment.json').read_text(encoding='utf-8'))
        self.assertEqual(assessment['grader_sha256'], hashlib.sha256(normalize(Path(gate.__file__))).hexdigest())
        self.assertEqual(assessment['verdicts'], gate.assess(r))
        self.assertTrue(all(v == 'PASS' for v in gate.assess(r).values()))
        self.assertEqual(r['verdicts']['RPC_FD_isolation'], 'INCONCLUSIVE')
        self.assertEqual(r['model_turns_requested'], 4)
        item, shell = gate.native_shell(r)
        self.assertEqual(shell, r['shell_result']); self.assertEqual(item, r['native_shell_item'])
        self.assertTrue(gate.tool_surface(r)['verified'])
        for t in r['threads'].values():
            self.assertEqual(t['sandbox']['type'], 'workspaceWrite')
            self.assertTrue(t['sandbox']['networkAccess'])
            self.assertEqual(t['sandbox']['writableRoots'], [])
            self.assertEqual(t['runtimeWorkspaceRoots'], [t['cwd']])
            self.assertEqual(t['approvalPolicy'], 'on-request')
            self.assertEqual(t['approvalsReviewer'], 'user')
        cleanup = json.loads((p / 'cleanup.json').read_text(encoding='utf-8'))
        self.assertTrue(cleanup['auth_absent']); self.assertTrue(cleanup['stop']['waited'])
        self.assertFalse(any(cleanup['known_pids_exist'].values()))
        self.assertTrue(all(a['response'].get('result') == {} for a in cleanup['archives']))
        for row in (p / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
            expected, name = row.split(None, 1)
            self.assertEqual(hashlib.sha256((p / name).read_bytes()).hexdigest(), expected)

    def test_mismatched_native_output_actor_or_surface_blocks(self):
        _, r = self.evidence()
        fake = copy.deepcopy(r); fake['shell_result']['caller'] = 'forged'
        self.assertNotEqual(gate.assess(fake)['RPC_FD_isolation'], 'PASS')
        fake = copy.deepcopy(r); fake['module_turn'] = 'other'
        self.assertNotEqual(gate.assess(fake)['host_integrity'], 'PASS')
        fake = copy.deepcopy(r)
        fake['events'] = [e for e in fake['events'] if e['message'].get('method') != 'rawResponseItem/completed']
        self.assertNotEqual(gate.assess(fake)['RPC_FD_isolation'], 'PASS')


if __name__ == '__main__':
    unittest.main()
