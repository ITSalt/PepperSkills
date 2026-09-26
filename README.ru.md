# PepperSkills

Библиотека портативных скиллов и устанавливаемых Agent Plugins. Каждый плагин
можно поставить отдельно из marketplace или подключить из клона репозитория.

## Скиллы

| Скилл | Описание | Папка |
|-------|----------|-------|
| [`pepper-creative-mode`](./plugins/pepper-creative-mode/) | Честное сэмплирование из распределения и разнообразная генерация через self-seeded randomness. | [`plugins/pepper-creative-mode/`](./plugins/pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./plugins/pepper-prompt-engineer/) | CRAFT+ промпт-инженер: превращает описания задач в production-ready промпты под целевую модель. | [`plugins/pepper-prompt-engineer/`](./plugins/pepper-prompt-engineer/) |
| [`pepper-ru-web-compliance`](./plugins/pepper-ru-web-compliance/) | Проверка сайта на соответствие требованиям РФ: записка для юриста и план правок для разработчика. | [`plugins/pepper-ru-web-compliance/`](./plugins/pepper-ru-web-compliance/) |

## Установка

- **Плагин** — используй marketplace соответствующего клиента и пакет из
  `plugins/`. Локальный marketplace и публичный каталог — разные каналы.
- **Общая папка + симлинки** — подключи `plugins/<name>/skills/<name>` к
  `~/.agents/skills/<name>`. Для Claude Code добавь ссылку из
  `~/.claude/skills/<name>`; для других клиентов проверь поддерживаемый путь.
- **Проект, менеджер skills, ZIP или чат** — выбери способ по
  [инструкции установки](./docs/installation-and-updates.ru.md).
- **OpenAI review** — собери `scripts/build-plugins.sh pepper-ru-web-compliance`
  и загрузи получившийся архив в портал Skills only.

Собрать `.skill`-архивы для совместимой загрузки: `scripts/build-skills.sh`.
Собрать переносимые плагины: `scripts/build-plugins.sh`.

## Структура

Каждая группа скиллов — самодостаточная папка:

```
plugins/<name>/
├── README.md         # описание скилла (English)
├── README.ru.md      # описание скилла (Русский)
├── plugin.json       # переносимый Agent Plugins manifest
├── skills/<name>/    # единый источник SKILL.md, scripts и references
└── adapters/chat/    # сгенерированные инструкции для чатов без исполнения кода
```

## Версии документации

- English — [`README.md`](./README.md)
- Русский — этот файл

## Контрибьюция

См. [`CONTRIBUTING.md`](./CONTRIBUTING.md). Сообщения о безопасности — [`SECURITY.md`](./SECURITY.md).
Кодекс поведения — [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

Полный цикл установки и обновления: [`docs/installation-and-updates.ru.md`](./docs/installation-and-updates.ru.md).

Проект новой структуры и карта переноса: [`docs/repository-structure.ru.md`](./docs/repository-structure.ru.md).
Это предложение; приведённые выше текущие пути пока сохраняются.

## Лицензия

[MIT](./LICENSE) © ITSalt.
