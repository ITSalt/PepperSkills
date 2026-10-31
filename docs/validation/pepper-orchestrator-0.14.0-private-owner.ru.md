# Private owner 0.14.0: приёмка Linux/macOS

31 октября 2026 года. **Runtime PASS (Git-approved, on-request)** на Linux и macOS
из одного неизменяемого архива. Кандидат не опубликован; PR #42 остаётся draft.
[English](pepper-orchestrator-0.14.0-private-owner.md).
[Native evidence, исходники проб и хеши](evidence/orchestrator-private-owner-0140-20261031/README.md).

Существующий scheduler соединён с владеющим сессиями App Server через private
STDIO. Владелец явно запускает одного координатора и фиксированные module threads.
Fetch, создание ветки и setup выполняются модулем внутри native sandbox. В
производственном launcher approvals остаются явными командами владельца.
Публичного privileged MCP/RPC endpoint, командного inbox, постоянного сервиса и
производственного auto-approval нет. Прозрачного подключения к desktop runtime нет.

## Проверенный артефакт

Runtime собран из `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d`.
Последующие изменения документации и test-driver сохраняют эти байты пакета.

| Артефакт 0.14.0 | SHA256 |
|---|---|
| Plugin ZIP | `57722062c318161abc7e477b9ae06e584289849743e83bd618b76ac8d4a4253a` |
| Standalone skill ZIP | `7bc64b887591f175097d3aff2f149d7940403ce71c64fc0dfc64079333d89cab` |

Обе машины использовали native Codex 0.165.0 и gpt-6.1-sol/high. macOS 27.0.1 arm64,
Python 3.14.5; Linux 6.8.0-147 x86_64/glibc 2.39, Python 3.12.3. Хеши native binary
приведены в английском отчёте и JSON evidence. Глобальные CLI/config macOS и
существующий Linux checkout не изменялись.

Профиль обеих ОС: workspace-write, on-request, reviewer=user, network=true,
без дополнительных базовых writable roots, один runtime workspace root на actor.
Remote control отключён, MCP пуст.

## Матрица

| Проверка | Linux | macOS |
|---|---|---|
| Native caller/role; модуль не вызывает coordinator operation | PASS | PASS |
| Закрытый tool surface, нет Node/process/network globals и fs/net imports | PASS | PASS |
| Owner code/config/roles/program/receipt, чужая Git metadata, FD/process probes | PASS | PASS |
| Hardlink/symlink aliases при настоящем Git-grant | PASS | PASS |
| Native WAIT, точные шесть Git roots, grant на один turn | PASS | PASS |
| Fetch/branch/setup модулем; STARTED по native command provenance | PASS | PASS |
| Истечение grant в новом turn и после restart | PASS | PASS |
| exec workdir вне actor root не расширяет право записи | PASS | PASS |
| Отказ native apply_patch при изменении owner canary | PASS | PASS |
| Watcher → consume → coordinator dispatch, перекрытие native turns | PASS | PASS |
| Третий WP: тот же thread/worktree, новая ветка после squash merge/remote deletion | PASS | PASS |
| Pause после queued signal без новых назначений | PASS | PASS |
| Restart на реально pending consume; безопасное списание старого wake-up | PASS | PASS |
| Потерянное уведомление о merge: fresh scan, без дублей назначений | PASS | PASS |
| Новый завершённый contextCompaction в том же owning server | PASS | PASS |
| Пустые enabled ticks: 0 model turns, program/runtime files неизменны | PASS | PASS |
| Настоящий owner_main --resume/status/pause/stop, те же threads, generation +1 | PASS | PASS |
| Project MCP canary, включая redirected commondir, без модели | PASS | PASS |

На каждой ОС завершены WP-A-02, WP-B-02 и зависимый WP-A-03. Владелец fixture
проверил точный head перед GitHub squash merge и удалил remote branches. Модуль A
использовал исходные native thread и worktree. Driver выполнял bootstrap и
review/merge одноразового private repository; dispatch делал настоящий координатор,
Git preparation — настоящий модуль.

Для recovery настоящий consume был остановлен перед handler. После pause runtime
завершён, выход дочерних процессов доказан. Новый owner восстановил те же три TID.
Только при совпадающей защищённой истории владения и положительном доказательстве
завершения старого процесса списан stale wake-up и запрошен fresh scan. ID назначений
и unknown delivery outbox сохранены; TASK не переотправлялся. Назначений ровно три.

В основном прогоне: **23 native model turns macOS, 28 Linux**. Дополнительный
console smoke на каждой ОС: три явных context turns и один watcher turn координатора,
без нового модульного исполнителя и без native approvals. Вспомогательные
archive/unarchive операции модели не запускали.

## Разрешения и исправления

Принят выбранный владельцем **Git-approved** режим. На каждой ОС test-controller
выдал **три ограниченных native grant**: request_permissions, ровно шесть
канонических Git metadata directories, scope=turn. Перед решением зафиксирован WAIT.
Контроллер применял выбранную владельцем политику fixture; **ручных native UI кликов
0** — это не выдаётся за три ручных подтверждения человека. Ещё один native
file-change запрос явно отклонён тестом. Производственный owner_main ничего не
одобряет автоматически. Blanket Git rules, session grants и unsandboxed retry не применялись.

JSON от модуля не даёт authority: prepared проверяет точные argv/cwd/turn настоящей
завершённой native command, защищённый nonce, assignment/generation, Git-факты,
configuration и helper hash. Для expiry/workdir probes также проверяется точная
native command; echo с правдоподобным JSON или упоминанием пути не считается пробой.

После ранних функциональных PASS дополнительный zero-model контроль нашёл дефект:
config/read пропускал недоверенный project layer, но thread/start сохранял trust
и запускал его собственный MCP canary. Проверки effective config недостаточно.
Исправление закрепляет project_root_markers=[] и untrusted для каждого actor cwd
в session flags выше persisted trust. Native config/hooks/exec rules модулей
остаются отключёнными до загрузки; start/resume/compaction проверяют метаданные
слоёв. Финальный canary не запускался на обеих ОС, в том числе после перенаправления
commondir. Sandbox и approval profile сохранились. Основание — native
[приоритет конфигурации](https://learn.chatgpt.com/docs/config-file/config-basic#configuration-precedence)
и [version-pinned loader 0.165.0](https://github.com/openai/codex/blob/rust-v0.165.0/codex-rs/config/src/loader/mod.rs).

Другие исправления: failed/exitCode=1 означает завершившуюся команду, неизвестный
exit status продолжает блокировать reuse/recovery; hash изолированного config
закрепляется после native bootstrap trust-записей; версии Codex entrypoint
синхронизируются из canonical manifest. Ранние candidate PASS не сертифицируют
финальный артефакт.

## Регрессии и границы результата

Локальный scripts/check.sh завершился из неизменяемого checkout с защищёнными
build code/temp roots: основной selftest, 11 runtime, 19 reliability, 41 autonomy
(включая 15 Claude), 20 owner, три adversarial provenance tests, protocol/grant/macOS
suites, извлечённые ZIP и generated Codex copy, component checks, воспроизводимость
архивов и отсутствие изменений исходников. Статус CI — в evidence/ci.json.

Живой Claude Code 2.1.312/sonnet на Linux, с прежним auto permission mode, также
прошёл сценарий из этого же архива: параллельная работа, same-session reuse и
подтверждённый PostCompact receipt. Fixture/controller находились вне общих tmp и
model write roots. Это проверка совместимости Claude, без утверждения о равенстве
его прав kernel sandbox Codex.

Репозитории fixture архивированы, native threads архивированы, известные native
и Claude процессы завершены, тестовые auth-копии удалены. Публичный export заменяет
имена/пути/host identifiers на aliases и исключает reasoning/account telemetry;
raw logs остаются локальными.

Поддержан явный closed owner mode с native 0.165.0. Native config/hooks/rules модулей
и required MCP в нём не поддержаны. Произвольные UNIX-сервисы/сеть хоста не входят
в утверждение об изоляции private owner; network=true сохранён. Истечение turn grant
относится к новым командам и не обещает отозвать права у уже живущего background
terminal. Нужны конечный setup и проверка retained processes; неизвестное время
жизни native command блокирует reuse/recovery. Windows — offline/native core smoke,
без private-owner live acceptance.

Исторический safe refusal Linux в 0.13.0/e1134fd сохранён; его прежний unchanged-profile
Git blocker не переименован в PASS.
[Запуск, manifest, opt-in, отключение и recovery](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/private-owner.ru.md).
Merge PR PepperSkills, release, deploy и production-изменения не выполнялись.
