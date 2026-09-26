#!/usr/bin/env python3
"""Verify built archives, standalone execution and filesystem symlink updates."""
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import zipfile
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
schema = json.loads((ROOT/'scripts/schemas/agent-plugin-1.0.0.json').read_text())


def run():
    archives = sorted(ROOT.glob('pepper-*/*.skill')) + sorted(ROOT.glob('plugins/*/*.plugin.zip'))
    assert len(archives) == 6, f'Expected 6 archives, found {len(archives)}'
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for archive in archives:
            destination = tmp/archive.stem
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    parts = Path(info.filename).parts
                    assert not info.filename.startswith('/') and '..' not in parts
                    assert not stat.S_ISLNK(info.external_attr >> 16), info.filename
                    assert not any(v in parts for v in ('__pycache__','.DS_Store'))
                    assert not info.filename.endswith(('.zip','.skill','.pyc'))
                z.extractall(destination)
            folder = next(destination.iterdir())
            if archive.suffix == '.zip':
                manifest=json.loads((folder/'plugin.json').read_text())
                Draft202012Validator(schema).validate(manifest)
                for key in ('logo','composerIcon'):
                    asset=manifest.get('extensions',{}).get('com.openai',{}).get('interface',{}).get(key)
                    if asset: assert (folder/asset).is_file(), asset
            else:
                script = folder/'scripts/selftest.py'
                if script.exists():
                    subprocess.run([sys.executable,str(script)],check=True,stdout=subprocess.DEVNULL)
                    subprocess.run([sys.executable,str(folder/'scripts/test_modernization.py')],check=True)
                evals=folder/'scripts/run_evals.py'
                if evals.exists(): subprocess.run([sys.executable,str(evals),'--check-only'],check=True)
            print('PASS archive',archive.relative_to(ROOT))
        source=tmp/'source'
        source.mkdir()
        skill=source/'SKILL.md'
        skill.write_text('v1')
        link=tmp/'installed-skill'
        link.symlink_to(source,target_is_directory=True)
        assert (link/'SKILL.md').read_text()=='v1'
        skill.write_text('v2')
        assert (link/'SKILL.md').read_text()=='v2'
        link.unlink()
        assert skill.read_text()=='v2'
        print('PASS filesystem symlink create/update/remove (not client acceptance)')


if __name__=='__main__':
    run()
