# CRAFT+ Prompt Engineer — Installation Guide

Скилл `craft-plus-prompt-engineer` готов к установке. Ниже — инструкции для трёх сценариев.

## Что у тебя есть

| Файл | Назначение |
|---|---|
| `craft-plus-prompt-engineer.skill` | Запакованный .skill (zip) — для импорта через UI |
| `craft-plus-prompt-engineer/` | Распакованная папка — для ручной установки в filesystem |

## Сценарий 1 — Claude Desktop (через UI)

Поддерживается с Claude Desktop 1.x (выпущен 2025-2026). Если ты на Mac/Windows с Claude Desktop:

1. Открой Claude Desktop → Settings → Skills (или Capabilities → Skills в зависимости от версии)
2. Нажми **Install Skill** / **Import Skill**
3. Выбери файл `craft-plus-prompt-engineer.skill`
4. Подтверди установку
5. Перезапусти Claude Desktop, если попросит

После установки скилл доступен **во всех чатах** Claude Desktop. Активация автоматическая — когда пишешь «составь промпт под Claude», «build a prompt for GPT» и т.п.

**Проверка установки:** напиши в любом чате «Сделай промпт под Claude для парсинга CSV на Python». Должен активироваться скилл (не Claude напрямую напишет код, а вернёт CRAFT+ промпт в code-блоке).

## Сценарий 2 — Claude Code (для проектов с кодом)

Если работаешь через Claude Code (CLI):

### Личный скилл (для всех твоих проектов)

```bash
mkdir -p ~/.claude/skills/
cp -r craft-plus-prompt-engineer ~/.claude/skills/
```

Проверка:
```bash
ls ~/.claude/skills/craft-plus-prompt-engineer/
# должно показать: SKILL.md, references/, examples/, scripts/, evals/
```

### Проектный скилл (только для одного репозитория)

```bash
cd /path/to/your/project
mkdir -p .claude/skills/
cp -r /path/to/craft-plus-prompt-engineer .claude/skills/
```

Закоммить в git если хочешь делиться с командой:
```bash
git add .claude/skills/craft-plus-prompt-engineer
git commit -m "Add CRAFT+ prompt engineering skill"
```

## Сценарий 3 — Публикация в публичном репозитории

Если хочешь поделиться скиллом со всеми:

1. Создай новый GitHub-репозиторий, например `claude-skill-craft-plus-prompt-engineer`
2. Залей в корень содержимое папки `craft-plus-prompt-engineer/`:

```bash
cd /path/to/empty/repo
cp -r /path/to/craft-plus-prompt-engineer/* .
git add .
git commit -m "Initial commit — CRAFT+ Prompt Engineer skill v1.0"
git remote add origin https://github.com/yourname/claude-skill-craft-plus-prompt-engineer.git
git push -u origin main
```

3. Создай GitHub Release с прикреплённым `craft-plus-prompt-engineer.skill` файлом — пользователи смогут скачать и импортировать.

4. Опционально опубликуй на платформах для скиллов (зависит от того, что есть в твоей экосистеме на май 2026 — Anthropic Skill Hub, marketplace и т.п.).

## Структура скилла

```
craft-plus-prompt-engineer/
├── SKILL.md                          # Tier 2 entry point (236 строк)
├── references/                       # Tier 3 — загружаются по необходимости
│   ├── methodology.md                # CRAFT+ 10 блоков детально
│   ├── conditional-modules.md        # Модули A/B/C/D с bilingual триггерами
│   ├── target-models.md              # Полировка под 5 моделей
│   ├── question-strategy.md          # Стратегия вопросов с примерами
│   ├── scope-check.md                # Детекция мега-задач
│   ├── security.md                   # Anti-injection правила
│   └── output-format.md              # Markdown шаблоны + JSON schema
├── examples/                         # Tier 3 — загружаются по необходимости
│   ├── ready-prompt-claude.md
│   ├── ready-prompt-gpt.md
│   ├── ready-prompt-ssot.md
│   ├── clarification.md
│   ├── improve-mode.md
│   └── injection-attempt.md
├── scripts/
│   ├── validate.py                   # Программный валидатор (18 чеков)
│   └── README.md
└── evals/
    └── evals.json                    # 10 тест-кейсов для регрессии
```

## Использование скилла

После установки достаточно сформулировать запрос с одной из триггер-фраз:

**Русский:**
- «Составь промпт под Claude для ...»
- «Собери промпт под GPT, чтобы ...»
- «Напиши мне промпт для ...»
- «Улучши этот промпт: ...»
- «Сделай промпт под Gemini для ...»

**Английский:**
- "Build a prompt for Claude that ..."
- "Compose a GPT prompt for ..."
- "Create a prompt to ..."
- "Improve this prompt: ..."
- "Make a prompt for DeepSeek that ..."

Скилл активируется автоматически только на этих явных запросах. Обычные задачи («напиши скрипт на Python») идут к Claude напрямую, без активации.

## Регрессионное тестирование

Запустить тестовые кейсы:

```bash
# Через skill-creator (если установлен)
claude skills test craft-plus-prompt-engineer

# Или вручную: открой evals/evals.json, прогони каждый prompt через
# Claude-with-skill, сравни с expected_output
```

Запустить валидатор на готовом промпте:

```bash
cd craft-plus-prompt-engineer
python scripts/validate.py path/to/generated-prompt.txt --target claude
```

## Обновление скилла

Когда выйдет новая версия:

1. Замени содержимое папки в `~/.claude/skills/craft-plus-prompt-engineer/`
2. Перезапусти Claude Desktop (если установлено через UI — переимпортируй .skill)
3. Frontmatter (`name`, `description`) можно править без переустановки — Claude перечитывает при следующем запуске

## Troubleshooting

**Скилл не активируется на ожидаемом запросе:**
- Проверь триггер-фразу — она должна быть из списка в YAML description
- Узкие триггеры — это by design (избегаем false positives на обычных задачах)
- Если триггер должен быть, но не сработал — можно явно сказать «используй скилл craft-plus-prompt-engineer для этой задачи»

**Скилл активируется на ненужных задачах:**
- Сообщи в issue с примером входа — скорректируем триггер-листы в description

**Промпт получился короче 200 слов или длиннее 700:**
- Запусти `scripts/validate.py` — покажет где проблема
- Часто это означает, что скилл недозаполнил какой-то блок (для short) или не отсёк подробности (для long)

**JSON output mode не активируется:**
- Убедись, что в запросе явно есть «output json», «формат json», «--json» или их вариации
- По умолчанию всегда Markdown — это намеренно
