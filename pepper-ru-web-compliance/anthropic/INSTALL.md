# Установка

## Claude Code

Скопировать каталог в папку скиллов под именем, совпадающим с полем `name`
в `SKILL.md`:

```bash
# личные скиллы
cp -R anthropic ~/.claude/skills/pepper-ru-web-compliance

# или для конкретного проекта
cp -R anthropic <project>/.claude/skills/pepper-ru-web-compliance
```

Проверить, что скилл виден: в новой сессии спросить «проверь сайт example.ru на
соответствие требованиям РФ».

## Claude Desktop и claude.ai

Скачать `pepper-ru-web-compliance.skill` из релиза и загрузить через
*Settings → Capabilities → Skills → Upload*.

## Зависимости

Их нет — всё работает на стандартной библиотеке Python 3.10 и новее.

Опционально ставится Playwright: без него сбор идёт без рендера страниц, и
правила про cookie-баннер, состояние чекбоксов и сетевые запросы уходят в
`UNKNOWN`. С ним покрытие полное.

```bash
pip install playwright && python -m playwright install chromium
```

`PyYAML` тоже не обязателен: рядом с `rules.yaml` и `signatures.yaml` лежат
сгенерированные JSON-двойники, которые читаются стандартной библиотекой.
YAML остаётся форматом для правки человеком.

## Проверка установки

```bash
cd ~/.claude/skills/pepper-ru-web-compliance
python3 scripts/selftest.py                # регрессии детекторов, без сети
python3 scripts/registries.py probe        # что доступно с этой машины
python3 scripts/collect.py https://example.ru --out /tmp/a --max-pages 5
python3 scripts/detect.py --artifacts /tmp/a --out /tmp/f.json
python3 scripts/render.py --findings /tmp/f.json --out-dir /tmp/report --format md,html,pdf
```

Раскладку чек-листа в HTML и PDF выбирает `--layout`: `stacked` (по умолчанию),
`twoline` или `wide`.

Если `probe` показывает недоступные реестры — это нормально за пределами РФ.
Часть источников подхватится с зеркала, для остальных смотрите
`references/registries.md`.
