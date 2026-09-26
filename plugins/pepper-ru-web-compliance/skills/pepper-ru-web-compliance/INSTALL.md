# Установка и режимы проверки

Канонический пакет находится в плагине `plugins/pepper-ru-web-compliance/`.
Он не зависит от соседних каталогов и работает в средах с кодом, браузером и
сетью, а без них переводит проверку в ручной режим. Отсутствие cookie-баннера
не считается нарушением без установленной цели, состава данных и основания
обработки.

## Плагин

Установите каталог `plugins/pepper-ru-web-compliance` через каталог плагинов
своего клиента. Для локальной проверки или разработки можно собрать архив:

```bash
./scripts/build-plugins.sh pepper-ru-web-compliance
```

Архив содержит реальные файлы плагина; внешние симлинки в него не попадают.

## Клон и симлинк

Связывайте только канонический скилл, а не весь плагин:

```bash
ln -s /path/to/PepperSkills/plugins/pepper-ru-web-compliance/skills/pepper-ru-web-compliance \
  .agents/skills/pepper-ru-web-compliance
```

Для Claude Code используйте `.claude/skills/`, для Codex и Pi — `.agents/skills/`,
для Cursor — `.agents/skills/` или `.cursor/skills/`. После обновления клона
перечитайте скиллы или откройте новую сессию. Внешний симлинк всего плагина в
`~/.cursor/plugins/local` не используется: Cursor его пропускает.

## Команды из каталога распакованного скилла

Браузерный режим и PDF (зависимость добавляется именно в uv-окружение):

```bash
uv run --no-project --with playwright python -m playwright install chromium
uv run --no-project --with playwright scripts/collect.py https://example.ru --out /tmp/ru-audit --max-pages 20
uv run --no-project scripts/detect.py --artifacts /tmp/ru-audit --out /tmp/findings.json
uv run --no-project --with playwright scripts/render.py --findings /tmp/findings.json --out-dir /tmp/report --format md,html,pdf
```

Установка и запуск должны использовать одного пользователя и одинаковый
`PLAYWRIGHT_BROWSERS_PATH`, если он задан. Артефакты храните вне скилла.
Для воспроизводимости релиза зафиксируйте версию Playwright в обеих командах.

Режим без браузера, только стандартная библиотека (не проверяет сеть и отказ):

```bash
python3 scripts/selftest.py
python3 scripts/collect.py https://example.ru --out /tmp/ru-audit-static --no-browser
python3 scripts/detect.py --artifacts /tmp/ru-audit-static --out /tmp/findings-static.json
python3 scripts/render.py --findings /tmp/findings-static.json --out-dir /tmp/report-static --format md,html
```

## Ручной режим

Без кода используйте находящиеся внутри этого пакета `references/checklist.md`,
`references/llm-analysis.md`, `references/report-format.md` и
`references/legitimate-interest.md`. Запрашивайте наблюдения пользователя,
не выдавайте отсутствие данных за PASS. Согласие, уведомление и возражение
фиксируются раздельно. Чат-адаптеры — дополнительный вариант в полном плагине;
распакованный `.skill` от них не зависит.

## Отдельная смысловая проверка

Машинные наблюдения остаются в `status`; подтверждение проверяющего хранится
в `semantic_review`. Формат и привязка к артефактам описаны в
`references/semantic-review.md`. Изменение артефактов аннулирует прежнюю оценку.
