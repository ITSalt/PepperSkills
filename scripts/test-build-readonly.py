#!/usr/bin/env python3
"""Stale inputs/outputs must make BOTH public builders fail without writing."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
COMPLIANCE = 'plugins/pepper-ru-web-compliance'
SKILL = COMPLIANCE + '/skills/pepper-ru-web-compliance'

def snapshot(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode, os.readlink(p) if p.is_symlink()
            else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob('*') if '.git' not in p.relative_to(root).parts and (p.is_file() or p.is_symlink())}

def git(root, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', str(root), *args])

def main():
    cases = {
        'template': ('plugins/pepper-creative-mode/adapters/chat/custom-instructions.template.md', 'append'),
        'reference': ('plugins/pepper-creative-mode/skills/pepper-creative-mode/references/when-not-to-use.md', 'append'),
        'version': (COMPLIANCE + '/plugin.json', 'version'),
        'license': ('LICENSE', 'append'),
        'listing-extra': (COMPLIANCE + '/submission/listing-extra.json', 'extra'),
        'interface': (COMPLIANCE + '/plugin.json', 'interface'),
        'install-pointer': (SKILL + '/INSTALL.md', 'append'),
        'rules-json': (SKILL + '/scripts/rules.json', 'append'),
        'signatures-json': (SKILL + '/scripts/signatures.json', 'append'),
    }
    with tempfile.TemporaryDirectory(prefix='pepperskills-stale-') as raw:
        repo = Path(raw)
        # A real temporary Git repository, without legacy aliases or build outputs.
        for name in ('plugins', 'scripts'):
            shutil.copytree(ROOT / name, repo / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(ROOT / 'LICENSE', repo / 'LICENSE')
        git(repo, 'init', '-q')
        git(repo, 'add', '.')
        git(repo, '-c', 'user.name=Build Test', '-c', 'user.email=test@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        for label, (rel, operation) in cases.items():
            path = repo / rel
            original = path.read_bytes()
            if operation == 'append':
                path.write_bytes(original + b'\nSTALE TEST\n')
            else:
                data = json.loads(original)
                if operation == 'version':
                    data['version'] = '99.0.0'
                elif operation == 'extra':
                    data['review_test'] = 'changed'
                else:
                    data['extensions']['com.openai']['interface']['displayName'] += ' changed'
                path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            before = snapshot(repo)
            status = git(repo, 'status', '--porcelain=v1', '--untracked-files=all', '--ignored')
            for builder in ('build-skills.sh', 'build-plugins.sh'):
                result = subprocess.run(['bash', str(repo / 'scripts' / builder)], cwd=repo,
                                        capture_output=True, text=True)
                assert result.returncode != 0, (label, builder, result.stdout)
                assert 'stale' in result.stderr or 'устарел' in result.stderr, (label, result.stderr)
                assert snapshot(repo) == before, (label, builder, 'filesystem changed')
                assert git(repo, 'status', '--porcelain=v1', '--untracked-files=all', '--ignored') == status
            path.write_bytes(original)
            print('PASS read-only stale rejection:', label)
        adapters = [repo / COMPLIANCE / kind / 'plugin.json'
                    for kind in ('.codex-plugin', '.claude-plugin', '.cursor-plugin')]
        originals = {path: path.read_bytes() for path in adapters}
        for path in adapters:
            path.write_text('{}\n', encoding='utf-8')
        before = snapshot(repo)
        result = subprocess.run([sys.executable, str(repo / 'scripts/sync-plugin-manifests.py'), '--check'],
                                cwd=repo, capture_output=True, text=True)
        assert result.returncode != 0
        assert all(str(path) in result.stderr for path in adapters), result.stderr
        assert snapshot(repo) == before
        for path, data in originals.items():
            path.write_bytes(data)
        print('PASS manifest check reports every stale adapter without writing')
        # Successful public wrappers must also work without the legacy tree.
        before = snapshot(repo)
        for builder in ('build-skills.sh', 'build-plugins.sh'):
            subprocess.run(['bash', str(repo / 'scripts' / builder)], cwd=repo, check=True,
                           stdout=subprocess.DEVNULL)
        after = {k: v for k, v in snapshot(repo).items() if not k.startswith('dist/')}
        assert after == before
        print('PASS builders without legacy paths')

if __name__ == '__main__':
    main()
