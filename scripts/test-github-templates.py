#!/usr/bin/env python3
"""Validate GitHub issue forms, their config, CODEOWNERS and the pull request template."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FORMS = ROOT / '.github' / 'ISSUE_TEMPLATE'
TYPES = {'markdown', 'input', 'textarea', 'dropdown', 'checkboxes'}


def check_form(path):
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(data, dict), path
    for key in ('name', 'description', 'body'):
        assert data.get(key), f'{path.name}: missing {key}'
    ids = []
    for item in data['body']:
        assert item.get('type') in TYPES, f'{path.name}: unknown type {item.get("type")}'
        if item['type'] != 'markdown':
            assert item.get('id'), f'{path.name}: field without id'
            assert (item.get('attributes') or {}).get('label'), f'{path.name}: {item["id"]} without label'
            ids.append(item['id'])
    assert len(ids) == len(set(ids)), f'{path.name}: duplicate ids'
    return data


def main():
    forms = sorted(p for p in FORMS.glob('*.yml') if p.name != 'config.yml')
    assert forms, 'no issue forms'
    parsed = {p.name: check_form(p) for p in forms}
    agent = parsed['agent-bug-report.yml']
    assert set(agent['labels']) == {'bug', 'from-agent', 'needs-triage'}, agent['labels']
    config = yaml.safe_load((FORMS / 'config.yml').read_text(encoding='utf-8'))
    assert config['blank_issues_enabled'] is False
    assert any('SECURITY.md' in link['url'] for link in config['contact_links']), 'config.yml links SECURITY.md'
    owners = (ROOT / '.github' / 'CODEOWNERS').read_text(encoding='utf-8').splitlines()
    assert '* @ITSalt' in owners, 'CODEOWNERS: * @ITSalt'
    template = (ROOT / '.github' / 'PULL_REQUEST_TEMPLATE.md').read_text(encoding='utf-8')
    assert 'Fixes #' in template and 'private traces' in template
    print(f'PASS GitHub templates: {len(forms)} issue forms, config, CODEOWNERS, PR template')


if __name__ == '__main__':
    main()
