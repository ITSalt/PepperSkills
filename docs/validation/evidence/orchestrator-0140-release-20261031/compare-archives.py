#!/usr/bin/env python3
"""Compare a rebuilt accepted 0d6311a archive pair with public 0.14.0.
Usage: python3 compare-archives.py ACCEPTED_DIR RELEASE_DIR > comparison.json
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


old, new = map(Path, sys.argv[1:])
result = {'version': '0.14.0',
          'accepted_runtime_commit': '0d6311a2234dbfccd15eddda7a06a9d28abc3c7d',
          'archives': {}}
expected = {
    'pepper-orchestrator.plugin.zip': '57722062c318161abc7e477b9ae06e584289849743e83bd618b76ac8d4a4253a',
    'pepper-orchestrator.zip': '7bc64b887591f175097d3aff2f149d7940403ce71c64fc0dfc64079333d89cab',
}
for name, accepted_sha in expected.items():
    assert digest((old / name).read_bytes()) == accepted_sha
    with zipfile.ZipFile(old / name) as a, zipfile.ZipFile(new / name) as b:
        assert sorted(a.namelist()) == sorted(b.namelist())
        changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
        assert changed and all(n.endswith('.md') for n in changed)
        assert not any('/scripts/' in n or n.endswith('/SKILL.md') for n in changed)
        scripts = [n for n in a.namelist() if '/scripts/' in n]
        assert all(a.read(n) == b.read(n) for n in scripts)
        equal = [n for n in a.namelist() if n not in changed]
        manifest = ''.join(digest(a.read(n)) + '  ' + n + '\n' for n in sorted(equal))
        result['archives'][name] = {
            'live_accepted_sha256': accepted_sha,
            'public_release_sha256': digest((new / name).read_bytes()),
            'entries': len(a.namelist()), 'added_entries': [], 'removed_entries': [],
            'changed_markdown_entries': changed, 'identical_entries': len(equal),
            'identical_script_entries': len(scripts),
            'identical_entries_manifest_sha256': digest(manifest.encode()),
            'all_scripts_and_non_markdown_identical': True,
        }
print(json.dumps(result, indent=2))
