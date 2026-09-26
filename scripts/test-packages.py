#!/usr/bin/env python3
"""Validate built ZIP contents, extracted offline checks, and archive determinism."""
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_document_paths(document, package_root):
    """Check actual local Markdown links and resource paths outside command examples."""
    text = document.read_text(encoding='utf-8')
    text = re.sub(r'^```.*?^```[^\n]*$', '', text, flags=re.M | re.S)
    targets = re.findall(r'\]\(([^)]+)\)', text)
    targets += re.findall(r'`((?:(?:skills|scripts|assets|references|examples|evals)/)[^`\s]+)`', text)
    for target in targets:
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
            continue
        target = target.split('#', 1)[0]
        resolved = (document.parent / target).resolve()
        assert resolved.is_relative_to(package_root.resolve()), (document, target, 'outside package')
        assert resolved.exists(), (document, target, 'missing local resource')


def main():
    plugins = sorted(p for p in (ROOT / 'plugins').glob('pepper-*') if (p / 'plugin.json').is_file())
    archives = []
    for plugin in plugins:
        version = json.loads((plugin / 'plugin.json').read_text(encoding='utf-8'))['version']
        directory = ROOT / 'dist' / plugin.name / version
        assert stat.S_IMODE(directory.stat().st_mode) == 0o755, directory
        product_archives = sorted(directory.glob('*.zip'))
        expected = ''.join(f'{sha(p)}  {p.name}\n' for p in product_archives)
        assert (directory / 'SHA256SUMS').read_text(encoding='ascii') == expected, directory
        archives.extend(product_archives)
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
                skill_root = root / 'skills' / name
                submission = root / 'submission/run_tests.py'
                if submission.is_file():
                    subprocess.run([sys.executable, str(submission), '--out', str(destination / 'results')],
                                   cwd=root, check=True, stdout=subprocess.DEVNULL)
                for asset in ('logo', 'composerIcon'):
                    rel = manifest.get('extensions', {}).get('com.openai', {}).get('interface', {}).get(asset)
                    if rel:
                        assert (root / rel).is_file(), rel
            else:
                assert (root / 'SKILL.md').is_file()
                assert (root / 'LICENSE').is_file()
                skill_root = root
            for document in [root / 'LICENSE', root / 'NOTICE.md', skill_root / 'SKILL.md']:
                if document.is_file():
                    check_document_paths(document, root)
            for script_name in ('selftest.py', 'test_modernization.py', 'run_evals.py'):
                script = skill_root / 'scripts' / script_name
                if script.is_file():
                    command = [sys.executable, str(script)]
                    if script.name == 'run_evals.py':
                        command.append('--check-only')
                    subprocess.run(command, cwd=skill_root, check=True, stdout=subprocess.DEVNULL)
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
            kind = 'skill' if seed == 17 else 'plugin'
            # Poison old siblings: a single-kind invocation must refresh both ZIPs.
            for source in archives:
                destination = output / source.relative_to(ROOT / 'dist')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b'STALE ARCHIVE')
            old_umask = __import__('os').umask(0o077 if seed == 17 else 0o027)
            env = __import__('os').environ.copy()
            env['TZ'] = 'Pacific/Honolulu' if seed == 17 else 'Europe/Moscow'
            try:
                subprocess.run([sys.executable, str(ROOT / 'scripts/package.py'), '--kind', kind,
                                '--repo-root', str(copied_root), '--output-root', str(output)],
                               check=True, env=env)
            finally:
                __import__('os').umask(old_umask)
            for source in archives:
                relative = source.relative_to(ROOT / 'dist')
                rebuilt = output / relative
                assert stat.S_IMODE(rebuilt.parent.stat().st_mode) == 0o755
                assert sha(source) == sha(rebuilt), f'archive changed with source environment: {source.name}'
    print('PASS reproducible ZIP metadata across file order, mtime, mode, umask, TZ, and source roots')


if __name__ == '__main__':
    main()
