# Явный private owner для Codex (кандидат 0.14.0)

Режим Linux/macOS соединяет существующий scheduler с собственным App Server через
приватный STDIO. Владелец заранее объявляет единственного координатора и фиксированные
модульные worktree; launcher создаёт только эти native threads. Прозрачного подключения
к desktop-сессиям нет. Поддерживается native Codex **0.165.0**; другая версия получает
явный отказ. Обычный CLI/manual и Claude workflow сохраняются.

[Полная инструкция, manifest и команды](private-owner.md) — каноническая версия.
Установите проверенный архив вне Git checkout, actor writable roots и общих временных
каталогов. Запускайте owner через `python3 -I -S -B`. Launcher проверяет SHA256 архива,
байты установленного skill, отсутствие лишнего Python, symlink и hardlink. Отдельно
защищены native/Python/Git, program workspace, конфигурация, роли и runtime. Публичного
RPC/MCP endpoint, сокета owner, командного inbox, сервиса и глобальных настроек нет.

Manifest версии 1 задаёт model, workspace, coordinator.cwd и modules с module, wp,
cwd, branch_prefix. Все пути абсолютные. `wp` — последний завершённый пакет чистого
linked worktree; действуют обычные проверки accepted head, merge и удаления ветки.
Пространства веток должны различаться, например `orch/a/` и `orch/b/`, включая новые WP.
Первый owner-data должен быть пустым и отдельным от actor/workspace/installation.
`--preflight` проверяет архив и пути без модели; уберите флаг для явного запуска.
Локальная копия auth имеет режим 0600 и удаляется при выходе. Не переносите её между
машинами. Пользовательские config и сессии не меняются.

Профиль: workspace-write/on-request, reviewer=user, network=true, один runtime root
на actor, без дополнительных базовых writable roots, MCP и remote ingress. В этом
явном режиме отключены apps, remote plugins, browser/computer use, hooks, daemon и
дополнительные агенты. Сетевые возможности сохраняются: произвольные UNIX-сервисы
хоста не объявляются недоступными; у private owner нет доступного им сокета управления.
Каждый worktree проверяется до загрузки native thread.

Watcher без модельного polling вызывает общий scheduler и будит координатора сигналом.
Координатор через `pepper_orchestrator` вызывает consume/dispatch/reconcile, модуль —
context/prepare/prepared. Роль, thread, active turn/tool item и epoch берутся из native
канала и защищённой регистрации, а не из аргументов. Общего RPC/shell/path API,
создания сессий, изменения approvals, merge или deploy в tool нет.

Prepare возвращает конечную точную команду и шесть Git write roots: private gitdir,
objects, собственные branch/ref-log namespace, origin refs/ref-logs. Native
request_permissions остаётся WAIT. Владелец сверяет назначение, cwd, turn, пути и
команду, затем явно вводит `grant ID`; возможен только один grant этих путей на один
turn. Session grants, дополнительные read/network права, повторные и чужие запросы
отклоняются. `deny ID` отказывает. Производственного auto-approval и blanket Git
правил нет. Отдельный fixture-контроллер приёмки считает свои ограниченные решения
и не называет их ручными кликами native UI.

Fetch, ветка и setup выполняются самим модулем внутри sandbox. Prepared проверяет
реальную завершённую native command, nonce, assignment/generation, config/helper hash
и текущие Git-факты перед STARTED. Неизвестный исход не повторяется автоматически.
Host observer закрепляет Git-пути и отключает hooks, filters, fsmonitor, external diff,
implicit fetch; доступная модулю Git metadata считается изменяемой и не даёт host authority.

Консоль: status, pause, resume, grant ID, deny ID, stop. Pause блокирует назначения и
после queued signal; stop приостанавливает программу и завершает свой сервер. Для
повторного запуска добавьте `--resume` к прежней команде. Требуются положительное
доказательство завершения прежнего native process, те же code/native/config, отсутствие
команд с неизвестным временем жизни и сохранённые tools в тех же thread ID. Registry,
outbox и назначения сохраняются; новая generation не разрешает слепой resend. Изменение
кода/config требует явной миграции владельцем, lease или недоступный PID недостаточны.

Истечение turn grant проверяется для новых команд. Это не обещание отозвать права у
ранее запущенного фонового terminal: используйте конечный setup и проверяйте retained
processes. Незавершённая native command блокирует idle/reuse/prepare/compaction. Для
compaction требуется новый завершённый native contextCompaction в том же сервере.
Решения review/merge/deploy/production остаются у владельца.

Цель приёмки — PASS (Git-approved, on-request): автономное планирование с обычными
паузами approvals. Исторический unchanged-profile Git blocker не переименовывается
в PASS. Кандидат не опубликован; Windows проверяется offline/native core smoke,
живой private-owner сценарий Windows не заявляется.
