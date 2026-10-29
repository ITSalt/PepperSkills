# Передача контекста: автономность Pepper Orchestrator для Codex

Дата: 29 октября 2026 года. Репозиторий: `ITSalt/PepperSkills`.
Рабочая ветка: `codex/orchestrator-trusted-delivery`. Версия: **0.13.0, unreleased candidate**.

## Текущий результат

Codex-часть плана реализована и проверена. Исходный
[план автономности](2026-10-29-orchestrator-autonomy.ru.md) предусматривал оба клиента,
но актуальное поручение пользователя в этой сессии ограничено **Codex CLI**.
Claude autonomy не реализовывалась и не должна автоматически считаться следующим поручением.
Общее ядро и совместимость существующих Claude-команд сохранены.

Реализованы реестр сессий v2, подключение и подтверждение старых сессий,
поколения координатора, атомарное резервирование сессии/слота/блокировок,
`next --json`, структурированный dispatch, reuse после подтверждённого merge,
назначения с постоянным ID и подтверждением STARTED, локальный наблюдатель,
объединение/consume сигналов, пауза, восстановление и компактизация.

Каноническое ядро находится в
`plugins/pepper-orchestrator/skills/pepper-orchestrator/scripts/`:
`autonomy.py` отвечает за новый протокол, `runtime_commands.py` и `orch.py` подключают CLI,
`codex_transport.py` работает с queue и App Server, `codex_adapter.py` готовит запуск/окружение.
Редактируемую копию runtime внутри Codex entrypoint создавать нельзя: ресурсы копирует сборщик.

## Что прочитать прежде всего

1. [Итоговый отчёт 0.13.0](../validation/pepper-orchestrator-0.13.0.md): проверки, реальные
   сценарии, ссылки на CI/PR, хеши и границы доказанного.
2. [Протокол автономности](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/autonomy.md):
   команды, подтверждения, запуск, восстановление и ограничения.
3. [Codex workflow](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/codex.md).

## Проверенное состояние

- 24 новых autonomy-регрессии PASS; существующие runtime/reliability/selftest также PASS.
- Полный `scripts/check.sh` прошёл в неизменяемой локальной Git-копии. Извлечённые
  skill/plugin ZIP и Codex-копия внутри plugin ZIP проверены отдельно.
- [Финальная CI](https://github.com/ITSalt/pepper-orchestrator-autonomy-validation-20261029-90334b/actions/runs/40902670870):
  все 7 jobs PASS. Есть Linux/macOS/Windows-регрессии и нативный Windows/PowerShell/Codex smoke.
  Снимок runtime: `fda68b2c2bc4e5a9e05fc8859f29add621d51015` в приватном тестовом репозитории.
- На macOS/Codex CLI 0.154.0 прошёл живой цикл из итогового Codex ZIP: два независимых
  пакета, затем следующий пакет в той же A-сессии после merge, без пользовательского dispatch.
  Проверена компактизация. Результаты Windows/Linux smoke не означают живой E2E reuse на них.
- Тестовые серверы/наблюдатели остановлены, тестовые сессии и приватные тестовые репозитории
  архивированы. Постоянный сервис, расписания Codex App и пользовательские программы не настраивались.

Поздние изменения внешнего live-harness исправили ожидание после исторического failed-хода
и проверены повторным успешным запуском. Пакуемый runtime после указанного CI-снимка не менялся.

## Восстановление окружения на другой машине

```bash
git fetch origin
git switch codex/orchestrator-trusted-delivery
git pull --ff-only
git status --short --branch
```

При отсутствии локальной ветки использовать
`git switch --track origin/codex/orchestrator-trusted-delivery`.
Не сбрасывать посторонние изменения и не считать исторические SHA вечной базой.

ZIP в `dist/` и временное окружение проверок не коммитятся. На macOS/Linux восстановить их:

```bash
python3 -m venv /tmp/pepper-orchestrator-check
/tmp/pepper-orchestrator-check/bin/python -m pip install -r scripts/requirements-build.txt
PYTHON=/tmp/pepper-orchestrator-check/bin/python bash scripts/check.sh
```

Полный check собирает `dist/pepper-orchestrator/0.13.0/`; ожидаемые SHA256 приведены в отчёте.
Для быстрой проверки нового ядра:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 plugins/pepper-orchestrator/skills/pepper-orchestrator/scripts/autonomy_selftest.py
```

`scripts/test-orchestrator-autonomy-live.py` — отдельная явная платная/сетевая приёмка:
она создаёт приватный одноразовый GitHub-репозиторий и реальные модельные сессии.
Обычные offline-checks её не запускают. Не повторять без необходимости: результаты уже сохранены.

## Правила продолжения и оставшиеся границы

- Сначала прочитать новый запрос пользователя. Сам этот handoff не поручает релиз, merge,
  публикацию, развёртывание или включение автономности в существующей программе.
- Автономность выключена до явного enable; defaults: reuse auto, два модульных слота,
  600 секунд до повторной проверки действия. Новые терминалы запускает владелец.
- Привязки PID/процесса, thread ID, локальные сокеты и подтверждения не переносятся между
  машинами. Подключение требует актуального подтверждения на новом хосте; multi-host исключён.
- Наблюдение и queue должны обращаться к тому же серверу, который владеет живой сессией.
  Не создавать второго исполнителя/координатора и не ослаблять sandbox/approvals ради доступности RPC.
- Unknown delivery удерживает резервирование. Сначала сверять получателя и Git, не дублировать TASK
  и не выдавать ручную передачу. ACCEPTED не разрешает reuse до подтверждённого merge.
- Native `.codex` не переписывается модулем при reuse. При неизвестном исходе setup нужна сверка;
  изменения native config в новой базе требуют подготовки/подтверждения владельцем.
- Публичного релиза 0.13.0 нет. Пользовательский PROD, реальные миграции, интерактивные approvals,
  живой E2E Windows/Linux, Claude autonomy, #23, ранний reuse после ACCEPTED и смешанные клиенты
  не принимались как завершённые. Состояние issues перед их изменением нужно проверить заново.
