#!/usr/bin/env python3
"""Execute every published Bash block, unchanged, in Bash/Zsh and a private HOME."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def prepare(home):
    repo = home / 'projects/PepperSkills'
    (repo / 'scripts').mkdir(parents=True)
    for name in ('link-path.sh', 'link-skill.sh'):
        shutil.copy2(ROOT / 'scripts' / name, repo / 'scripts' / name)
    for name in ('pepper-prompt-engineer', 'pepper-creative-mode'):
        skill = repo / 'plugins' / name / 'skills' / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('# Fixture\n', encoding='utf-8')
        chat = repo / 'plugins' / name / 'adapters/chat'
        chat.mkdir(parents=True)
        for file in ('system-prompt.md', 'chat-prompt.md'):
            (chat / file).write_text('# Fixture\n', encoding='utf-8')
        legacy = repo / name
        legacy.mkdir()
        (legacy / 'anthropic').symlink_to(skill)
        (legacy / 'openai').symlink_to(chat)
        (legacy / 'chat-prompt.md').symlink_to(chat / 'chat-prompt.md')
    return repo


def snapshot(home):
    return {str(p.relative_to(home)): os.readlink(p) if p.is_symlink() else p.read_bytes()
            for p in home.rglob('*') if p.is_symlink() or p.is_file()}


def main():
    guides = [ROOT / 'docs' / f'installation-and-updates{suffix}.md' for suffix in ('', '.ru')]
    published = [re.findall(r'^```bash\n(.*?)^```', p.read_text(encoding='utf-8'), re.M | re.S)
                 for p in guides]
    assert len(published[0]) == 3 and published[0] == published[1], 'translated commands differ'
    for shell in ('bash', 'zsh'):
        assert shutil.which(shell), shell
        for guide, blocks in zip(guides, published):
            for number, block in enumerate(blocks):
                for scenario in ('new', 'shared-chain', 'healthy-legacy', 'broken-legacy', 'directory', 'unrelated'):
                    with tempfile.TemporaryDirectory(prefix='pepperskills-guide-') as raw:
                        home = Path(raw).resolve()
                        repo = prepare(home)
                        skill = repo / 'plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer'
                        if number < 2:
                            links = [(home / '.agents/skills/pepper-prompt-engineer', skill,
                                      repo / 'pepper-prompt-engineer/anthropic')]
                        else:
                            links = [(home / '.local/share/pepper-creative-mode',
                                      repo / 'plugins/pepper-creative-mode/adapters/chat',
                                      repo / 'pepper-creative-mode/openai'),
                                     (home / '.local/share/pepper-prompt-engineer-chat.md',
                                      repo / 'plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md',
                                      repo / 'pepper-prompt-engineer/chat-prompt.md')]
                        for index, (link, source, legacy) in enumerate(links):
                            link.parent.mkdir(parents=True, exist_ok=True)
                            if scenario == 'shared-chain':
                                shared = home / f'shared-{index}'
                                shared.symlink_to(source)
                                link.symlink_to(shared)
                            elif scenario == 'healthy-legacy':
                                assert legacy.exists()
                                link.symlink_to(legacy)
                                assert link.exists()
                            elif scenario == 'broken-legacy':
                                link.symlink_to(home / 'missing' / legacy.relative_to(repo))
                                assert not link.exists()
                            elif scenario == 'directory':
                                link.mkdir()
                                (link / 'preserve.txt').write_text('user data', encoding='utf-8')
                            elif scenario == 'unrelated':
                                link.symlink_to(home / 'unrelated')
                        if number == 0 and scenario == 'shared-chain':
                            agent = home / '.claude/skills/pepper-prompt-engineer'
                            agent.parent.mkdir(parents=True)
                            agent.symlink_to(links[0][0])
                        snippet = home / 'example.sh'
                        snippet.write_text(block, encoding='utf-8')
                        variables = sorted(set(re.findall(r'^(pepper_\w+)=', block, re.M)))
                        init = '\n'.join(f'{v}=sentinel' for v in variables)
                        check = '\n'.join(f'test "${v}" = sentinel || exit 94' for v in variables)
                        driver = ('set +e\nset +u\n' + init + '\n'
                                  'saved_options=$-\nsaved_directory=$PWD\n'
                                  '. "$1"\nexample_result=$?\n'
                                  'test "$-" = "$saved_options" || exit 91\n'
                                  'test "$PWD" = "$saved_directory" || exit 92\n' + check + '\n'
                                  'test "$example_result" = "$2" || exit 93\n'
                                  'printf "outer shell preserved\\n"\n')
                        before = snapshot(home)
                        expected = 1 if scenario in ('directory', 'unrelated') else 0
                        env = dict(os.environ, HOME=str(home))
                        result = subprocess.run([shell, '-c', driver, '_', str(snippet), str(expected)],
                                                cwd=home, env=env, text=True, capture_output=True)
                        assert result.returncode == 0, (shell, guide.name, number, scenario, result.stderr)
                        assert 'outer shell preserved' in result.stdout
                        if expected:
                            assert snapshot(home) == before, 'refused installation modified user files'
                        else:
                            for link, source, _ in links:
                                assert link.is_symlink() and link.resolve() == source.resolve()
                        # Running the same example twice must remain safe.
                        again = subprocess.run([shell, '-c', driver, '_', str(snippet), str(expected)],
                                               cwd=home, env=env, text=True, capture_output=True)
                        assert again.returncode == 0, again.stderr
                print(f'PASS published commands: {guide.name} block {number + 1} / {shell}')

if __name__ == '__main__':
    main()
