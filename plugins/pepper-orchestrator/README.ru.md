# Pepper Orchestrator

> **Preview (0.2.1).** Режимы `init`, `plan`, `dispatch`, `resume`, `owner`, `decide`; потоки в одном
> репозитории с worktree и замками.
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
| `/pepper-orchestrator:dispatch <WP>` | проверка пересечений и замков, команда запуска |
| `/pepper-orchestrator:resume` | чтение состояния, сверка с реальностью, следующий шаг |
| `/pepper-orchestrator:owner` | очередь владельца с командами; «готово» → сверка и закрытие |
| `/pepper-orchestrator:decide <текст>` | решение D-n / допущение A-n / вопрос Q-n или вопрос владельцу P-n |

Версия 0.2.0 — preview (этап 2a). Модуль — весь репозиторий либо раздел или домен одного
репозитория: каждый поток работает в своём worktree (`claude -w`), общие пути и ресурсы держатся
замками, слияния в один репозиторий идут очередью. Режимы review, verify, release, retro,
субагенты-рецензенты и PreToolUse-хуки появятся в следующих версиях; до тех пор скилл ведёт эти шаги
по концепции инструкциями.

## Облачные сессии

Облачные сессии (claude.ai/code) не ставят плагины из проектных настроек, а писать в `.claude/`
облачной сессии нельзя. Скилл им даёт **setup-скрипт** облачного окружения: он выполняется до старта
Claude, записанные им файлы остаются в окружении:

```bash
# pepper-orchestrator skill (PepperSkills); change this comment to refresh the cached environment
pepper_dir="$HOME/.cache/pepperskills"
if [ -d "$pepper_dir/.git" ]; then
  git -C "$pepper_dir" pull --ff-only -q
else
  git clone -q --depth 1 https://github.com/ITSalt/PepperSkills "$pepper_dir"
fi
bash "$pepper_dir/scripts/install-skill.sh" pepper-orchestrator
```

`install-skill.sh` идемпотентен: копирует `plugins/<name>/skills/<name>` в
`~/.claude/skills/<name>` (или в `--dest`) и печатает версию. После первого запуска окружение
кэшируется, поэтому скилл обновится при изменении setup-скрипта или истечении кэша.

Команд плагина в облаке нет: вызывайте `/pepper-orchestrator <режим> <аргументы>` (например,
`/pepper-orchestrator resume`) или фразой. Облачная программа держит рабочее пространство в самом
репозитории на ветке `orch/<program>` (`init --in-repo`), сессии модулей — облачные, их запускают по
промпту из `dispatch`, готовность находится по веткам и PR.

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
