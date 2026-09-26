# Pepper RU Web Compliance

Portable technical website audit for Russian personal-data, cookie, tracker,
registry, disclosure, and infrastructure checks. It produces evidence-backed
findings and an actionable remediation plan. Legal qualification remains with
the operator and counsel.

The canonical skill is under `skills/pepper-ru-web-compliance/`; the chat adapter
is under `adapters/chat/`. Use `uv run --no-project` for helper scripts. The
plugin is skills-only and has no network service or MCP dependency.

## Browser runtime / браузерный запуск

From the installed skill directory / из каталога скилла:

```bash
uv run --no-project --with playwright python -m playwright install chromium
uv run --no-project --with playwright scripts/collect.py https://example.ru --out /tmp/ru-audit
uv run --no-project --with playwright scripts/render.py --findings /tmp/findings.json --out-dir /tmp/report --format md,html,pdf
```

Use the same user and `PLAYWRIGHT_BROWSERS_PATH` for installation and execution.
