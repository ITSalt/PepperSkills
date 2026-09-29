#!/usr/bin/env python3
"""install-skill.sh: fresh copy, idempotent refresh, refusals; no network."""
import filecmp
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts/install-skill.sh'
EXCLUDED = {'INSTALL.md', '__pycache__', '.DS_Store'}


def run(*args, env=None, ok=True):
    result = subprocess.run(['bash', str(SCRIPT), *args], text=True, capture_output=True, env=env)
    assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
    return result


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*')
                  if not any(part in EXCLUDED or part.endswith('.pyc') for part in p.relative_to(root).parts))


def main():
    name = 'pepper-orchestrator'
    source = ROOT / 'plugins' / name / 'skills' / name
    version = json.loads((ROOT / 'plugins' / name / 'plugin.json').read_text(encoding='utf-8'))['version']
    with tempfile.TemporaryDirectory(prefix='pepperskills-install-') as raw:
        dest = Path(raw) / 'skills'
        out = run('--dest', str(dest), name).stdout
        assert f'installed {name} {version} -> {dest / name}' in out, out
        target = dest / name
        assert tree(target) == tree(source), 'copy differs from the canonical skill'
        for rel in tree(source):
            if (source / rel).is_file():
                assert filecmp.cmp(source / rel, target / rel, shallow=False), rel
        assert not (target / 'INSTALL.md').exists()
        (target / 'stale.md').write_text('left from an older version\n', encoding='utf-8')
        run('--dest', str(dest), name)
        assert not (target / 'stale.md').exists(), 'refresh must replace the whole directory'
        assert [p.name for p in dest.iterdir()] == [name], 'no temporary directories left behind'
        run('--dest', str(dest), 'pepper-unknown', ok=False)
        linked = Path(raw) / 'linked'
        linked.mkdir()
        (linked / name).symlink_to(source)
        refused = run('--dest', str(linked), name, ok=False)
        assert 'symlink' in refused.stderr and (linked / name).is_symlink()
        env = {'HOME': raw, 'PATH': '/usr/bin:/bin'}
        run(name, env=env)
        assert (Path(raw) / '.claude/skills' / name / 'SKILL.md').is_file(), 'default ~/.claude/skills'
        # A failing copy leaves no temporary directory behind (L5).
        broken = Path(raw) / 'broken'
        broken.mkdir()
        fake_bin = Path(raw) / 'bin'
        fake_bin.mkdir()
        (fake_bin / 'tar').write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
        (fake_bin / 'tar').chmod(0o755)
        failing = {'HOME': raw, 'PATH': f'{fake_bin}:/usr/bin:/bin'}
        run('--dest', str(broken), name, env=failing, ok=False)
        assert list(broken.iterdir()) == [], 'temporary directory left after a failure'
        # README fragment (EN and RU identical): a failing clone never fails the setup script (M6).
        blocks = []
        for readme in ('README.md', 'README.ru.md'):
            text = (ROOT / 'plugins' / name / readme).read_text(encoding='utf-8')
            blocks.append(re.search(r'```bash\n(# pepper-orchestrator skill.*?)```', text, re.S).group(1))
        assert blocks[0] == blocks[1], 'setup fragments differ between README languages'
        (fake_bin / 'git').write_text('#!/bin/sh\necho "git: network down" >&2\nexit 128\n', encoding='utf-8')
        (fake_bin / 'git').chmod(0o755)
        script = Path(raw) / 'setup.sh'
        script.write_text('set -e\n' + blocks[0] + 'echo setup-finished\n', encoding='utf-8')
        result = subprocess.run(['bash', str(script)], text=True, capture_output=True,
                                env={'HOME': raw, 'PATH': f'{fake_bin}:/usr/bin:/bin'})
        assert result.returncode == 0 and 'setup-finished' in result.stdout, (result.stdout, result.stderr)
        assert 'skill not installed; setup continues' in result.stderr
    print('PASS install-skill.sh: copy, idempotent refresh, default destination, refusals, cleanup, safe fragment')


if __name__ == '__main__':
    main()
