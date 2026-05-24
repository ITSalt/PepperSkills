# PepperSkills

Библиотека портативных скиллов для prompt engineering. Каждый скилл
поставляется параллельно в двух экосистемах — **Anthropic (Claude)** и
**OpenAI (GPT)** — чтобы форматы можно было сравнивать и адаптировать.

## Скиллы

| Скилл | Описание | Папка |
|-------|----------|-------|
| [`itsalt:creative-mode`](./itsalt-creative-mode/) | Честное сэмплирование из распределения и разнообразная генерация через self-seeded randomness. | [`itsalt-creative-mode/`](./itsalt-creative-mode/) |

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
