# `pepper-prompt-engineer` — Installation Guide

Скилл `pepper-prompt-engineer` поставляется в двух форматах. Какой брать —
зависит от того, где ты его запускаешь.

## Что у тебя есть

| Артефакт | Где лежит | Для чего |
|---|---|---|
| `pepper-prompt-engineer.skill` | `../pepper-prompt-engineer.skill` (рядом с `anthropic/`) | ZIP-архив для Claude Desktop и claude.ai (web). Внутри одна корневая папка `pepper-prompt-engineer/` со всей структурой скилла. |
| `pepper-prompt-engineer/` (распакованная папка) | Эта папка — `pepper-prompt-engineer/anthropic/` и всё, что в ней | Для Claude Code: копируется целиком в `~/.claude/skills/` либо в `<project>/.claude/skills/`. |

Anthropic Skills spec (май 2026) требует, чтобы относительные пути из
`SKILL.md` к `references/…`, `examples/…`, `scripts/…` всегда резолвились.
Поэтому **«закинуть один SKILL.md без окружающих папок» — не работает**:
в обоих официальных сценариях нужна либо полная папка, либо ZIP с такой
же папкой внутри. Подробности в разделе «Troubleshooting».

## Сценарий 1 — Claude Desktop / claude.ai (через UI)

Источник: <https://support.claude.com/en/articles/12512180-use-skills-in-claude>.
Оба интерфейса принимают **только ZIP-архив**, загружаемый через настройки.

1. Открой **Settings → Capabilities → Skills**.
2. Нажми **«+» → «Create skill» → «Upload a skill»**.
3. Выбери файл `pepper-prompt-engineer.skill` из этого репозитория.
4. Подтверди установку. После загрузки скилл будет виден в боковой
   панели как `pepper-prompt-engineer` со всем содержимым:
   `SKILL.md`, `references/`, `examples/`, `scripts/`, `evals/`,
   `INSTALL.md`.

После установки скилл доступен **во всех чатах**. Активация — автоматическая
по триггер-фразам из YAML `description`.

**Проверка установки.** В новом чате напиши:
«Сделай промпт под Claude для парсинга CSV на Python». Скилл должен
активироваться — ответ придёт в виде CRAFT+ промпта в code-блоке, а не как
прямое решение задачи.

## Сценарий 2 — Claude Code (распакованная папка)

Источник: <https://code.claude.com/docs/en/skills>. Claude Code работает с
файловой системой и берёт скиллы напрямую из каталога — никаких архивов.

### Личный скилл (для всех твоих проектов)

```bash
mkdir -p ~/.claude/skills/
cp -r pepper-prompt-engineer ~/.claude/skills/
ls ~/.claude/skills/pepper-prompt-engineer/
# должно показать: SKILL.md, INSTALL.md, references/, examples/, scripts/, evals/
```

Папку для копирования бери из распакованного `.skill` или просто из
`anthropic/` этого репозитория (она структурно совпадает с содержимым
архива — `SKILL.md` лежит в корне, рядом `references/`, `examples/`,
`scripts/`, `evals/`). Если копируешь из `anthropic/`, переименуй
полученную папку в `pepper-prompt-engineer/`, чтобы её имя совпало с
полем `name:` в `SKILL.md` (Claude Code ожидает совпадения).

### Проектный скилл (только для одного репозитория)

```bash
cd /path/to/your/project
mkdir -p .claude/skills/
cp -r /path/to/pepper-prompt-engineer .claude/skills/
```

Если хочешь делиться с командой через git:

```bash
git add .claude/skills/pepper-prompt-engineer
git commit -m "Add pepper-prompt-engineer skill"
```

## Сценарий 3 — Публикация форка / своего GitHub-репозитория

1. Создай GitHub-репозиторий, например `claude-skill-pepper-prompt-engineer`.
2. Залей содержимое распакованной папки `pepper-prompt-engineer/` в корень:

```bash
cd /path/to/empty/repo
cp -r /path/to/pepper-prompt-engineer/* .
git add .
git commit -m "Initial commit — pepper-prompt-engineer v1.0"
git remote add origin https://github.com/yourname/claude-skill-pepper-prompt-engineer.git
git push -u origin main
```

3. Создай GitHub Release и прикрепи `pepper-prompt-engineer.skill` —
   пользователи Claude Desktop смогут скачать и импортировать ZIP одним
   движением.

## Структура скилла

```
pepper-prompt-engineer/
├── SKILL.md                          # Tier 2 entry point (~236 строк)
├── INSTALL.md                        # этот файл
├── references/                       # Tier 3 — подгружаются по необходимости
│   ├── methodology.md                # CRAFT+ 10 блоков детально
│   ├── conditional-modules.md        # Модули A/B/C/D с bilingual триггерами
│   ├── target-models.md              # Полировка под 5 моделей
│   ├── question-strategy.md          # Стратегия вопросов с примерами
│   ├── scope-check.md                # Детекция мега-задач
│   ├── security.md                   # Anti-injection правила
│   └── output-format.md              # Markdown шаблоны + JSON schema
├── examples/                         # Tier 3 — подгружаются по необходимости
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

После установки достаточно написать запрос с одной из триггер-фраз из
`SKILL.md` (поле `description`).

**Русский:**
- «Составь промпт под Claude для …»
- «Собери промпт под GPT, чтобы …»
- «Напиши мне промпт для …»
- «Улучши этот промпт: …»

**Английский:**
- "Build a prompt for Claude that …"
- "Compose a GPT prompt for …"
- "Create a prompt to …"
- "Improve this prompt: …"

Скилл активируется **только** по этим триггерам. Обычные задачи («напиши
скрипт на Python») идут к модели напрямую без активации скилла — это
сделано намеренно, чтобы избежать false-positive активаций.

## Регрессионное тестирование

Прогон тестовых кейсов из `evals/evals.json`:

```bash
# Если установлен skill-creator:
claude skills test pepper-prompt-engineer

# Иначе вручную: открой evals/evals.json, прогони каждый prompt
# через Claude-with-skill, сравни с expected_output.
```

Программный валидатор на готовом промпте:

```bash
cd ~/.claude/skills/pepper-prompt-engineer   # или путь к распакованной папке
python scripts/validate.py path/to/generated-prompt.txt --target claude
```

## Обновление скилла

| Куда установлено | Как обновить |
|---|---|
| Claude Desktop / claude.ai (ZIP через UI) | В UI удали старый `pepper-prompt-engineer` и загрузи новый `.skill`. Anthropic не предоставляет «in-place» обновления для пользовательских скиллов. |
| Claude Code (`~/.claude/skills/pepper-prompt-engineer/`) | `rm -rf ~/.claude/skills/pepper-prompt-engineer && cp -r pepper-prompt-engineer ~/.claude/skills/`. Метаданные (`name`, `description`) подхватываются при следующем запуске Claude Code. |

## Troubleshooting

**Скилл не активируется на ожидаемом запросе.**
Проверь, что триггер-фраза реально из списка в YAML `description` —
триггеры намеренно узкие, чтобы не активироваться на обычных задачах. Если
триггер должен был сработать, но не сработал, скажи явно: «используй скилл
pepper-prompt-engineer для этой задачи».

**Скилл активируется на ненужных задачах.**
Открой issue с примером входа — скорректируем триггер-листы в
`description`.

**Промпт получился короче 200 слов или длиннее 700.**
Запусти `scripts/validate.py` — он покажет, в каком блоке проблема. Чаще
всего это значит, что скилл недозаполнил один из CRAFT+ блоков (для
short) или не отсёк подробности (для long).

**JSON output mode не активируется.**
В запросе должно быть явное `output json` / `формат json` / `--json` или их
вариация. По умолчанию вывод — Markdown, это намеренно.

**В Claude Desktop вижу название без структуры (только `SKILL.md`).**
Это значит, что был загружен битый архив (например, в нём оказался один
`SKILL.md` без папки) или развернутая папка из `anthropic/` без
переименования. Решение: пересобери `.skill` так, чтобы в корне ZIP лежала
ровно одна папка `pepper-prompt-engineer/`, и в ней `SKILL.md` плюс все
поддиректории (`references/`, `examples/`, `scripts/`, `evals/`).
Источник требования —
<https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices>
(раздел «Skill structure»).

**Имя `name:` в `SKILL.md` содержит двоеточие или пробел.**
Anthropic спека (май 2026) разрешает в `name:` только `[a-z0-9-]`, до 64
символов, и запрещает зарезервированные слова `anthropic`, `claude`. Любое
другое имя будет либо отвергнуто, либо «приклеено» в UI (Claude Desktop
молча удаляет двоеточия — поэтому, например, старое имя
`itsalt:creative-mode` отображалось как `itsaltcreative-mode`).
