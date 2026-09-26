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

Все способы установки, команды, таблица совместимости и общая папка скиллов
описаны в [инструкции по установке](./docs/installation-and-updates.ru.md).

| Поверхность | Способ |
| --- | --- |
| Codex, Claude Code | Marketplace или отдельный каталог скиллов |
| Claude Chat и Cowork | ZIP-загрузка скилла после приёмки клиента |
| Cursor | Cursor marketplace или поддерживаемый локальный плагин |
| API и другие поля промптов | Сгенерированный чат-адаптер |

Для владельцев симлинков на старые `anthropic/` и `openai/` в инструкции есть
[карта перехода](./docs/installation-and-updates.ru.md#переход-со-старых-путей).
Решение и этапы миграции — в [отчёте](./docs/history/repository-structure-2026-09-26.ru.md).

## Версии документации

- English — [`README.md`](./README.md)
- Русский — этот файл

## Контрибьюция

См. [`CONTRIBUTING.md`](./CONTRIBUTING.md). Сообщения о безопасности — [`SECURITY.md`](./SECURITY.md).
Кодекс поведения — [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).

Полный цикл установки и обновления: [`docs/installation-and-updates.ru.md`](./docs/installation-and-updates.ru.md).

Результат перехода этапа A: [отчёт по структуре](./docs/history/repository-structure-2026-09-26.ru.md).
Исходное предложение сохранено в [`docs/history/`](./docs/history/).

## Лицензия

[MIT](./LICENSE) © ITSalt.
