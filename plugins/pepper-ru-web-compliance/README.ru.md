# Pepper RU Web Compliance

> 3.0.0: вердикт по каждому пункту — нарушение с местом и правкой, риск с позицией,
> вопрос владельцу только о том, что снаружи не видно. Сборщик сам открывает вход,
> корзину и модальные формы; доразведка определяет страну и вендора получателей.
> Сетевой аудит — локальный Playwright через РФ-выход.
> Запуск: `scripts/audit.py`; РФ-шлюз `https://lts.itsalt.ru/ru-audit` уже настроен.
> Три сессии за скользящие 24 часа/IP. Регистрация и настройка VPN не нужны.
> Другой шлюз — `PEPPER_RU_GATEWAY_URL`, свой прокси — `PEPPER_RU_AUDIT_PROXY`.
> [Режимы, квоты и офлайн-повтор](skills/pepper-ru-web-compliance/references/gateway.md).

Плагин проверяет сайт по техническим признакам требований РФ и выдаёт
доказательства, аналитическую записку и план исправлений для разработчика,
ИИ-агента или подрядчика. Он не заменяет юридическое заключение и не пишет
юридический текст за оператора.

Основной скилл находится в `skills/pepper-ru-web-compliance/`. Ручной режим для
чатов — в `adapters/chat/`; режим выбирается по доступным инструментам, а не по
названию модели.

Для cookie и аналитики основание берётся из документов сайта. Нет баннера, теги
грузятся с первого визита и не заявлено ни согласие, ни законный интерес — это
нарушение. Заявлен законный интерес — риск с проверкой работающего отказа и
шаблоном декларации: `skills/pepper-ru-web-compliance/references/legitimate-interest.md`.

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
