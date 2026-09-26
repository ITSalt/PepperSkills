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

    # Recreate identical source files in different orders, modes, timestamps, umasks, and TZ.
    with tempfile.TemporaryDirectory(prefix='pepperskills-repro-') as raw:
        tmp = Path(raw)
        source_files = [p for p in (ROOT / 'plugins').rglob('*') if p.is_file()]
        for seed in (17, 4815):
            copied_root = tmp / f'repo-{seed}'
            copied_root.mkdir()
            order = list(source_files)
            random.Random(seed).shuffle(order)
            for index, original in enumerate(order):
                destination = copied_root / original.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(original.read_bytes())
                destination.chmod(0o600 if (index + seed) % 2 else 0o777)
                destination.touch()
            (copied_root / 'LICENSE').write_bytes((ROOT / 'LICENSE').read_bytes())
            output = tmp / f'dist-{seed}'
            old_umask = __import__('os').umask(0o077 if seed == 17 else 0o027)
            env = __import__('os').environ.copy()
            env['TZ'] = 'Pacific/Honolulu' if seed == 17 else 'Europe/Moscow'
            try:
                subprocess.run([sys.executable, str(ROOT / 'scripts/package.py'), '--kind', 'all',
                                '--repo-root', str(copied_root), '--output-root', str(output)],
                               check=True, env=env)
            finally:
                __import__('os').umask(old_umask)
            for source in archives:
                relative = source.relative_to(ROOT / 'dist')
                rebuilt = output / relative
                assert sha(source) == sha(rebuilt), f'archive changed with source environment: {source.name}'
    print('PASS reproducible ZIP metadata across file order, mtime, mode, umask, TZ, and source roots')


if __name__ == '__main__':
    main()
