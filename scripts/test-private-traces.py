#!/usr/bin/env python3
"""Offline test of check-private-traces.py on throwaway git repositories."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('traces', HERE / 'check-private-traces.py')
traces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(traces)
ENV = {**os.environ, 'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/dev/null'}
MAC = '/' + 'Users/x/projects/app/file.py'
LINUX = '/' + 'home/x/app'
WINDOWS = 'C:' + '\\' + 'Users' + '\\' + 'x\\app'


def repo(files):
    root = Path(tempfile.mkdtemp(prefix='private-traces-'))
    subprocess.run(['git', 'init', '-q', str(root)], check=True, env=ENV)
    for rel, content in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            (root / rel).write_bytes(content)
        else:
            (root / rel).write_text(content, encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', '-A'], check=True, env=ENV)
    return root


def archive(text):
    path = Path(tempfile.mkdtemp()) / 'a.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('pkg/notes.md', text)
    return path.read_bytes()


def main():
    clean = repo({'docs/a.md': 'See [x](/plugins/x/detect.py:1) and ~/projects/example and https://example.com\n'})
    assert traces.findings(clean) == [], traces.findings(clean)
    assert traces.main(['--root', str(clean)]) == 0
    for label, text in (('macOS', MAC), ('Linux', LINUX), ('Windows', WINDOWS)):
        dirty = repo({'docs/a.md': f'line one\nbuilt: {text}\n'})
        found = traces.findings(dirty)
        assert found == ['docs/a.md:2: absolute home-directory path'], (label, found)
        assert traces.main(['--root', str(dirty)]) == 1
    packed = repo({'pkg/a.skill': archive(f'x {MAC}\n')})
    assert traces.findings(packed) == ['pkg/a.skill!pkg/notes.md:1: absolute home-directory path']
    termed = repo({'docs/a.md': 'Report on Secret-Project results\n', '.gitignore': '.private-terms.local\n'})
    assert traces.findings(termed) == []
    (termed / '.private-terms.local').write_text('# private names\nsecret-project\n', encoding='utf-8')
    assert traces.findings(termed) == [f'docs/a.md:1: private term from {traces.TERMS_FILE}']
    untracked = repo({'docs/a.md': 'clean\n'})
    (untracked / 'notes.txt').write_text(MAC, encoding='utf-8')
    assert traces.findings(untracked) == [], 'only tracked files are checked'
    print('PASS private traces: home paths (macOS, Linux, Windows), archives, local terms, tracked only')


if __name__ == '__main__':
    main()
