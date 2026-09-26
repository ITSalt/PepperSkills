# Комплект OpenAI review

Локальный проект комплекта. Публикация и отправка на ревью не выполнены.

- `listing.json` — название, описания, издатель, starter prompt, категория,
  пути логотипа, URL и предложенные регионы US, CA, GB, DE, FR.
- `../assets/logo.svg`, `../assets/logo.png` — подготовленный логотип 512 × 512.
- `support.md`, `privacy.md`, `terms.md` — тексты для публикации.
- `../submission-tests.json`, `fixtures/`, `run_tests.py` — 5 положительных и
  3 отрицательных сценария, воспроизводимые данные и JSON-результаты.

Предложенные регионы — стартовый вариант для подтверждения издателем, а не
автоматическая географическая настройка. Тематика законодательства РФ не
означает доступность OpenAI в РФ. Доступность стран сверяется в форме подачи.

## Воспроизведение

Из каталога плагина:

```bash
python3 submission/run_tests.py --out /tmp/pepper-submission-results
```

В каждом сценарии сохраняются findings и Markdown-отчёт; общий результат —
`results.json`. Это детерминированная проверка скриптов, не оценка ответов живой
модели. Исходные prompt и expected остаются заданием для ручного прогона в клиенте.

Браузерная фикстура дополнительно проверяет работающий, сломанный и недоступный
отказ. Из каталога скилла:

```bash
uv run --no-project --with playwright python -m playwright install chromium
uv run --no-project --with playwright scripts/test_browser_scenarios.py --out /tmp/pepper-browser-qa
```

## Перед подачей

Подтвердить проекты privacy/terms, издателя и регионы. Опубликовать эти файлы
по планируемым URL из listing.json и проверить их без авторизации. После этого
перенести подтверждённые policy URL в `plugin.json` и перегенерировать адаптеры.
Подтвердить Developer Identity в OpenAI Platform. Пройти установку, обновление,
отключение и тестовые диалоги в целевых клиентах. Финальный ZIP пересобрать.

Требования к комплекту: https://developers.openai.com/plugins/deploy/submission.
