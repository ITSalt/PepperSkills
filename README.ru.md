# PepperSkills

Библиотека портативных скиллов для prompt engineering. Каждый скилл
поставляется параллельно в двух экосистемах — **Anthropic (Claude)** и
**OpenAI (GPT)** — чтобы форматы можно было сравнивать и адаптировать.

## Скиллы

| Скилл | Описание | Папка |
|-------|----------|-------|
| [`pepper-creative-mode`](./pepper-creative-mode/) | Честное сэмплирование из распределения и разнообразная генерация через self-seeded randomness. | [`pepper-creative-mode/`](./pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./pepper-prompt-engineer/) | CRAFT+ промпт-инженер: превращает описания задач в production-ready промпты под целевую модель. | [`pepper-prompt-engineer/`](./pepper-prompt-engineer/) |

## Установка

- **Claude Desktop / claude.ai** — скачай нужный `.skill`-архив из
  [последнего релиза](https://github.com/ITSalt/PepperSkills/releases/latest)
  и загрузи через *Settings → Capabilities → Skills → Upload*.
- **Claude Code** — скопируй распакованную папку `<skill>/anthropic/`
  (переименованную под `name:` из `SKILL.md`) в `~/.claude/skills/`
  (личный скилл) или `<project>/.claude/skills/` (проектный). Подробности —
  в `anthropic/INSTALL.md` соответствующего скилла.
- **OpenAI / ChatGPT / GPT API** — содержимое `openai/system-prompt.md`
  (полная версия) или `openai/custom-instructions.md` (компактная, <1500
  символов) копируется в соответствующее поле.

Собрать `.skill`-архивы из исходников: `scripts/build-skills.sh`.

## Структура

Каждая группа скиллов — самодостаточная папка:

```
<skill-group>/
├── README.md         # описание скилла (English)
├── README.ru.md      # описание скилла (Русский)
├── anthropic/        # вариант для Claude — Anthropic Skill spec
│   ├── SKILL.md      #   YAML frontmatter + тело
│   ├── examples/
│   └── references/
└── openai/           # вариант для GPT — OpenAI prompt format
    ├── system-prompt.md         # полный промпт для API / Custom GPT
    └── custom-instructions.md   # компактная версия для ChatGPT Custom Instructions
```

## Версии документации

- English — [`README.md`](./README.md)
- Русский — этот файл

## Контрибьюция

См. [`CONTRIBUTING.md`](./CONTRIBUTING.md). Сообщения о безопасности — [`SECURITY.md`](./SECURITY.md).
Кодекс поведения — [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

## Лицензия

[MIT](./LICENSE) © ITSalt.
