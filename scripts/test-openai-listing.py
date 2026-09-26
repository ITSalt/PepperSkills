#!/usr/bin/env python3
"""Regress final directory limits that the portable package schema permits."""
import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('manifests', ROOT / 'scripts/sync-plugin-manifests.py')
manifests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifests)
source = json.loads((ROOT / 'plugins/pepper-ru-web-compliance/plugin.json').read_text())
for field, limit in {'displayName': 30, 'shortDescription': 30,
                     'longDescription': 4000, 'developerName': 80}.items():
    for value, valid in [('Я' * limit, True), ('Я' * (limit + 1), False), (' ', False),
                         ('line\nbreak', field == 'longDescription')]:
        data = copy.deepcopy(source)
        data['extensions']['com.openai']['interface'][field] = value
        try:
            manifests.validate_openai_listing(data)
        except ValueError:
            assert not valid, (field, value)
        else:
            assert valid, (field, value)
for plugin in (ROOT / 'plugins').glob('*/plugin.json'):
    manifests.validate_openai_listing(json.loads(plugin.read_text()))
print('PASS OpenAI final listing limits, including Cyrillic and overlong package-valid text')
