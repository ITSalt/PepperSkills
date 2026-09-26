#!/usr/bin/env python3
"""Validate built ZIP contents, extracted offline checks, and archive determinism."""
import hashlib
import json
from pathlib import Path
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plugins = sorted(p for p in (ROOT / 'plugins').glob('pepper-*') if (p / 'plugin.json').is_file())
    archives = sorted((ROOT / 'dist').glob('pepper-*/*/*.zip'))
    assert len(archives) == len(plugins) * 2, f'Expected two ZIPs per product; found {len(archives)}'
    for archive in archives:
        name = archive.name.split('.plugin.zip')[0] if archive.name.endswith('.plugin.zip') else archive.stem
        is_plugin = archive.name.endswith('.plugin.zip')
        with tempfile.TemporaryDirectory(prefix='pepperskills-unpack-') as raw:
            destination = Path(raw)
            with zipfile.ZipFile(archive) as zf:
                names = zf.namelist()
                assert names == sorted(names), f'unsorted entries: {archive}'
                assert len(names) == len(set(names)), f'duplicate entries: {archive}'
                assert all(n.startswith(name + '/') and '..' not in Path(n).parts for n in names)
                for info in zf.infolist():
                    mode = info.external_attr >> 16
                    assert not stat.S_ISLNK(mode), info.filename
                    assert info.date_time == (1980, 1, 1, 0, 0, 0)
                    assert info.compress_type == zipfile.ZIP_STORED
                    assert info.extra == b'' and info.comment == b''
                    assert stat.S_IMODE(mode) in (0o644, 0o755)
                    parts = Path(info.filename).parts
                    assert not any(v in parts for v in ('__pycache__', '.DS_Store', 'INSTALL.md'))
                    assert not info.filename.endswith(('.zip', '.skill', '.pyc'))
                    assert not ('registries-snapshot' in parts and info.filename.endswith('.json'))
                zf.extractall(destination)
            root = destination / name
            if is_plugin:
                manifest = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
                assert manifest['name'] == name
                assert (root / 'skills' / name / 'SKILL.md').is_file()
                for asset in ('logo', 'composerIcon'):
                    rel = manifest.get('extensions', {}).get('com.openai', {}).get('interface', {}).get(asset)
                    if rel:
                        assert (root / rel).is_file(), rel
            else:
                assert (root / 'SKILL.md').is_file()
                assert (root / 'LICENSE').is_file()
                skill_checks = [root / 'scripts/selftest.py', root / 'scripts/test_modernization.py',
                                root / 'scripts/run_evals.py']
                for script in skill_checks:
                    if script.is_file():
                        command = [sys.executable, str(script)]
                        if script.name == 'run_evals.py':
                            command.append('--check-only')
                        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
            print(f'PASS package {archive.relative_to(ROOT)}')

    # Change source mtimes and process umask in a copied tree; package bytes must stay fixed.
    with tempfile.TemporaryDirectory(prefix='pepperskills-repro-') as raw:
        tmp = Path(raw)
        copied_plugins = tmp / 'plugins'
        shutil.copytree(ROOT / 'plugins', copied_plugins, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.zip', '*.skill'))
        copied_root = tmp / 'repo'
        copied_root.mkdir()
        shutil.move(copied_plugins, copied_root / 'plugins')
        shutil.copy2(ROOT / 'LICENSE', copied_root / 'LICENSE')
        shutil.copy2(ROOT / 'scripts/package.py', copied_root / 'package.py')
        files = [p for p in (copied_root / 'plugins').rglob('*') if p.is_file()]
        random.Random(4815).shuffle(files)
        for index, path in enumerate(files):
            path.touch()
            path.chmod(0o600 if index % 2 else 0o777)
        old_umask = __import__('os').umask(0o077)
        try:
            subprocess.run([sys.executable, str(copied_root / 'package.py'), '--kind', 'all',
                            '--repo-root', str(copied_root), '--output-root', str(tmp / 'dist')], check=True)
        finally:
            __import__('os').umask(old_umask)
        for source in archives:
            relative = source.relative_to(ROOT / 'dist')
            repeated = tmp / 'dist' / relative
            assert sha(source) == sha(repeated), f'archive changed with source metadata: {source.name}'
    print('PASS reproducible ZIP metadata, source mtime, umask, and file traversal order')


if __name__ == '__main__':
    main()
