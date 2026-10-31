# Private STDIO: Linux gate, 30 октября 2026

[English report](pepper-orchestrator-private-stdio-linux-2026-10-30.md).

**BLOCKED / AUTONOMY_NOT_RUN. §2 не закрыт. Отдельно BLOCKED_GIT_PREPARATION.**
Production scheduler, этапы 3–7, push, merge и release не выполнялись.
Новый probe находится только в `scripts/`, вне поставляемого runtime.

| Проверка | Verdict | Доказательство и граница результата |
|---|---|---|
| API | PASS | Native CLI 0.165.0: experimental initialize, dynamicTools и server request `item/tool/call`; клиентский вызов этого метода отвергнут с -32600 |
| Caller binding | PASS | Два настоящих треда вызывают context с разными ролями; живые подставленные ID остаются аргументами модуля. Общий dispatcher отказывает координаторской операции с `role_forbidden`, handler не вызван |
| RPC/FD isolation | INCONCLUSIVE | Проверенные shell-пути закрыты, listener не обнаружен. Полный аудит инструментов code-mode host и переноса FD не завершён; детали ниже |
| Host integrity | PASS | Код, config, роли, restart-canary и symlink/path-доступ дают EROFS; хеши до/после совпали; подложенный `json.py`/PYTHONPATH/PYTHONSTARTUP не загружается с `-I -S` |
| Approvals | PASS | Настоящий native request остаётся pending; owner не посылает ни одного ответа на него. Неизвестный server request отказывает в offline-тесте |
| Recovery | PASS | Прежний App Server завершился с rc=0, выполнен wait; только затем resume того же module threadId. Persisted context работает без повторной регистрации; старый epoch отвергнут |
| Git preparation | BLOCKED_GIT_PREPARATION | В shell модуля fetch и switch отказывают на FETCH_HEAD/HEAD.lock с EROFS; harmless setup-marker создаётся. Approval fetch оставлен WAIT |

Это PASS отдельных проверок данного fixture, не общего security gate, scheduler
recovery, Linux autonomy или одинакового архива на Linux/macOS.

## База и окружение

Получен актуальный `origin/codex/orchestrator-linux-acceptance`, точный HEAD:
`1776a223f977d40e10da45d1b59147f1a0ab54e6`. Проверены предки `1776a22`,
`35b3626`, `6d59bfa`. Исходный checkout `main` был чистым, stash пуст;
незакоммиченных пользовательских изменений не было. Обновление checkout потребовало
отдельного одобрения fetch/switch из-за read-only `.git`; это **не** результат Git gate.

Linux x86_64, Ubuntu 24.04, kernel `6.8.0-147-generic`, Python `3.12.3`.
Оба Codex в PATH — local-bin и npm-bin — разрешаются в один npm shim.
Фактически запущен native ELF из npm-пакета `@openai/codex-linux-x64`:

```text
codex-cli 0.165.0
native SHA256 c06a67fd8ac76508dc78bd99ce20c9f317b8d568beda59485f3f4134df9962d5
probe SHA256  8a330a0b0e9e1c09a880ae65f0554d04920cac8582885436ec7158abcf23d73e
```

Модель неизменна: **gpt-6.1-sol**, effort high. Всего 8 явных `turn/start`:
4 в исключённом диагностическом прогоне B и 4 в финальном C. Preflight и сбой
bootstrap — 0 ходов. Сохранены 18 native token-usage notifications двух прогонов;
это не измерение числа внутренних HTTP/inference-запросов провайдера.

## Точный финальный профиль и native provenance

Один App Server одновременно: `codex app-server --listen stdio://`; анонимные
pipes владельца, без socket/proxy endpoint. После disconnect старый процесс
доказанно завершён до нового запуска. Remote control явно отключён и проверен
через status/read; config показывает `remote_control=false`,
`daemon_auto_start=false`, пустые `mcp_servers`; native MCP list пуст.
Apps/plugins/remote-plugin/browser/computer/image generation/multi-agent/hooks
отключены в отдельном CODEX_HOME. Глобальные настройки не менялись.

Native thread/start и resume возвращают:

```json
{
  "approvalPolicy": "on-request",
  "approvalsReviewer": "user",
  "sandbox": {
    "type": "workspaceWrite",
    "writableRoots": [],
    "networkAccess": true,
    "excludeTmpdirEnvVar": false,
    "excludeSlashTmp": false
  },
  "runtimeWorkspaceRoots": ["/FIXTURE/WORK/module"],
  "cwd": "/FIXTURE/WORK/module"
}
```

У координатора root/cwd — `/FIXTURE/WORK/coordinator`. Extra roots, grants,
allow-rules, принятия предложенного execpolicy amendment не было. Доступ к `/tmp`
не сужался, сеть не ужесточалась ради результата. Изолированный host-код, config,
роли и журналы находятся под `/PROTECTED/OWNER`, вне этих roots и `/tmp`;
Python запущен с `-I -S -B`. Readable manifest не считается capability.

[Основное свидетельство](evidence/orchestrator-private-stdio-linux-20261030/linux-private-stdio.json)
сохраняет owner send/receive, native item-start/request/completion, исходный
commandExecution с exitCode=0 и полным stdout. Внутри него Git-подкоманды имеют
собственные ненулевые коды; успешный diagnostic wrapper не означает успешный Git.
Offline-тест связывает команду, cwd, тред, ход, stdout и SHA256 исполнявшегося probe.
Пути заменены согласованными aliases; PIDs, call IDs, epoch и errno сохранены.
Account telemetry и адреса TCP peers исключены; исходный JSON закреплён хешем.

## Что остаётся неизвестным в RPC/FD gate

В shell унаследованы только `/dev/null` и его output pipes, не owner control pipes.
Проверены найденные proc mounts, `/proc`, `/proc/1/root/proc`,
`/proc/self/root/proc`, `/dev/fd`; host PIDs/FD дают ENOENT. pidfd_open,
ptrace PEEKDATA без attach и process_vm_readv дают ESRCH.
**pidfd_getfd фактически не достигнут после отказа pidfd_open; PEEKDATA не является
проверкой успешного attach.** Эти результаты нельзя выдавать за общий запрет
соответствующих примитивов. Никакие чужие процессы не были целями.

Owner snapshots сопоставили socket inodes своих процессов и потомков (включая
code-mode host) с tcp/tcp6/unix: listener отсутствует до/после shell и после recovery.
Есть исходящие TLS-соединения и безымянные socketpairs; их peers не публикуются.
CLI proxy по тестовому адресу отказывает с ENOENT; socket-файлов в CODEX_HOME нет.

Это сильные отрицательные факты о проверенных путях, но snapshots не являются
непрерывным наблюдением, а полного списка/аудита фактически доступных модели
операций code-mode host и возможностей переноса FD здесь нет. Нет отдельного
проверенного queue ingress. `mcpServerStatus/list=[]` не доказывает отсутствие
всех native built-ins. Поэтому общий RPC/FD verdict **INCONCLUSIVE**, а §2 BLOCKED.
Следующий безопасный шаг — дополнить read-only probe наблюдаемым native-аудитом
tool surface и целевыми отрицательными FD/alternate-ingress пробами при том же
профиле; неподдерживаемые части оставить INCONCLUSIVE. Общие host-операции также
требуют macOS negative probes до поставки.

## Независимый Git gate и WAIT

При bootstrap созданы seed, local bare remote и два worktree, hooks отключены.
Host не выполнял fetch/setup вместо модуля. Gitdir не переносился между пробами:
в финальном fixture `.git` модуля — обычный worktree pointer в
`/FIXTURE/WORK/remote.git/worktrees/module`; common dir — `/FIXTURE/WORK/remote.git`.

```text
git fetch origin -> 255
error: cannot open '/FIXTURE/WORK/remote.git/worktrees/module/FETCH_HEAD': Read-only file system

git switch -c gate-prepared -> 128
error: Unable to create '/FIXTURE/WORK/remote.git/worktrees/module/HEAD.lock': Read-only file system
fatal: unable to update HEAD
```

Точный native approval scope: `/bin/bash -lc 'git fetch origin'`, cwd
`/FIXTURE/WORK/module`, reason `Allow fixture Git fetch to write the protected gitdir?`.
Native runtime сам предложил amendment `["git", "fetch", "origin"]`;
его не приняли. На момент наблюдения запрос pending, turn не завершён,
ответов owner — **0**. Затем закрыт только тестовый runtime без ответа на approval;
активного запроса для позднего принятия больше нет. Промпт не разрешал одобрение.
При будущей необходимости человеку нужен новый штатный запрос с тем же точным scope;
такой прогон с расширенными правами не закроет исходный профиль.

В прогоне B ошибочно указан общий root `/FIXTURE/WORK`, отчего Git прошёл.
[Этот результат исключён](evidence/orchestrator-private-stdio-linux-20261030/different-roots-excluded.json)
из приёмки, исправлена только спецификация fixture, выполнен C с отдельными roots.
[Первый bootstrap-сбой](evidence/orchestrator-private-stdio-linux-20261030/bootstrap-error.json)
на `git config --worktree` исправлен до любых модельных ходов и не считается
sandbox-отказом. [Zero-turn preflight](evidence/orchestrator-private-stdio-linux-20261030/api-preflight.json)
также не подменяет live security acceptance.

## Повторение, проверки и cleanup

В новом защищённом каталоге установите только standalone probe из `scripts/`.
`OWNER` должен быть вне repo/model writable roots и вне общей `/tmp`; повторный
запуск использует новый пустой каталог. Нужен существующий local login, не новый ключ.
Запуск owner требует обычного разрешения среды на этот каталог; это не native
approval модельного треда.

```bash
install -d "$OWNER"
install -m 700 scripts/probe-orchestrator-private-stdio.py "$OWNER/"
python3 -I -S -B "$OWNER/probe-orchestrator-private-stdio.py" \
  --preflight --owner "$OWNER" --output /tmp/private-stdio-preflight.json
# Для live используйте другой новый OWNER; это явный платный прогон.
python3 -I -S -B "$OWNER/probe-orchestrator-private-stdio.py" \
  --run --owner "$OWNER" --model gpt-6.1-sol --output /tmp/private-stdio-live.json
python3 -B scripts/test-orchestrator-private-stdio.py
```

Probe возвращает rc=2 при BLOCKED; это ожидаемый результат финального прогона.
Offline PASS: основной selftest, 11 runtime, 19 reliability, все 41 autonomy,
3 прежних MCP-regressions и 11 тестов нового probe.
**Полный `scripts/check.sh` НЕ PASS**: повтор в изолированном venv остановился
на `missing shell: zsh` в `test-install-links.sh`, exit 1; последующие проверки
установки/сборки/архивов не выполнялись. Первоначальный missing `h11` устранён
только в `/tmp` venv. Глобальные CLI не менялись; для полного check нужна среда
с zsh. Логи, версии зависимостей и хеши — в
[manifest](evidence/orchestrator-private-stdio-linux-20261030/README.md).
Все тестовые копии auth удалены; процессы проверяются только по известным PID
этого fixture. [Cleanup evidence](evidence/orchestrator-private-stdio-linux-20261030/cleanup.json).
Пользовательские треды, конфигурация, CLI, сервисы, проекты, PROD и БД не менялись.

## Независимая проверка на macOS

В checkout планирования получен patch SHA256
`e2fcab96c11bc795261f3589dfd0f7c86b8845edb13104c3c1f7354f198a84da`
на базу `1776a22`. Хэши manifest совпали; 11 новых и три прежних probe-теста PASS.
Отдельно проверены неизменность protected-файлов, тот же восстановленный module
thread, остановка старого runtime, отсутствие ответов на approval и cleanup.
Полный `scripts/check.sh` на macOS / Python 3.14.5 прошёл, включая извлечённые
архивы и воспроизводимость, без изменения исходников. Это не закрывает отсутствие
zsh в прежнем Linux-прогоне, живые RPC/FD/Git gate или macOS acceptance.

Разбор исходников 0.165.0 (ссылки в English-отчёте) показал: globals code-mode
ограничены callbacks/configured tools, module loader отвергает imports, вложенный
вызов использует исходные session/turn. Следующую пробу можно сузить до фактически
включённого tool inventory и alternate ingress, включая CLI queue, с проверкой
доступности FD по исходникам и нативным событиям. Сам по себе этот разбор не меняет
живой RPC/FD verdict. Дополнительных модельных ходов и grants при проверке не было.
