#!/usr/bin/env python3
"""Check that plugin ZIPs carry client adapter components and that they are consistent.

Agent-workflow plugins ship Claude Code adapters next to the canonical skill:
`commands/`, `agents/` and `hooks/`. The plugin ZIP must include them unchanged; the
standalone skill ZIP must not depend on them.
"""
import importlib.util
import json
from pathlib import Path
import re
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('package', ROOT / 'scripts/package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def frontmatter(path):
    text = path.read_text(encoding='utf-8')
    match = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
    assert match, f'missing frontmatter: {path}'
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(':')
        if sep and not line.startswith(' '):
            fields[key.strip()] = value.strip()
    return fields, text[match.end():]


def test_fixture_packaging():
    with tempfile.TemporaryDirectory(prefix='pepperskills-components-') as raw:
        plugin = Path(raw) / 'pepper-fixture'
        files = {
            'plugin.json': '{"name": "pepper-fixture", "version": "0.0.1"}\n',
            'skills/pepper-fixture/SKILL.md': '---\nname: pepper-fixture\n---\n# Fixture\n',
            'commands/plan.md': '---\ndescription: plan\n---\nUse the skill.\n',
            'agents/reviewer.md': '---\nname: reviewer\ndescription: review\n---\nRead only.\n',
            'hooks/hooks.json': '{"hooks": {}}\n',
            'hooks/guard.py': '#!/usr/bin/env python3\nprint("guard")\n',
        }
        for rel, content in files.items():
            (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
            (plugin / rel).write_text(content, encoding='utf-8')
        plugin_zip, skill_zip = Path(raw) / 'p.zip', Path(raw) / 's.zip'
        package.build_plugin(plugin, plugin_zip)
        package.build_skill(plugin, skill_zip)
        with zipfile.ZipFile(plugin_zip) as zf:
            names = set(zf.namelist())
            for rel, content in files.items():
                name = f'pepper-fixture/{rel}'
                assert name in names, f'plugin ZIP dropped {rel}'
                assert zf.read(name).decode('utf-8') == content
            mode = stat.S_IMODE(zf.getinfo('pepper-fixture/hooks/guard.py').external_attr >> 16)
            assert mode == 0o755, 'hook script lost its executable mode'
        with zipfile.ZipFile(skill_zip) as zf:
            assert not any(n.split('/')[1] in ('commands', 'agents', 'hooks')
                           for n in zf.namelist()), 'skill ZIP must contain only the skill'
    print('PASS plugin ZIP packs commands/, agents/, hooks/ (modes kept); skill ZIP excludes them')


def test_real_plugins():
    checked = 0
    for plugin in sorted((ROOT / 'plugins').glob('pepper-*')):
        manifest = json.loads((plugin / 'plugin.json').read_text(encoding='utf-8'))
        skill = plugin / 'skills' / plugin.name
        components = sorted(p for d in ('commands', 'agents', 'hooks')
                            for p in (plugin / d).rglob('*') if p.is_file())
        if not components:
            continue
        for command in sorted((plugin / 'commands').glob('*.md')):
            fields, body = frontmatter(command)
            assert fields.get('description'), f'command without description: {command}'
            for ref in re.findall(r'`(references/[^`]+)`', body):
                assert (skill / ref).is_file(), f'{command}: missing {ref}'
        for agent in sorted((plugin / 'agents').glob('*.md')):
            fields, _ = frontmatter(agent)
            assert fields.get('name') and fields.get('description'), f'agent frontmatter: {agent}'
        hooks = plugin / 'hooks/hooks.json'
        if hooks.is_file():
            text = hooks.read_text(encoding='utf-8')
            json.loads(text)
            for rel in re.findall(r'\$\{CLAUDE_PLUGIN_ROOT\}/([^\s"\']+)', text):
                assert (plugin / rel).is_file(), f'{hooks}: missing {rel}'
        archive = ROOT / 'dist' / plugin.name / manifest['version'] / f'{plugin.name}.plugin.zip'
        with zipfile.ZipFile(archive) as zf:
            names = set(zf.namelist())
        for path in components:
            rel = f'{plugin.name}/{path.relative_to(plugin).as_posix()}'
            assert rel in names, f'{archive.name} is missing {rel}'
        checked += 1
        print(f'PASS {plugin.name}: {len(components)} adapter files consistent and packaged')
    assert checked, 'expected at least one plugin with adapter components'


def test_orchestrator_modes():
    skill = ROOT / 'plugins/pepper-orchestrator/skills/pepper-orchestrator'
    text = (skill / 'SKILL.md').read_text(encoding='utf-8')
    modes = re.findall(r'^\| `(\w+)[^`]*` \| [^|]+ \| \[references/modes/(\w+)\.md\]', text, re.M)
    assert modes, 'mode table not found in SKILL.md'
    for mode, target in modes:
        assert mode == target, (mode, target)
        assert (skill / 'references/modes' / f'{mode}.md').is_file(), mode
        assert (ROOT / 'plugins/pepper-orchestrator/commands' / f'{mode}.md').is_file(), mode
    commands = {p.stem for p in (ROOT / 'plugins/pepper-orchestrator/commands').glob('*.md')}
    for mode in commands:
        _, body = frontmatter(ROOT / 'plugins/pepper-orchestrator/commands' / f'{mode}.md')
        # A command body carries no skill base directory: it must load the skill itself.
        assert '`pepper-orchestrator:pepper-orchestrator`' in body, mode
        assert f'`{mode} $ARGUMENTS`' in body, mode
        assert '${CLAUDE_PLUGIN_ROOT}/skills/pepper-orchestrator' in body, mode
    assert commands == {m for m, _ in modes}, 'every command must map to a documented mode'
    agents = ROOT / 'plugins/pepper-orchestrator/agents'
    scout, _ = frontmatter(agents / 'orchestrator-scout.md')
    reviewer, _ = frontmatter(agents / 'orchestrator-reviewer.md')
    verifier, _ = frontmatter(agents / 'orchestrator-verifier.md')
    assert 'model' not in verifier and verifier.get('tools') == 'Read, Grep, Glob, Bash', 'verifier: read-only tools'
    assert scout.get('model') == 'opus', 'orchestrator-scout runs on opus (owner decision)'
    assert 'model' not in reviewer, 'orchestrator-reviewer inherits the orchestrator model'
    print(f'PASS pepper-orchestrator: modes, mode files and commands agree ({len(modes)}); agent models')


if __name__ == '__main__':
    test_fixture_packaging()
    test_real_plugins()
    test_orchestrator_modes()
