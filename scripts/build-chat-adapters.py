#!/usr/bin/env python3
"""Chat adapters are generated from skill sections and canonical references."""
import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('chat', ROOT / 'scripts/build-chat-prompt.py')
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)
HEADER = '<!-- GENERATED: python3 scripts/build-chat-adapters.py; edit canonical skill sources. -->\n\n'


def build():
    outputs = {}
    for name, sections in {
        'pepper-creative-mode': ['When to apply', 'When to skip', 'The two modes', 'Core protocol', 'Pattern selection', 'Hard rules'],
        'pepper-ru-web-compliance': ['Три правила, которые важнее удобства', 'Что нужно узнать до запуска', 'Основание обработки и законный интерес', 'Что отдаём пользователю', 'Чего скилл не делает'],
    }.items():
        plugin = ROOT / 'plugins' / name
        skill = plugin / 'skills' / name
        text = (skill / 'SKILL.md').read_text()
        intro = ('Ручной режим: не запускай команды и не утверждай, что сам обошёл сайт. '
                 'Запрашивай доказательства пользователя; при нехватке данных ставь UNKNOWN. '
                 'Приложи manual-checklist.md к этому диалогу.\n\n'
                 if name.endswith('compliance') else 'Apply the following protocol only to eligible tasks.\n\n')
        body = intro + '\n\n'.join('## ' + h + '\n\n' + chat.extract_section(text, h) for h in sections)
        # Inline referenced documents so a copied chat prompt is self-contained.
        import re
        refs = list(dict.fromkeys(re.findall(r'`(references/[^`]+\.md)`', body)))
        for rel in refs:
            path = skill / rel
            if path.exists():
                body = body.replace('`' + rel + '`', 'приложение «' + path.stem + '»')
                body += '\n\n## ' + path.stem + '\n\n' + path.read_text()
        outputs[plugin / 'adapters/chat/system-prompt.md'] = HEADER + body + '\n'
        short_sections = sections[:2] if name.endswith('compliance') else ['When to skip', 'Core protocol', 'Hard rules']
        compact = intro + '\n\n'.join(chat.extract_section(text, h) for h in short_sections)
        outputs[plugin / 'adapters/chat/custom-instructions.md'] = HEADER + compact + '\n'
        if name.endswith('compliance'):
            outputs[plugin / 'adapters/chat/manual-checklist.md'] = HEADER + (skill / 'references/checklist.md').read_text()
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for path, content in build().items():
        if args.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f'stale chat adapter: {path}')
        else:
            path.write_text(content)
        print(f'{"checked" if args.check else "built"}: {path.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
