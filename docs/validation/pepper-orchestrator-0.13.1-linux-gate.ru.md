# Codex Linux acceptance gate — 30 октября 2026

[English canonical report](pepper-orchestrator-0.13.1-linux-gate.md).

Продолжение: [новый private STDIO вариант](../adr/2026-10-30-codex-private-stdio-tools.md)
имеет [частичные живые Linux evidence](pepper-orchestrator-private-stdio-linux-2026-10-30.ru.md):
RPC/FD INCONCLUSIVE, Git preparation BLOCKED. Security/E2E gate ещё открыты;
исторические результаты и хэши архивов ниже не изменены.

**Итог плана: BLOCKED на обязательном §2. Автономность Linux не принята.**
Кандидат 0.13.1 содержит независимые исправления безопасной отмены/диагностики;
привилегированного MCP-моста нет. Публичного релиза и изменений пользовательских
программ, PROD/БД или сетевых/approval-настроек не выполнялось.

## Воспроизведённый блокер

В реальном shell модуля macOS / Codex CLI 0.154.0 / workspace-write/on-request /
network_access=true вызван только read-only `context({})` чужого тестового треда.
Поддерживаемый `mcpServer/tool/call` принял threadId координатора и произвольный
`_meta`. MCP получил подставленные itemId/callId/turnId от **правильного native
App Server**. Фактический CODEX_THREAD_ID инициатора остался модульным.

[JSON с native-свидетельством](evidence/orchestrator-linux-gate-20261030/macos-mcp-caller-binding.json):
`same_native_parent=true`, `thread_turn_binding=true`, `native_report_matches_file=true`,
но `shell_cannot_impersonate_coordinator=false`, verdict **BLOCKED**. Неудача самого
теста (например, TypeError) не считается запретом доступа; это покрыто регрессией.
Доказательство shell взято из stdout точного успешного native commandExecution того
же хода/треда и сверено с файлом, а не принято из редактируемого JSON.

На Linux / CLI 0.165.0 метаданные есть, но shell не может открыть сырой сокет:
[JSON](evidence/orchestrator-linux-gate-20261030/linux-mcp-caller-binding.json).
Это PASS узкой пробы транспорта/текущей изоляции, **не PASS автономности** и не
доказательство общей межролевой аутентификации для обеих ОС.
[ADR с решением и конкретной нехваткой API](../adr/2026-10-30-codex-stdio-bridge.ru.md).

## Матрица исходного архива и кандидата

Релизная база `e1134fdf92346a2911163042b74d8a47b7831b46`, тег
`pepper-orchestrator-v0.13.0`. Архивы скачаны из релиза; SHA256SUMS сверены:

```text
4c1e9ace0e0f528df998cadef090ddab17dd091da83aefdc9ed01d9480d37e68  pepper-orchestrator.plugin.zip
b72ade91dae2b05a43ff76b1e48c180783ee05d89985ba2e45af7bf02afcf0d4  pepper-orchestrator.zip
```

| Проверка | Исходный 0.13.0 | 0.13.1 safety-fix candidate |
|---|---|---|
| Codex macOS живой цикл | [PASS](evidence/orchestrator-linux-gate-20261030/release-0.13.0-macos-live.json): 3 WP, перекрытие ходов, reuse, squash/delete, compaction | Общий новый E2E не объявлен; gate §2 остановил привилегированный мост |
| Codex Linux живой цикл | [WAIT / безопасный отказ](evidence/orchestrator-linux-gate-20261030/release-0.13.0-linux-live.json), назначений нет | Автономность остаётся заблокированной |
| CLI/MCP 0.154.0, macOS | Native metadata доступны, но подменяются через сырой RPC | Привилегированный мост не включён |
| CLI/MCP 0.165.0, Linux | Native metadata доступны; прямой shell-RPC отказал | Это диагностическая проба, не кандидат E2E |
| Cancel при запрете наблюдения | Ошибка принималась за `still_live=False` | Отказ, все назначения/outbox/слоты/locks сохранены |
| Claude | Исторический Linux live в отчёте 0.13.0 | 15 обязательных регрессий входят в общий набор; новый live не подменяется ими |

Первый macOS-повтор в пользовательском CLI-config остановился из-за config drift.
В итоговом повторе драйвер использовал отдельный CODEX_HOME с копией только
аутентификации, без пользовательских MCP; копия удалена после завершения.
Исходные релизные байты не менялись. Историческая запись Linux-отказа сохранена.

## Локализация Linux

[Свидетельства из shell координатора и обоих модулей](evidence/orchestrator-linux-gate-20261030/linux-shell-boundary.json):
App Server — EACCES/13; PID хоста — ENOENT/2; PID namespace отличается от хостового;
boot_id читается; служебный каталог — EROFS/30. Host-side наблюдение того же App Server
работает, но переносить его полномочия без доказанной аутентификации нельзя.
Реальные пути отказа: owner/consume требуют identity процесса; compatible/next —
живое наблюдение; transition — наблюдение и Git-подготовку; watcher/recover/compact
требуют того же runtime. Один успешный connect не закрывает эти зависимости.

Эксперимент дошёл до Linux shell-перехода и отдельно выявил EROFS для FETCH_HEAD
общего Git-каталога worktree. Минимальный command/exec повторил отказ с явной
workspaceWrite policy; дополнительные writableRoots `.git`/bare mirror его не сняли.
Fetch/setup на хост не переносился. Экспериментальный мост после контрпробы удалён
из исходников/поставок; его промежуточный macOS PASS не считается безопасной приёмкой.

## Реализованный безопасный объём

- Три результата process observation: live / proven exited / unavailable.
  Смена/неизвестный PID namespace, недоступный boot_id, EACCES, timeout и некорректное
  подтверждение сохраняют резервирование. Известный завершившийся процесс по-прежнему
  позволяет отмену с прежними CAS/idle/evidence-проверками; outbox не удаляется.
- Native Codex выбирается из официального npm-пакета непосредственно; PID принадлежит
  бинарному App Server. Native smoke проверяет формат исполняемого файла.
- Ошибка fetch сохраняет диагностический stderr с маскированием HTTP userinfo.
- Явный платный read-only MCP reproducer, изоляция config живого стенда, проверка
  извлечённого skill против указанного ZIP и фиксация commit/SHA/profile в verdict.
- EN/RU recovery-шаблоны, resume/dispatch/close и CHANGELOG отражают безопасный отказ.

## Проверки безопасного объёма — PASS

Проверенный runtime snapshot: `6d59bfac32da3dd3985ea021b9645d346adad5a0`.
Последующее дополнение отчёта/перевода не меняет ни одного поставляемого файла.

| Проверка | Результат |
|---|---|
| Полный локальный `scripts/check.sh` | PASS, без изменений исходников |
| Autonomy | 41 тест, в том числе все 15 Claude-регрессий |
| Read-only MCP reproducer | 3 offline-регрессии; неожиданный сбой не становится PASS |
| Извлечённые skill/plugin ZIP и Codex-копия | Все selftest/runtime/reliability/autonomy PASS; одно каноническое ядро |
| Native transport | macOS CLI 0.154.0 PASS; формат исполняемого файла проверен |
| [CI](https://github.com/ITSalt/PepperSkills/actions/runs/41033211497) | Все 7 jobs PASS: Linux Python 3.10/3.12, macOS Python 3.12, runtime Linux/macOS/Windows, native Windows/PowerShell, compare-packages |
| Воспроизводимость | Linux/macOS/локальные хеши совпали; отдельно сверены с [native Windows job](https://github.com/ITSalt/PepperSkills/actions/runs/41033211497/job/123987673786) |
| Приватность и cleanup | PASS: пользовательские config без тестовых MCP, копий test auth не осталось; все 9 одноразовых GitHub-репозиториев архивированы |

Кандидат 0.13.1 (unreleased, это не Linux E2E и не публикация):

```text
8783133d206664931f2478b817e02f05388abe7da11e95e3f81728b6cc8dde2c  pepper-orchestrator.plugin.zip
08cd36def0d0a2885a3c7b639a2dbff08282717047fda3c492ea0d12db104204  pepper-orchestrator.zip
```

Shared proxy отдельно проверен в изолированном CODEX_HOME на обеих версиях:
initialize закрылся без ответа, работающего общего daemon в этих fixture не было.
Поэтому не утверждается, что proxy видит явный сервер: реальные прогоны используют
его точный Unix endpoint. [Свидетельства](evidence/orchestrator-linux-gate-20261030/shared-proxy.json).


## Повторение и границы

```bash
python3 scripts/probe-orchestrator-codex-mcp.py --run \
  --skill plugins/pepper-orchestrator/skills/pepper-orchestrator \
  --model TEST_MODEL --output /tmp/pepper-mcp-proof.json
```

Модель теста выбирается явно из доступных на хосте; здесь `gpt-6-astra`. Платные
пробы не включены в CI. Тест создаёт только собственные треды, не возобновляет
пользовательские, архивирует их и останавливает свой native сервер. Одноразовые
GitHub-репозитории живых baseline/экспериментальных прогонов архивированы.

§3–§7 исходного плана не считаются реализованными/принятыми как автономность.
Для продолжения нужен доказанный неподменяемый субъект MCP-вызова либо отдельно
согласованная граница сырого RPC, затем Git-подготовка и единый Linux/macOS E2E.
#23, mixed clients, multi-host, ранний reuse, постоянный сервис, Windows live и PROD
остаются вне работы. Релиз не опубликован, существующие программы не включены.
