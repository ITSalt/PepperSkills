# Pepper RU Web Compliance

> 3.0.0: вердикт по каждому пункту — нарушение с местом и правкой, риск с позицией,
> вопрос владельцу только о том, что снаружи не видно. Сборщик сам открывает вход,
> корзину и модальные формы; доразведка определяет страну и вендора получателей.
> Сетевой аудит — локальный Playwright через РФ-выход.
> Запуск: `scripts/audit.py`; РФ-шлюз `https://lts.itsalt.ru/ru-audit` уже настроен.
> Три сессии за скользящие 24 часа/IP. Регистрация и настройка VPN не нужны.
> Другой шлюз — `PEPPER_RU_GATEWAY_URL`, свой прокси — `PEPPER_RU_AUDIT_PROXY`.
> [Режимы, квоты и офлайн-повтор](skills/pepper-ru-web-compliance/references/gateway.md).

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

Installation and update models: [English guide](../../docs/installation-and-updates.md) · [Русская версия](../../docs/installation-and-updates.ru.md).

| Surface | Canonical location |
| --- | --- |
| Skill | `skills/pepper-ru-web-compliance/` |
| Chat adapters | `adapters/chat/` |
| Plugin manifest | `plugin.json` |
