#!/usr/bin/env python3
"""Create deterministic standalone-skill and Agent Plugin ZIP packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile

EXCLUDED_NAMES = {'.DS_Store', 'INSTALL.md'}
EXCLUDED_SUFFIXES = {'.zip', '.skill'}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def files_under(root: Path):
    result = []
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'symlinks are forbidden in packages: {path}')
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDED_NAMES or part == '__pycache__' for part in rel.parts):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES or path.suffix == '.pyc':
            continue
        parts = rel.parts
        if 'registries-snapshot' in parts and path.suffix.lower() == '.json':
            continue
        result.append(path)
    return sorted(result, key=lambda p: p.relative_to(root).as_posix())


def zip_info(name: str, content: bytes):
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.extra = b''
    info.comment = b''
    mode = 0o755 if content.startswith(b'#!') else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.file_size = len(content)
    return info


def add_tree(zf, source: Path, root_name: str):
    for path in files_under(source):
        rel = path.relative_to(source).as_posix()
        data = path.read_bytes()
        zf.writestr(zip_info(f'{root_name}/{rel}', data), data)


def build_skill(plugin: Path, out: Path):
    name = plugin.name
    skill = plugin / 'skills' / name
    if not (skill / 'SKILL.md').is_file():
        raise ValueError(f'canonical skill missing: {skill}')
    entries = [(f'{name}/{p.relative_to(skill).as_posix()}', p.read_bytes()) for p in files_under(skill)]
    for license_name in ('LICENSE', 'NOTICE.md'):
        source = plugin / license_name
        if source.is_file():
            data = source.read_bytes()
            if license_name == 'NOTICE.md':
                data = data.replace(f'skills/{name}/'.encode('utf-8'), b'')
            entries.append((f'{name}/{license_name}', data))
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for rel, data in sorted(entries, key=lambda item: item[0]):
            zf.writestr(zip_info(rel, data), data)


def build_plugin(plugin: Path, out: Path):
    if not (plugin / 'plugin.json').is_file():
        raise ValueError(f'plugin manifest missing: {plugin}')
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        add_tree(zf, plugin, plugin.name)


def build_all(repo: Path, kind: str, names: list[str], output_root: Path):
    plugins_root = repo / 'plugins'
    discovered = {p.name: p for p in plugins_root.glob('pepper-*') if (p / 'plugin.json').is_file()}
    selected = names or sorted(discovered)
    unknown = set(selected) - set(discovered)
    if unknown:
        raise ValueError('unknown plugins: ' + ', '.join(sorted(unknown)))
    products = {}
    for name in selected:
        plugin = discovered[name]
        version = json.loads((plugin / 'plugin.json').read_text(encoding='utf-8'))['version']
        target = output_root / name / version
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix=f'.{version}.build-', dir=target.parent))
        try:
            # Every invocation refreshes the pair: never carry forward a stale sibling.
            build_skill(plugin, tmp_dir / f'{name}.zip')
            build_plugin(plugin, tmp_dir / f'{name}.plugin.zip')
            tmp_dir.chmod(0o755)
            manifest_lines = []
            for archive in sorted(tmp_dir.glob('*.zip'), key=lambda p:p.name):
                archive.chmod(0o644)
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                manifest_lines.append(f'{digest}  {archive.name}')
                products[f'{name}/{version}/{archive.name}'] = digest
            (tmp_dir / 'SHA256SUMS').write_text('\n'.join(manifest_lines) + '\n', encoding='ascii')
            (tmp_dir / 'SHA256SUMS').chmod(0o644)
            backup = None
            if target.exists():
                backup = target.with_name(target.name + '.previous')
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(target, backup)
            try:
                os.replace(tmp_dir, target)
            except Exception:
                if backup and backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
            if backup and backup.exists():
                shutil.rmtree(backup)
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
        print(f'packaged: {name} {version} ({kind})')
    return products


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=('skill', 'plugin', 'all'), required=True,
                        help='compatibility selector; every invocation rebuilds both archive kinds')
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('names', nargs='*')
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    output = (args.output_root or repo / 'dist').resolve()
    build_all(repo, args.kind, args.names, output)

if __name__ == '__main__':
    main()
