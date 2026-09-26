# Установка, использование и обновление

Проверено по документации 26 сентября 2026. Команды ниже относятся к
**текущему** дереву `plugins/<name>/skills/<name>/`.
[Новая структура](repository-structure.ru.md) пока предложена, но не внедрена.
Установки на этой машине в ходе исследования не выполнялись.

## Что устанавливаем

| Сущность | Содержимое | Использование |
| --- | --- | --- |
| Skill | `SKILL.md`, references, scripts, ресурсы | Агент обнаруживает папку и загружает инструкции |
| Plugin | Skills, манифест, при необходимости MCP/hooks/commands | Установка средствами клиента |
| Chat-адаптер | Самодостаточный текст | Вставка в диалог или поле инструкций |
| Marketplace | Каталог ссылок на плагины | Обнаружение и распространение пакетов |

Переименование папки не меняет формат. Переносимость инструкций не гарантирует
наличие Python, браузера, сети и разрешений в каждой среде.
[Agent Skills](https://agentskills.io/specification),
[Agent Plugins](https://agent-plugins.org/).

## Схемы использования

| Схема | Когда удобна | Кто обновляет |
| --- | --- | --- |
| Общий каталог + симлинки | Несколько локальных агентов используют один skill | Владелец общего источника |
| Менеджер skills | Нужны поиск, установка и обновления готовой командой | Менеджер; его копии не редактируют вручную |
| Проектная установка | Команда получает skills вместе с проектом | Git проекта или bootstrap с фиксированной версией |
| Клон + прямой link | Разработка скилла, немедленная проверка изменений | Автор клона |
| Plugin / marketplace | Пакет с metadata, несколькими skills или интеграциями | Клиент плагинов |
| ZIP upload / аккаунт / организация | Claude Chat, Cowork, управляемая раздача | Загрузка или механизмы синхронизации продукта |
| Chat prompt | Разовый диалог или отсутствие skill-loader | Пользователь вставляет новый текст |
| API / серверное окружение | Автоматизация вне локального приложения | Пайплайн доставки в соответствующий runtime |

Это способы доставки, а не восемь реализаций методики. Project/global scope —
отдельная ось. CLI и Desktop могут использовать один пакет. Локальный симлинк
не доставляет файлы в облачный или серверный runtime.

## Общая папка и симлинки

Схема подтверждена двумя независимыми реализациями:

- **Vercel Skills CLI:** каноническая копия и symlink-установка; также есть
  `--copy`, выбор агентов, project/global scope и обновление. Это сторонний
  инструмент, а не официальный установщик каждого бренда.
  [Vercel Skills](https://github.com/vercel-labs/skills).
- **skillsync:** реестр `~/.agents/skills/`, ссылки из папок агентов и Git-наборы.
  Это пример реализации, а не предложение немедленно ставить ещё один менеджер.
  [skillsync](https://github.com/Akemid/skillsync).

Рекомендуемая ручная схема для PepperSkills:

```text
клон/plugins/<name>/skills/<name>/     ← канонические файлы сейчас
               ↑
~/.agents/skills/<name> ──────────────┘
       ↑                   ↑
Codex читает напрямую       └── ~/.claude/skills/<name> → общая папка
```

Здесь общая папка — точка подключения; источник остаётся в клоне. Менеджер
может вместо этого хранить там реальную управляемую копию. Не смешивайте
ручную и менеджерную установку одного имени.

| Клиент | Подтверждённые точки подключения | Примечание |
| --- | --- | --- |
| Codex | `.agents/skills/`, `~/.agents/skills/` | Поддерживает ссылки на skill-каталоги |
| Claude Code | `.claude/skills/`, `~/.claude/skills/` | Отдельный skill может быть симлинком |
| Gemini CLI | `.gemini/skills/`, `~/.gemini/skills/`; также `.agents/skills/`, `~/.agents/skills/` | Общая папка документирована как alias |

Источники: [Codex](https://developers.openai.com/codex/skills/),
[Claude Code](https://code.claude.com/docs/en/skills),
[Gemini CLI](https://geminicli.com/docs/cli/using-agent-skills/).

Для остальных агентов проверяйте документацию установленной версии. Таблицы
менеджеров могут отставать: например, встречается `~/.codex/skills`, тогда как
актуальная документация Codex рекомендует `~/.agents/skills`. Не создавайте
обе ссылки автоматически. Не связывайте целиком `.claude`, `.codex` и caches:
там находятся и другие данные приложений.

### macOS / Linux: существующий клон

Замените путь на свой. Пример не перезаписывает существующую установку:
при конфликте сначала выясните, кто ею управляет.

```bash
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_skill="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_skill/skills/$pepper_skill"
test -f "$pepper_source/SKILL.md"
mkdir -p "$HOME/.agents/skills"
# Отдельная проверка важна: ln может создать вложенную ссылку в существующей папке.
test ! -e "$HOME/.agents/skills/$pepper_skill"
test ! -L "$HOME/.agents/skills/$pepper_skill"
ln -s "$pepper_source" "$HOME/.agents/skills/$pepper_skill"

# Только если нужен Claude Code:
mkdir -p "$HOME/.claude/skills"
test ! -e "$HOME/.claude/skills/$pepper_skill"
test ! -L "$HOME/.claude/skills/$pepper_skill"
ln -s "$HOME/.agents/skills/$pepper_skill" "$HOME/.claude/skills/$pepper_skill"
```

Проверка и обновление ручного клона:

```bash
readlink "$HOME/.agents/skills/pepper-prompt-engineer"
git -C "$HOME/projects/PepperSkills" status --short
# Только для чистого клона, если выбран канал текущей ветки:
git -C "$HOME/projects/PepperSkills" pull --ff-only
```

Рабочий клон с незавершёнными изменениями так не обновляйте. Для фиксированных
версий используйте отдельный installation-клон на tag/commit. После обновления
проверьте вызов в новой сессии. Для отката переключайте только installation-клон
на предыдущую ревизию. Для удаления ручной установки уберите именно ссылку,
проверив её тип; сначала отключите зависимые ссылки агентов. Исходник сохраняется.

### Windows и WSL

Native Windows использует папки профиля пользователя. Создание symlink может
потребовать Developer Mode или повышенных прав; при недоступности используйте
copy-режим установщика либо штатный plugin. Это различие установки, а не
отдельная методика скилла.
[skillsync: Windows](https://github.com/Akemid/skillsync#windows-powershell).

У WSL и native Windows разные домашние каталоги и окружения. Установка в WSL
не означает доступность в Windows Desktop. Пакет должен находиться в среде,
где работает агент. Windows/WSL в рамках этого аудита не тестировались.

## Skills CLI

Пример из корня **локальной рабочей копии**:

```bash
npx skills add ./plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer --list
npx skills add ./plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer -g -a codex -a claude-code
```

Первая команда проверяет обнаружение, вторая устанавливает. `npx` может загрузить
CLI; здесь он не запускался. Для внешней установки используйте опубликованный
Git URL/путь: текущие untracked изменения не обязательно есть на GitHub.

`npx skills list` показывает установки, `npx skills update` обновляет их,
`npx skills remove` удаляет. Для командной автоматизации фиксируйте версию CLI
и источник. Local-path install не следует считать обещанием live-link к клону:
проверяйте фактическое расположение канонической установленной копии.
[Vercel Skills: команды](https://github.com/vercel-labs/skills).

## Проектная установка

Для Codex: `<project>/.agents/skills/<name>`, для Claude Code:
`<project>/.claude/skills/<name>`. Команда получает реальные файлы в Git либо
bootstrap с зафиксированным источником. Абсолютный личный симлинк на `/Users/...`
не является воспроизводимой командной поставкой.

Не устанавливайте без необходимости один продукт как standalone skill и plugin
одновременно: могут появиться две точки вызова или версии. Codex предупреждает,
что совпадающие имена skills не объединяются.
[Codex: обнаружение](https://developers.openai.com/codex/skills/).

## Плагины и marketplace

В текущей рабочей копии есть `.agents/plugins/marketplace.json`,
`.claude-plugin/marketplace.json`, `.cursor-plugin/marketplace.json`.
Они ссылаются на `plugins/<name>`. Наличие файлов не подтверждает публикацию
или приёмку клиента.

**OpenAI.** Есть переносимый `plugin.json`, совместимость с `.codex-plugin`,
локальные/repo marketplaces и отдельный публичный каталог. Документирована
команда `codex plugin marketplace add ./local-marketplace-root`; для локальной
установки и проверки документация направляет в Desktop. Доступность канала
зависит от конкретной среды.
[OpenAI: упаковка и marketplace](https://developers.openai.com/plugins/build/plugins).

**Claude.** Plugin объединяет skills и другие компоненты, marketplace
распространяется отдельно. Вызов skill может получить namespace
`/plugin-name:skill-name`. Обновляйте и отключайте plugin средствами клиента.
[Claude: плагины](https://code.claude.com/docs/en/plugins),
[marketplace](https://code.claude.com/docs/en/plugin-marketplaces).

**Cursor.** Есть собственный manifest и marketplace. Ссылка из
`~/.cursor/plugins/local` на plugin вне этой папки пропускается клиентом.
Используйте поддерживаемый marketplace или реальные файлы локального plugin.
Схему симлинков для standalone skills нельзя переносить на целые плагины.
[Cursor: плагины](https://prod.cursor.com/docs/plugins).

Plugin cache не является авторским репозиторием. Исправления делаются в
исходниках и доставляются обновлением. Не редактируйте установленные копии
и не подменяйте весь кэш симлинком.

## Claude Chat, Cowork и ZIP

Для custom skills документирована загрузка ZIP с верхней папкой
`<name>/SKILL.md` и ресурсами, а не всего PepperSkills. Текущие `.skill` — ZIP
по содержимому, но для UI с документированным ZIP следует выпускать `.zip`.
[Claude: упаковка](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills).

Локальная `~/.claude/skills` не равна набору Cowork/cloud. Документация отдельно
описывает skills аккаунта и синхронизацию. Установка на диск и включение для
аккаунта — разные операции; проверяйте результат в нужной поверхности.
[Claude: области загрузки](https://code.claude.com/docs/en/skills).

## Чат без установки skill

Сейчас готовые тексты лежат в `plugins/<name>/adapters/chat/`:
Prompt Engineer — `chat-prompt.md`; Creative Mode — `system-prompt.md` и
`custom-instructions.md`; RU Web Compliance — те же файлы плюс
`manual-checklist.md`.

Для разового использования скопируйте готовый текст в диалог. Для постоянных
инструкций учитывайте ограничения поля продукта. Файл `system-prompt.md`,
вставленный обычным сообщением, не становится системным сообщением API.
Ручной compliance-режим работает с представленными доказательствами и не
заменяет обход сайта скриптами полного skill.

## Граница проверки

В этом аудите проверены локальные пути, симлинки, сборщики и первичные источники.
Клиентская установка PepperSkills не выполнялась. Для каждого заявленного
клиента и ОС нужен отдельный цикл: установка → вызов → обновление → отключение.
После миграции команды этого документа обновляются одновременно с исходниками.
