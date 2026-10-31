# Промпт Linux-агенту: закрытый STDIO и подготовка Git

[English canonical](2026-10-30-orchestrator-linux-agent.md).
Скопируйте текст после разделителя в чат агента на Linux. Это исследование gate,
ещё не разрешение реализовать привилегированный scheduler или объявить Linux PASS.

---

Проверь безопасный путь к автономности Codex на Linux в PepperSkills без
ослабления sandbox/approvals. Репозиторий `ITSalt/PepperSkills`, ветка
`codex/orchestrator-linux-acceptance`, draft PR #42. Найди существующий checkout,
прочитай инструкции и git status, сохрани чужие изменения. Получи актуальную ветку,
запиши точный HEAD; обязательные предки — `6d59bfa` (безопасная отмена) и `35b3626`
(отчёт gate). Прочитай обновлённые документы из ветки. Если их нет — сначала
получи обновлённые файлы, не тестируй старый вариант:

- `docs/plans/2026-10-30-orchestrator-codex-linux-acceptance.ru.md`
- `docs/adr/2026-10-30-codex-private-stdio-tools.md`
- `docs/adr/2026-10-30-codex-stdio-bridge.ru.md`
- `docs/validation/pepper-orchestrator-0.13.1-linux-gate.ru.md`

Прежний дизайн опровергнут: реальный shell модуля на macOS мог обратиться к
MCP-соединению другого треда через `mcpServer/tool/call` и подделать `_meta`.
Linux EACCES на сокете не доказал общую привязку роли. Не возвращай старый мост.
Новый вариант: владелец держит анонимные pipes одного native App Server с
`--listen stdio://`, без owner socket/proxy/remote ingress; native dynamic tool
передаётся владельцу как server request `item/tool/call`. Роль берётся из
защищённой регистрации треда и нативного envelope, а не arguments. Это гипотеза
до проверки изоляции; сами dynamic tools не являются аутентификацией.

Разрешены одноразовые локальные fixtures и минимальные явные прогоны с моделью
для этого gate. Используй доступную frontier-модель, запиши её имя и число вызовов;
не меняй модель посреди теста ради успеха. Изолируй CODEX_HOME без посторонних
инструментов, используй только имеющийся на этой машине login, не запрашивай
пересылку секретов; тестовую копию auth затем удали. Не меняй глобальные config,
CLI, сервисы, пользовательские сессии/проекты, PROD/БД, ничего не выпускай и не
сливай. Для этих проб достаточно локального bare remote и двух worktree,
GitHub-репозиторий не нужен. Новые чаты и делегирование не нужны.

1. Запиши ОС/ядро/Python, все Codex в PATH, фактический native binary/хэш,
   версию и эффективные permissions. Прошлый Linux имел CLI 0.165.0, но на этой
   машине это надо проверить. Сгенерируй схему через
   `app-server generate-json-schema --experimental`. Проверь help/schema:
   experimentalApi, dynamicTools, server requests, approvals, remote control и
   resume с сохранёнными tools. Начни без модели. Не выводи старую поддержку
   из современной документации.
2. Сделай минимальный воспроизводимый read-only probe, а не production-мост.
   Код владельца/imports/config/роли/журналы держи вне model-writable roots;
   изолируй imports, не исполняй проектные hooks. Один App Server на private
   STDIO, один координатор и один модуль. Зарегистрируй только
   `pepper_context({})`. Сохрани реальные workspace-write/on-request и прежний
   тестовый network_access=true, запиши runtime writable roots. Не получай PASS
   за счёт более строгой сети. Отключи и проверь альтернативный ingress.
3. Оба реальных модельных хода должны вызвать context. Сохрани native
   item-start/request/completion и правильные разные роли. Из модуля попытайся
   подставить чужие ID в arguments и вызвать операцию координатора через общий
   dispatcher с тестовым handler без side effects. Отказ должен быть до записи;
   одной ошибки JSON schema недостаточно для проверки авторизации.
4. Из реального shell модуля проверь owner RPC и получение управляющих FD:
   socket/CLI queue/proxy/remote ingress, унаследованные FD, `/proc`, `/dev/fd`,
   другие доступные proc roots, ptrace/pidfd там, где поддержаны. Только созданные
   тестовые процессы и read-only identity-вызовы. Проверь и другие включённые
   инструменты, способные достичь owner RPC. Докажи отсутствие listener именно
   этого runtime; localhost/chmod недостаточно. Проверь запись host-кода/ролей,
   symlink/path/import/restart injection. Sandbox для проб не ослабляй.
5. Native approval должен оставаться pending без ответа человека. Никаких
   auto-accept, acceptForSession, allow-rules и grants. Неизвестные server requests
   отказывают безопасно. Disconnect/restart: сброс epoch, доказательство остановки
   прежнего runtime, resume того же тестового треда без второго исполнителя,
   проверка persisted tools и отказ старому call. Неподдержанный resume так и укажи.
6. Независимо проверь Git fetch/новую ветку/setup из shell модуля при том же
   профиле на локальном bare fixture. Запиши `.git`/resolved-gitdir, точный отказ
   и native approval request. Ранее FETCH_HEAD давал EROFS даже с extra roots.
   Не переноси gitdir, не выполняй host fetch/setup, не меняй protected paths,
   roots/profile, sandbox или approvals ради успеха. Если нужен approval —
   сохрани WAIT и точный scope для человека: этот промпт не разрешает принять
   запрос. Прогон с расширенными правами не закрывает неизменённый профиль.

Сохрани небольшой повторяемый probe, offline-тесты его verdict/provenance и
обезличенные evidence в `docs/validation/evidence/`. Доказательство — события
владельца плюс точный native commandExecution; одного writable JSON недостаточно.
Timeout, ошибка Python или неподдержанный syscall дают INCONCLUSIVE этой пробе,
а не security PASS. Отдельные verdict: API, caller binding, RPC/FD isolation,
host integrity, approvals, recovery и Git preparation.

Остановись перед production-интеграцией. При PASS всех security-проверок сообщи
`LINUX_SECURITY_GATE_PASS / AUTONOMY_NOT_RUN`, предложи реализацию этапов 3–7 и явно
укажи необходимость macOS negative probes до поставки общих host-операций.
Один Linux-прогон не закрывает общий §2. Если Git не имеет допустимого пути,
отдельно BLOCKED_GIT_PREPARATION.
Любой security FAIL/INCONCLUSIVE оставляет §2 BLOCKED. Не объявляй Linux autonomy
PASS: для этого нужна вся приёмка одного архива на Linux/macOS из плана.

Прогони уместные offline-проверки, останови только свои процессы/треды, удали копии
auth, сохрани обезличенные журналы. Верни patch/commit, команды запуска и краткий
отчёт, который я передам агенту планирования. Push, merge, release и внешние
сообщения не нужны. Укажи: что доказано/опровергнуто, точный native profile и
approval state, оставшийся блокер и следующий безопасный шаг.
