# `pepper-creative-mode` — Installation Guide

Скилл `pepper-creative-mode` поставляется в двух форматах. Какой брать —
зависит от того, где ты его запускаешь.

## Что у тебя есть

| Артефакт | Где лежит | Для чего |
|---|---|---|
| `pepper-creative-mode.skill` | `../pepper-creative-mode.skill` (рядом с `anthropic/`) | ZIP-архив для Claude Desktop и claude.ai (web). Внутри одна корневая папка `pepper-creative-mode/` со всей структурой скилла. |
| `pepper-creative-mode/` (распакованная папка) | Эта папка — `pepper-creative-mode/anthropic/` и всё, что в ней | Для Claude Code: копируется целиком в `~/.claude/skills/` либо в `<project>/.claude/skills/`. |

Anthropic Skills spec (май 2026) требует, чтобы относительные пути из
`SKILL.md` к `references/…` и `examples/…` всегда резолвились. Поэтому
**«закинуть один SKILL.md без окружающих папок» — не работает**: в обоих
официальных сценариях нужна либо полная папка, либо ZIP с такой же папкой
внутри. `SKILL.md` ссылается на 4 файла в `references/` (Sum-Mod,
Rolling Hash, Decision Cascade, when-not-to-use) и 4 в `examples/`
(fair-coin, biased-decision, creative-generation, mixed-strategy) —
без них скилл деградирует на нетривиальных задачах.

## Сценарий 1 — Claude Desktop / claude.ai (через UI)

Источник: <https://support.claude.com/en/articles/12512180-use-skills-in-claude>.
Оба интерфейса принимают **только ZIP-архив**, загружаемый через настройки.

1. Открой **Settings → Capabilities → Skills**.
2. Нажми **«+» → «Create skill» → «Upload a skill»**.
3. Выбери файл `pepper-creative-mode.skill` из этого репозитория.
4. Подтверди установку. После загрузки скилл будет виден в боковой
   панели как `pepper-creative-mode` со всем содержимым:
   `SKILL.md`, `references/`, `examples/`, `INSTALL.md`.

После установки скилл доступен **во всех чатах**. Активация — автоматическая
по триггер-фразам из YAML `description`.

**Проверка установки.** В новом чате напиши: «Подбрось честную монетку».
Скилл должен активироваться — ответ придёт в виде явного шага со строкой
seed-а и арифметикой `sum mod 2`, а не как односложное «heads».

## Сценарий 2 — Claude Code (распакованная папка)

Источник: <https://code.claude.com/docs/en/skills>. Claude Code работает с
файловой системой и берёт скиллы напрямую из каталога — никаких архивов.

### Личный скилл (для всех твоих проектов)

```bash
mkdir -p ~/.claude/skills/
cp -r pepper-creative-mode ~/.claude/skills/
ls ~/.claude/skills/pepper-creative-mode/
# должно показать: SKILL.md, INSTALL.md, references/, examples/
```

Папку для копирования бери из распакованного `.skill` или просто из
`anthropic/` этого репозитория (она структурно совпадает с содержимым
архива — `SKILL.md` лежит в корне, рядом `references/` и `examples/`).
Если копируешь из `anthropic/`, переименуй полученную папку в
`pepper-creative-mode/`, чтобы её имя совпало с полем `name:` в `SKILL.md`
(Claude Code ожидает совпадения).

### Проектный скилл (только для одного репозитория)

```bash
cd /path/to/your/project
mkdir -p .claude/skills/
cp -r /path/to/pepper-creative-mode .claude/skills/
```

Если хочешь делиться с командой через git:

```bash
git add .claude/skills/pepper-creative-mode
git commit -m "Add pepper-creative-mode skill"
```

## Сценарий 3 — Публикация форка / своего GitHub-репозитория

1. Создай GitHub-репозиторий, например `claude-skill-pepper-creative-mode`.
2. Залей содержимое распакованной папки `pepper-creative-mode/` в корень:

```bash
cd /path/to/empty/repo
cp -r /path/to/pepper-creative-mode/* .
git add .
git commit -m "Initial commit — pepper-creative-mode v1.0"
git remote add origin https://github.com/yourname/claude-skill-pepper-creative-mode.git
git push -u origin main
```

3. Создай GitHub Release и прикрепи `pepper-creative-mode.skill` —
   пользователи Claude Desktop смогут скачать и импортировать ZIP одним
   движением.

## Структура скилла

```
pepper-creative-mode/
├── SKILL.md                          # Tier 2 entry point
├── INSTALL.md                        # этот файл
├── references/                       # Tier 3 — подгружаются по необходимости
│   ├── sum-mod.md                    # Sum-Mod: формула, worked example, edge cases
│   ├── rolling-hash.md               # Rolling Hash: формула, interval splitting
│   ├── decision-cascade.md           # Decision Cascade: decomposition procedure
│   └── when-not-to-use.md            # Hard/soft exclusions, QwQ-32B аномалия
└── examples/                         # Tier 3 — подгружаются по необходимости
    ├── fair-coin.md                  # Sum-Mod, 50/50 coin flip
    ├── biased-decision.md            # Rolling Hash, 30/70 биас
    ├── creative-generation.md        # Decision Cascade, три прогона одного промпта
    └── mixed-strategy.md             # Sum-Mod N=3, Rock-Paper-Scissors
```

## Использование скилла

После установки достаточно написать запрос с одной из триггер-фраз из
`SKILL.md` (поле `description`).

**Русский:**
- «Подбрось монетку» / «Кинь кубик»
- «Выбери случайно из …»
- «Сгенерируй 5 разных вариантов …»
- «Придумай заголовок» (с просьбой разнообразия)
- «Удиви меня»

**Английский:**
- "Flip a coin" / "Roll a die"
- "Pick randomly from …"
- "Write 5 different …" / "Generate variants of …"
- "Brainstorm …"
- "Surprise me"

Скилл активируется **только** по этим триггерам. Задачи с единственным
правильным ответом (математика, классификация, перевод, дебаг кода)
идут к модели напрямую — это намеренно, чтобы не вносить шум туда, где
он вредит точности. См. `references/when-not-to-use.md`.

## Обновление скилла

| Куда установлено | Как обновить |
|---|---|
| Claude Desktop / claude.ai (ZIP через UI) | В UI удали старый `pepper-creative-mode` и загрузи новый `.skill`. Anthropic не предоставляет «in-place» обновления для пользовательских скиллов. |
| Claude Code (`~/.claude/skills/pepper-creative-mode/`) | `rm -rf ~/.claude/skills/pepper-creative-mode && cp -r pepper-creative-mode ~/.claude/skills/`. Метаданные (`name`, `description`) подхватываются при следующем запуске Claude Code. |

## Troubleshooting

**Скилл не активируется на ожидаемом запросе.**
Проверь, что триггер-фраза реально из списка в YAML `description` —
триггеры намеренно узкие, чтобы не активироваться на обычных задачах.
Если триггер должен был сработать, но не сработал, скажи явно: «используй
скилл `pepper-creative-mode` для этой задачи».

**Скилл активируется на ненужных задачах (математика, факт-чек, дебаг).**
Это false-positive — открой issue с примером входа. Базовое правило в
`description` запрещает применение на single-answer задачах, но если
формулировка вводит модель в заблуждение, его нужно укрепить.

**Модель «подбрасывает монетку», но не показывает seed-строку.**
Значит, скилл не активировался либо активировался частично (только YAML
без `SKILL.md` body). Скорее всего, в Desktop был загружен битый архив
(например, в нём оказался один `SKILL.md` без `references/` и
`examples/`). Решение: пересобери `.skill` так, чтобы в корне ZIP лежала
ровно одна папка `pepper-creative-mode/`, и в ней `SKILL.md` плюс
`references/` и `examples/`. См. также раздел про требования спеки в
шапке этого файла.

**Распределение всё равно смещено (например, 70/30 вместо 50/50).**
Это ожидаемо на маленьких моделях, которые плохо считают модуль
автономно. Эффективность техники растёт с размером модели и резко
улучшается на reasoning-моделях (DeepSeek-R1 ≈ true PRNG). На GPT-4o /
Claude Haiku ожидай улучшение, но не идеал.

**Имя `name:` в `SKILL.md` содержит двоеточие или пробел.**
Anthropic спека (май 2026) разрешает в `name:` только `[a-z0-9-]`, до 64
символов, и запрещает зарезервированные слова `anthropic`, `claude`.
Любое другое имя будет либо отвергнуто, либо «приклеено» в UI (Claude
Desktop молча удаляет двоеточия — поэтому, например, старое имя
`itsalt:creative-mode` отображалось как `itsaltcreative-mode`).
