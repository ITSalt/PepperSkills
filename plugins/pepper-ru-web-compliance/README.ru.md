# Pepper RU Web Compliance

Плагин проверяет сайт по техническим признакам требований РФ и выдаёт
доказательства, аналитическую записку и план исправлений для разработчика,
ИИ-агента или подрядчика. Он не заменяет юридическое заключение и не пишет
юридический текст за оператора.

Основной скилл находится в `skills/pepper-ru-web-compliance/`. Ручной режим для
чатов — в `adapters/chat/`; режим выбирается по доступным инструментам, а не по
названию модели.

Для cookie и аналитики сначала определяется цель, состав данных и основание
обработки. Отсутствие баннера не считается нарушением автоматически. Для
ограниченной аналитики плагин предлагает проверить шаблон законного интереса,
минимизацию, баланс и отказ: `skills/pepper-ru-web-compliance/references/legitimate-interest.md`.

Локальная проверка:

```bash
uv run --no-project skills/pepper-ru-web-compliance/scripts/selftest.py
uv run --no-project skills/pepper-ru-web-compliance/scripts/collect.py https://example.ru --out /tmp/ru-audit
```

Python-зависимости не устанавливаются в проект проверяемого сайта. Playwright
остаётся дополнительным компонентом для браузерных доказательств.

## Browser runtime / браузерный запуск

From the installed skill directory / из каталога скилла:

```bash
uv run --no-project --with playwright python -m playwright install chromium
uv run --no-project --with playwright scripts/collect.py https://example.ru --out /tmp/ru-audit
uv run --no-project --with playwright scripts/render.py --findings /tmp/findings.json --out-dir /tmp/report --format md,html,pdf
```

Use the same user and `PLAYWRIGHT_BROWSERS_PATH` for installation and execution.

Установка и обновление: [русская инструкция](../../docs/installation-and-updates.ru.md) · [English guide](../../docs/installation-and-updates.md).

| Поверхность | Канонический путь |
| --- | --- |
| Skill | `skills/pepper-ru-web-compliance/` |
| Чат-адаптеры | `adapters/chat/` |
| Манифест плагина | `plugin.json` |
