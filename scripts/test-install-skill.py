#!/usr/bin/env python3
"""install-skill.sh: fresh copy, idempotent refresh, refusals; no network."""
import filecmp
import json
from pathlib import Path
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
    print('PASS install-skill.sh: copy, idempotent refresh, default destination, refusals')


if __name__ == '__main__':
    main()
