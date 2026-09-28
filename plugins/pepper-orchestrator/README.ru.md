# Pepper Orchestrator

> **Preview (0.1.0).** Ядро этапа 1: режимы `init`, `plan`, `resume`, `owner`, `decide`.
> Форматы и команды могут измениться до 1.0.0.

Портативный Agent Plugin для концепции единого оркестратора (hub-and-spoke): одна сессия
оркестратора планирует работу в нескольких репозиториях, пишет пакеты работ для сессий модулей,
проверяет их результат и хранит всё состояние в версионируемых Markdown-файлах. Merge, деплой,
PROD и запись в БД остаются за владельцем — в виде готовых однострочных команд.

Установка и обновление: [инструкция](../../docs/installation-and-updates.ru.md) ·
[English](../../docs/installation-and-updates.md).

```text
/plugin marketplace add ITSalt/PepperSkills
/plugin install pepper-orchestrator@pepperskills
```

## Использование

Фраза «спланируй X по концепции единого оркестратора» или короткие команды:

| Команда | Что делает |
|---------|------------|
| `/pepper-orchestrator:init <program>` | рабочее пространство `features/<program>/` и `orch.yaml` |
| `/pepper-orchestrator:plan <задача>` | факты → план → пакеты работ → вопросы владельцу |
| `/pepper-orchestrator:resume` | чтение состояния, сверка с реальностью, следующий шаг |
| `/pepper-orchestrator:owner` | очередь владельца с командами; «готово» → сверка и закрытие |
| `/pepper-orchestrator:decide <текст>` | решение D-n / допущение A-n / вопрос Q-n или вопрос владельцу P-n |

Версия 0.1.0 — preview ядра (этап 1). Режимы dispatch, review, verify, release, retro, субагенты-рецензенты
и PreToolUse-хуки появятся в следующих версиях; до тех пор скилл ведёт эти шаги по концепции
инструкциями.

## Когда подходит

Два и более репозитория или роли, работа дольше одной сессии, есть PROD и риск регресса, по ходу
нужны решения владельца. Для одной правки в одном репозитории — лишние накладные расходы.
Подробности и границы применимости — в [концепции](skills/pepper-orchestrator/references/concept.ru.md).

## Состав

| Часть | Где | Переносимость |
| --- | --- | --- |
| Скилл (ядро) | `skills/pepper-orchestrator/` | любой агент, читающий файлы и запускающий Python 3 |
| CLI рабочего пространства | `skills/pepper-orchestrator/scripts/orch.py`, `safe_edit.py` | стандартная библиотека + git |
| Шаблоны (en, ru) | `skills/pepper-orchestrator/templates/` | переносимы |
| Короткие команды | `commands/` | адаптер Claude Code |
| Манифест | `plugin.json` | канонический; клиентские манифесты генерируются |

Клиенты без сообщений между сессиями тоже работают: строки-указатели передаёт владелец, а `resume`
узнаёт о PR через `gh pr list`.

Самопроверка: `python3 skills/pepper-orchestrator/scripts/selftest.py`.
