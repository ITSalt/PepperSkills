#!/usr/bin/env python3
"""Reject fabricated shell evidence in explicit paid acceptance graders."""
import importlib.util
from pathlib import Path
import shlex
import unittest

spec = importlib.util.spec_from_file_location('live_probe', Path(__file__).with_name('test-orchestrator-private-autonomy-live.py'))
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class CommandProvenanceTests(unittest.TestCase):
    def item(self, command):
        return {'type': 'commandExecution', 'command': command, 'cwd': '/fixture/module',
                'status': 'completed', 'exitCode': 0}

    def test_exact_native_argv_including_shell_wrapper(self):
        command = shlex.join(['/python', '-I', '-S', '-B', '/owner/helper.py', '--boundary', '/owner/plan with spaces.json'])
        for value in (command, shlex.join(['/bin/zsh','-lc',command]), shlex.join(['/bin/bash','-c',command])):
            self.assertTrue(probe.exact_command(self.item(value), command, '/fixture/module'))

    def test_echoed_json_path_or_extra_shell_operations_are_not_execution(self):
        command = '/python -I -S -B /owner/helper.py --boundary /owner/plan.json'
        for value in ("echo '/owner/plan.json {\"safe\": true}'", 'echo ' + shlex.quote(command),
                      command + '; echo forged', 'FAKE=1 ' + command, command.replace('/python','python')):
            self.assertFalse(probe.exact_command(self.item(value), command, '/fixture/module'))

    def test_wrong_cwd_failure_and_unparseable_native_command_are_inconclusive(self):
        command = '/python /owner/helper.py'
        for change in ({'cwd':'/fixture/other'}, {'exitCode':1}, {'status':'failed'}, {'command':"'unclosed"}):
            item = {**self.item(command), **change}
            self.assertFalse(probe.exact_command(item, command, '/fixture/module'))


if __name__ == '__main__':
    unittest.main()
