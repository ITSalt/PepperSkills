#!/usr/bin/env python3
"""Compare generated bodies with checkpoint goldens plus enumerated link repairs.

Golden hashes come from e2c7d4f, not from the implementation under test. The
fixture lists exact reviewed changes; no whitespace/content normalization is used.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('chat', ROOT / 'scripts/build-chat-prompts.py')
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)
goldens = json.loads((ROOT / 'scripts/fixtures/chat-goldens.json').read_text(encoding='utf-8'))
outputs = chat.build_all()
assert {str(p.relative_to(ROOT)) for p in outputs} == set(goldens['cases'])
for path, generated in outputs.items():
    rel = str(path.relative_to(ROOT))
    body = re.sub(r'^<!--.*?-->\n\n', '', generated, count=1, flags=re.S)
    case = goldens['cases'][rel]
    for change in reversed(case['intentional_changes']):
        assert body.count(change['after']) == 1, f'approved change drift: {rel}'
        body = body.replace(change['after'], change['before'], 1)
    assert hashlib.sha256(body.encode('utf-8')).hexdigest() == case['baseline_sha256'], rel
    assert not re.search(r'\]\(\.?/?references/', generated), rel
    print('PASS checkpoint chat golden:', rel)

# Labels are driven by metadata, even if a template starts with punctuation,
# a heading, lowercase Cyrillic, or prose in the other language.
for language, included, missing in (
    ('en', 'appendix “present”', 'the “absent” reference in the full skill edition'),
    ('ru', 'приложение «present»', 'справочный материал «absent» в полной версии скилла'),
):
    for prefix in ('# Heading\n', 'english introduction\n', 'русское вступление\n', '«Вступление»\n'):
        body = prefix + '`references/present.md` / `references/absent.md`\n\n## present\n'
        template = f'<!-- chat-language: {language} -->\n\n' + body
        declared, content = chat.template_language(template)
        assert content == body and declared == language
        rendered = chat.local_reference_labels(content, language=declared)
        assert included in rendered and missing in rendered
        assert rendered.startswith(prefix)
for invalid in ('no marker', '<!-- chat-language: de -->\n\nText'):
    try:
        chat.template_language(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError('missing/unsupported language must be rejected')
print('PASS explicit template languages and localized missing references')
