# PepperSkills

Библиотека портативных скиллов и устанавливаемых Agent Plugins. Каждый плагин
можно поставить отдельно из marketplace или подключить из клона репозитория.

## Скиллы

| Скилл | Описание | Папка |
|-------|----------|-------|
| [`pepper-creative-mode`](./plugins/pepper-creative-mode/) | Честное сэмплирование из распределения и разнообразная генерация через self-seeded randomness. | [`plugins/pepper-creative-mode/`](./plugins/pepper-creative-mode/) |
| [`pepper-prompt-engineer`](./plugins/pepper-prompt-engineer/) | CRAFT+ промпт-инженер: превращает описания задач в production-ready промпты под целевую модель. | [`plugins/pepper-prompt-engineer/`](./plugins/pepper-prompt-engineer/) |
| [`pepper-ru-web-compliance`](./plugins/pepper-ru-web-compliance/) | Проверка сайта на соответствие требованиям РФ: записка для юриста и план правок для разработчика. | [`plugins/pepper-ru-web-compliance/`](./plugins/pepper-ru-web-compliance/) |

## Релизы

| Продукт | Версия |
| --- | --- |
| `pepper-creative-mode` | [2.0.1](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-creative-mode-v2.0.1) |
| `pepper-prompt-engineer` | [2.5.1](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-prompt-engineer-v2.5.1) |
| `pepper-ru-web-compliance` | [2.1.0](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-ru-web-compliance-v2.1.0) |

В каждом релизе: ZIP скилла, ZIP плагина и SHA256SUMS. В Claude web проверены импорт и обновление предыдущих переходных версий; новые пакеты требуют отдельной клиентской приёмки.

Подробнее: [выпуск по замечаниям](./docs/releases/2026-09-26-feedback.md) и [предыдущий переходный выпуск](./docs/releases/2026-09-26-transition.md).

## Установка

Все способы установки, команды, таблица совместимости и общая папка скиллов
описаны в [инструкции по установке](./docs/installation-and-updates.ru.md).

| Поверхность | Способ |
| --- | --- |
| Codex, Claude Code | Marketplace или отдельный каталог скиллов |
| Claude Chat и Cowork | ZIP скилла; проверена загрузка предыдущего выпуска |
| Cursor | Cursor marketplace или поддерживаемый локальный плагин |
| API и другие поля промптов | Сгенерированный чат-адаптер |

Для владельцев симлинков на старые `anthropic/` и `openai/` в инструкции есть
[карта перехода](./docs/installation-and-updates.ru.md#переход-со-старых-путей-pepperskills).
Решение и этапы миграции — в [отчёте](./docs/history/repository-structure-2026-09-26.ru.md).

## Пути на переходном этапе

| Старый путь | Канонический путь |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `pepper-prompt-engineer/chat-prompt.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md` |
| `pepper-prompt-engineer/chat-prompt.template.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.template.md` |
| `<name>/anthropic/INSTALL.md` | `docs/installation-and-updates.md`, `docs/installation-and-updates.ru.md` |

Корневые `.skill` — прежние зафиксированные сборки из ревизии репозитория
`v1.4.1-1-g4128fe6` (commit `4128fe6`). Они не пересобираются и не соответствуют
текущим версиям плагинов; новые архивы собираются в `dist/<name>/<version>/`.

## Версии документации

- English — [`README.md`](./README.md)
- Русский — этот файл

## Контрибьюция

См. [`CONTRIBUTING.md`](./CONTRIBUTING.md). Сообщения о безопасности — [`SECURITY.md`](./SECURITY.md).
Кодекс поведения — [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

Результат перехода этапа A: [отчёт по структуре](./docs/history/repository-structure-2026-09-26.ru.md).
Исходное предложение сохранено в [`docs/history/`](./docs/history/).

## Лицензия

[MIT](./LICENSE) © ITSalt.
