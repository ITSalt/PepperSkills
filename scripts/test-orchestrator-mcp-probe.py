#!/usr/bin/env python3
"""Offline regressions for the read-only caller-binding reproducer; no model/network."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PATH = Path(__file__).with_name('probe-orchestrator-codex-mcp.py')
spec = importlib.util.spec_from_file_location('mcp_probe', PATH)
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_unexpected_failure_is_not_a_pass(self):
        self.assertFalse(probe.impersonation_prevented({'reachable': False, 'error': 'TypeError: wrong context manager'}, 'coord'))
        self.assertFalse(probe.impersonation_prevented({'reachable': False, 'error': 'socket timeout'}, 'coord'))
        self.assertTrue(probe.impersonation_prevented({'reachable': False, 'denied': True, 'error': 'PermissionError'}, 'coord'))
        self.assertFalse(probe.impersonation_prevented({'reachable': True, 'context': {'meta': {'threadId': 'coord'}}}, 'coord'))

    def test_read_only_surface_and_no_secret_logging(self):
        with tempfile.TemporaryDirectory(prefix='pepper-mcp-probe-test-') as temp:
            log = Path(temp) / 'events.jsonl'
            requests = [
                {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}},
                {'id': 2, 'method': 'tools/list'},
                {'id': 3, 'method': 'tools/call', 'params': {'name': 'context', 'arguments': {}, '_meta': {
                    'threadId': 'coord', 'itemId': 'forged-item', 'authorization': 'SECRET_FIXTURE_VALUE',
                    'x-codex-turn-metadata': {'thread_id': 'coord', 'turn_id': 'fake-turn', 'token': 'SECRET_FIXTURE_VALUE'}}}},
                {'id': 4, 'method': 'tools/call', 'params': {'name': 'command/exec', 'arguments': {'shell': 'forbidden'}}},
            ]
            completed = subprocess.run([sys.executable, '-I', '-S', '-B', str(PATH), '--serve', str(log)],
                input=''.join(json.dumps(r) + '\n' for r in requests), capture_output=True, text=True, check=True)
            values = [json.loads(line) for line in completed.stdout.splitlines()]
            tools = values[1]['result']['tools']
            self.assertEqual([t['name'] for t in tools], ['context'])
            self.assertTrue(tools[0]['annotations']['readOnlyHint'])
            self.assertFalse(tools[0]['inputSchema']['additionalProperties'])
            self.assertTrue(values[3]['result']['isError'])
            self.assertNotIn('SECRET_FIXTURE_VALUE', completed.stdout + log.read_text())
            self.assertEqual(json.loads(log.read_text())['meta']['itemId'], 'forged-item')

    def test_editable_report_cannot_replace_a_native_command(self):
        cwd = Path('/fixture/module')
        item = {'type': 'commandExecution', 'status': 'completed', 'exitCode': 0,
                'command': '/bin/bash -lc \'python3 -I -S /protected/probe.py --spoof unix:///fixture.sock\'',
                'cwd': str(cwd)}
        command = 'python3 -I -S /protected/probe.py --spoof unix:///fixture.sock'
        self.assertTrue(probe.exact_command(item, command, cwd))
        self.assertFalse(probe.exact_command({**item, 'command': command + '; echo fake'}, command, cwd))
        self.assertFalse(probe.exact_command({**item, 'cwd': '/fixture/other'}, command, cwd))
        self.assertFalse(probe.exact_command({**item, 'status': 'inProgress'}, command, cwd))


if __name__ == '__main__':
    unittest.main()
