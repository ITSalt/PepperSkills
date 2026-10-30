# Linux: явный Git-grant при сохранённой песочнице

**GIT_APPROVED_FIXTURE_PASS / AUTONOMY_NOT_RUN.**
[English canonical](pepper-orchestrator-git-approved-linux.md).
[Evidence и хэши](evidence/orchestrator-git-approved-linux/README.md).

Выбранный владельцем режим проверен на одноразовом Linux-fixture. CLI 0.165.0
применяет ограниченный файловый grant при сохранённых workspace-write/on-request,
approvals reviewer=user, network=true и отдельных runtime roots модуля/координатора.
Глобальные config, сервисы, CLI, пользовательские программы и поставляемый runtime
плагина не менялись.

| Проверка | Итог |
|---|---|
| Штатный запрос/ответ: ровно шесть Git-каталогов, scope=turn | PASS |
| Fetch нового upstream-коммита, новая ветка, setup модуля | PASS |
| Owner-код/состояние, Git config, чужая metadata и control FD защищены | PASS проверенных путей |
| Новые команды следующего хода не получают прежний grant | PASS |
| Другая сессия не наследует grant, пока он действует у модуля | PASS |
| Restart того же thread ID не восстанавливает grant | PASS |

В изолированном config включён только дополнительный
`features.request_permissions_tool=true`. Эта возможность в проверенном CLI
экспериментальная и по умолчанию выключена. Модель вызвала native
`request_permissions`; владелец проверил настоящий thread/turn/cwd и точный набор
путей, зафиксировал WAIT и вернул файловые разрешения с `scope=turn`.
Человек выбрал режим теста; ограниченный тестовый controller ответил на native
запрос. Это не ручной клик в native UI и не правило автоодобрения реальных программ.

Запись разрешена только в private gitdir модуля, общей object database, его
`refs/heads/gate/module` и reflog, origin tracking refs и их reflog. Common config,
hooks, ветка координатора и его private HEAD остаются read-only. Git metadata
расположена вне общей writable temp-директории; runtime root — только отдельный
worktree. Общего umbrella root или обхода переносом gitdir нет.

До grant все шесть write-canary дают EROFS, fetch — exit 255. С grant fetch
получает ранее отсутствовавший коммит upstream, новая `gate/module/next` указывает
именно на него, setup выполняется в shell модуля. Десять protected write-проб
по-прежнему дают EROFS, попытки получить control FD владельца/native — ENOENT;
хэши protected-файлов совпадают. `require_escalated`, session grant,
`acceptForSession` и изменения execpolicy не принимались.

Защищённый барьер владельца удерживает helper/ход модуля до завершения команды
другой сессии. Native события доказывают порядок: grant → старт команды модуля →
старт/завершение команды другой сессии → завершение команды модуля. Другая сессия
не получает запись ни в один из шести каталогов. После окончания хода и после
доказанной остановки/resume прежнего runtime новые команды того же модуля также
снова лишены этих прав. Все helpers конечные.

Получен настоящий code-mode tool inventory: 13 инструментов, без общего owner
App Server RPC. `process`, `require`, `fetch`, `Deno`, `Bun` — undefined;
`node:fs`/`node:net` возвращают `unsupported import in exec`. MCP servers пуст,
remote control выключен, в snapshots владельца/потомков listener не найден.
Настоящий default `codex queue` на тестовый coordinator thread с правильным
изолированным CODEX_HOME отказывает при запуске embedded server с EROFS.
Это не проба с заведомо вымышленным endpoint. Пять запросов turn/start дали ровно
пять native started: лишнего исполнителя/модельного хода не появилось.

Эти факты дополняют прежний private-STDIO отчёт и сужают пробелы inventory/queue.
Общий §2 ещё требует macOS и итоговой проверки интеграции. Нет заявления о всех
будущих CLI/дополнительных MCP или готовом scheduler. Поставляемого
привилегированного моста/общего host runner нет.

Первый прогон (`780cf09`, три хода) неполон: обвязка повторно прочитала уже
обработанный approval из истории. Второй grant она не выдала. Добавлена регрессия
фильтрации по текущим native thread/turn; новый fixture (`50552a3`, пять ходов)
независимо прошёл шесть gate. Модель в обоих случаях одна: gpt-6.1-sol, high.
Всего восемь turn/start/native started, два ограниченных grants; внутренних
provider HTTP/inference-вызовов отдельно не считали. Хэши native/source/library,
команды повторения и источник API — в English-отчёте и evidence.

Проверено истечение прав для новых команд. Отзыв sandbox уже работающего фонового
процесса не проверялся: native хранит launch permissions, что видно в исходнике
stdin_approval по ссылке English-отчёта. Перед production reuse нужны конечные
prep-helpers, проверка активных terminals/processes и drift прав. Git metadata с
grant изменяема: host-наблюдения должны закреплять зарегистрированные пути и не
исполнять project hooks/filters/setup или доверять writable gitdir pointer.
macOS, сквозной coordinator/watcher/reuse и приёмка одного архива ещё впереди.
Прежний отказ при неизменённых правах не переименован в PASS.

Локально PASS: 14 Git-grant тестов, 11 private-STDIO и три MCP. Git-grant suite
подключён к offline check и runtime CI Linux/macOS/Windows; платных проб в CI нет.
Прежняя полная offline-приёмка и хэши поставляемых архивов не менялись; для новых
диагностик/tests нужен свежий CI. Нового релиза или полной автономности не заявляем.

Все сохранённые тестовые треды архивированы; неиспользованный coordinator первого
прогона не имел rollout. Копии auth удалены, известные PID отсутствуют, процессов
с cwd обоих fixtures не осталось. Отдельная archive-cleanup проверка — ноль
модельных ходов. GitHub-репозитории для этих проб не создавались.
