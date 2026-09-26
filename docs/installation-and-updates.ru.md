# Установка, использование и обновление PepperSkills

Срез документации: 26 сентября 2026. Канонические исходники находятся в
`plugins/<name>/skills/<name>/`. [English version](installation-and-updates.md).

## Что устанавливаем

| Сущность | Содержимое | Использование |
| --- | --- | --- |
| Skill | `SKILL.md`, references, scripts, ресурсы | Агент обнаруживает папку и загружает инструкции |
| Plugin | Skills, манифест, при необходимости MCP/hooks/commands | Установка средствами клиента |
| Chat-адаптер | Самодостаточный текст | Вставка в диалог или поле инструкций |
| Marketplace | Каталог ссылок на плагины | Обнаружение и распространение |

Переносимость инструкций не гарантирует Python, браузер, сеть и разрешения
в каждой среде. Переименование папки не меняет формат пакета.

## Схемы установки

| Схема | Когда удобна | Кто обновляет |
| --- | --- | --- |
| Общий каталог и симлинки | Несколько локальных агентов используют один источник | Владелец клона |
| Менеджер skills | Поиск, установка и обновления через CLI | Менеджер; его копии не редактируют |
| Проектная установка | Skills поставляются вместе с проектом команды | Git проекта или фиксированный bootstrap |
| Клон и прямой link | Проверка изменений при разработке skill | Автор |
| Plugin / marketplace | Метаданные и интеграции вместе со skills | Клиент / издатель плагина |
| ZIP / аккаунт / организация | Claude Chat, Cowork, управляемая раздача | Загрузка или синхронизация продукта |
| Chat prompt | Разовое использование без skill-loader | Пользователь вставляет новый текст |
| API / серверное окружение | Автоматизация вне Desktop | Пайплайн доставки в runtime |

Это способы доставки одной методики. Project/global scope — отдельная ось.
CLI и Desktop могут использовать один пакет; локальная ссылка не доставляет
его в облачный или серверный runtime.

## Общая папка и симлинки

Vercel Skills CLI поддерживает копирование и симлинки, выбор агентов и области
project/global. `skillsync` использует общий реестр `~/.agents/skills/` и ссылки
агентов. Оба — необязательные сторонние инструменты, не зависимости PepperSkills.

При ручной установке общая папка может ссылаться на клон:
`~/.claude/skills/<name> → ~/.agents/skills/<name> → клон/plugins/<name>/skills/<name>`.
Менеджер может хранить там настоящую управляемую копию; не смешивайте владельцев
одного имени skill и не связывайте целиком папки конфигурации и кэшей агентов.

| Клиент | Документированные папки skills | Примечание |
| --- | --- | --- |
| Codex | `.agents/skills/`, `~/.agents/skills/` | Поддерживает ссылки на отдельные skill-каталоги |
| Claude Code | `.claude/skills/`, `~/.claude/skills/` | Поддерживает ссылки на отдельные skill-каталоги |
| Gemini CLI | `.gemini/skills/`, `~/.gemini/skills/`; aliases `.agents/skills/`, `~/.agents/skills/` | Общая папка документирована как alias |

Для других клиентов и установленной версии сверяйтесь с документацией. В таблицах
менеджеров ещё может встречаться `~/.codex/skills`; не создавайте обе точки автоматически.

### macOS / Linux: существующий клон

Замените путь к клону и имя продукта. Уберите второй вызов помощника, если
Claude Code не нужен. Пример работает в Bash и Zsh:

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_name="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_name/skills/$pepper_name"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.agents/skills/$pepper_name" "$pepper_source"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.claude/skills/$pepper_name" "$HOME/.agents/skills/$pepper_name"
)
```

Подшелл сохраняет переменные и опции внешней оболочки. Помощники отклоняют обычные
файлы/каталоги и посторонние ссылки; цепочка, ведущая к каноническому источнику,
корректна. Распознанные старые ссылки PepperSkills можно безопасно перенастроить.

Перед обновлением проверьте ссылку через `readlink` и выполните `git status --short`
в клоне. `git pull --ff-only` используйте только для чистого клона, следующего ветке.
Для фиксированных установок и отката используйте отдельный installation-клон на
tag/commit. Проверьте активацию в новой сессии. При удалении сначала убедитесь, что
путь — симлинк, отключите зависимые ссылки агентов, затем удалите только свою
ссылку; сохраняйте исходник, пока им пользуется другая установка.

### Windows и WSL

Native Windows использует папки профиля. Симлинки могут требовать Developer Mode
или повышенных прав; иначе используйте поддерживаемый copy-установщик либо штатный
plugin. У WSL и native Windows разные домашние папки и runtime: устанавливайте
пакет в среде, где действительно работает агент.

## Skills CLI

Из клона команда `npx skills add ./plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer --list`
показывает найденные skills. Удаление `--list` и добавление `-g -a codex -a claude-code`
устанавливает их для этих агентов глобально. `npx` может скачать CLI. Для внешней
установки используйте опубликованный Git-источник; локальные незакоммиченные изменения
удалённо недоступны.

`npx skills list`, `npx skills update` и `npx skills remove` управляют установками.
В автоматизации фиксируйте версию CLI и источник. Local-path install не обещает
live-link: проверяйте, где менеджер хранит каноническую копию.

## Проектная установка

Codex использует `<project>/.agents/skills/<name>`, Claude Code —
`<project>/.claude/skills/<name>`. Добавляйте реальные файлы в Git либо bootstrap
с фиксированной ревизией источника. Абсолютные личные симлинки невоспроизводимы
для команды. Избегайте двойной standalone/plugin-установки, если не планируете
управлять двумя точками вызова; Codex не объединяет совпадающие имена skills.

## Плагины и marketplace

В репозитории есть `.agents/plugins/marketplace.json`,
`.claude-plugin/marketplace.json` и `.cursor-plugin/marketplace.json`; все ведут
в `plugins/<name>`. Файлы в Git не подтверждают публикацию или приёмку клиента.

**OpenAI:** переносимый `plugin.json`, совместимость `.codex-plugin`, локальные/repo
marketplaces и публичный каталог. Документация описывает
`codex plugin marketplace add ./local-marketplace-root` и установку/проверку в Desktop.
Доступность зависит от окружения.

**Claude:** plugin объединяет skills и другие компоненты; marketplace — отдельный
каталог. Вызов может иметь вид `/plugin-name:skill-name`. Обновляйте и отключайте
плагин средствами клиента.

**Cursor:** используйте его manifest и marketplace либо настоящие файлы поддерживаемого
локального plugin. Ссылка из `~/.cursor/plugins/local` на plugin вне этой папки
пропускается. Схема симлинков standalone skills не переносится автоматически на плагины.

Кэши клиентов — управляемые копии. Правьте исходный клон и доставляйте обновление;
не заменяйте и не редактируйте весь кэш плагинов.

## Claude Chat, Cowork и ZIP

Custom skills используют ZIP с одной верхней папкой `<name>/`, содержащей `SKILL.md`
и ресурсы. Загружайте пакет skill, а не весь PepperSkills. Standalone-архивы —
`<name>.zip`, пакеты плагинов — `<name>.plugin.zip`. Локальная `~/.claude/skills`
и загрузка в аккаунт/Cowork — разные области установки. Включите skill в нужной
поверхности и проверьте вызов, обновление и отключение. Для скиллов со скриптами
проверьте, что в этой среде включено выполнение кода.

Корневые `.skill` — прежние зафиксированные сборки из ревизии репозитория
`v1.4.1-1-g4128fe6` (commit `4128fe6`); они не пересобираются и не соответствуют
текущим версиям плагинов. Новые сборки находятся в `dist/<name>/<version>/`.
Загрузка и публикация замещающих ZIP — условия выпуска; используйте проверенный
опубликованный пакет, когда он доступен. Прежние Releases и теги сохраняются.

## Чат-адаптеры

Используйте готовые файлы в `plugins/<name>/adapters/chat/`:

| Продукт | Файлы |
| --- | --- |
| Prompt Engineer | `chat-prompt.md` |
| Creative Mode | `system-prompt.md`, `custom-instructions.md` |
| RU Web Compliance | `system-prompt.md`, `custom-instructions.md`, `manual-checklist.md` |

Вставьте подходящий текст в поле инструкций или диалог; учитывайте лимит поля.
Пользовательское сообщение не становится системным сообщением API. Ручной
compliance-режим требует доказательств из диалога и manual-checklist;
браузерный сбор полного skill он не выполняет.

## Переход со старых путей PepperSkills

Обновление репозитория не переписывает установленные ссылки. Этап A сохраняет
старые пути; новые ссылки направляйте на канонические исходники. Удаление — отдельный
этап B после проверенной загрузки ZIP, замещающих пакетов всех продуктов и переходного
выпуска с предупреждением о миграции.

| Старый путь | Канонический путь |
| --- | --- |
| `<name>/anthropic/` | `plugins/<name>/skills/<name>/` |
| `<name>/openai/` | `plugins/<name>/adapters/chat/` |
| `pepper-prompt-engineer/chat-prompt.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md` |
| `pepper-prompt-engineer/chat-prompt.template.md` | `plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.template.md` |
| `<name>/anthropic/INSTALL.md` | `docs/installation-and-updates.md`, `docs/installation-and-updates.ru.md` |

Для ручной общей установки (замените продукт и клон по необходимости):

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
pepper_name="pepper-prompt-engineer"
pepper_source="$pepper_repo/plugins/$pepper_name/skills/$pepper_name"
"$pepper_repo/scripts/link-skill.sh" "$pepper_name" "$HOME/.agents/skills/$pepper_name" "$pepper_source"
)
```

Проверьте через `readlink` и вызовите skill в новой сессии. Бывший
`anthropic/INSTALL.md` содержит временный указатель на эту инструкцию, исключённый
из новых ZIP. Для чат-каталогов и файлов промптов используйте подходящий тип пути:

```bash
(
set -eu
pepper_repo="$HOME/projects/PepperSkills"
"$pepper_repo/scripts/link-path.sh" chat pepper-creative-mode \
  "$HOME/.local/share/pepper-creative-mode" \
  "$pepper_repo/plugins/pepper-creative-mode/adapters/chat"
"$pepper_repo/scripts/link-path.sh" file pepper-prompt-engineer \
  "$HOME/.local/share/pepper-prompt-engineer-chat.md" \
  "$pepper_repo/plugins/pepper-prompt-engineer/adapters/chat/chat-prompt.md"
)
```

Обычные каталоги и посторонние ссылки отклоняются, а не перезаписываются. Для других
продуктов повторите явно; пользовательские установки автоматически не меняются.

## Решение проблем

- **Нет активации:** проверьте description установленного `SKILL.md` и включение
  skill, затем явно назовите его в новой сессии. Prompt Engineer активируется
  для составления промптов, а не обычного выполнения задачи.
- **Лишняя активация:** приложите пример в issue. Creative Mode должен пропускать
  математику, факт-чек, отладку и другие задачи с единственным верным ответом.
- **Виден только SKILL.md или нет ресурсов:** установите целую папку/ZIP с references,
  examples, scripts и evals, где они есть. Не загружайте один `SKILL.md`. Имя папки
  должно совпадать с `name` (строчные латинские буквы, цифры и дефис; не более
  64 символов); без двоеточий и пробелов. Запреты зарезервированных имён смотрите
  в спецификации целевого клиента.
- **У Creative Mode нет seed или остаётся смещение:** проверьте полную активацию и
  содержимое пакета. Проверьте температуру (ноль/фиксированный seed снижают вариативность),
  независимые прогоны в новых сессиях и способность модели к арифметике/reasoning.
  Серия бросков в одном диалоге не независима. Универсальной гарантии улучшения нет,
  особенно при уже честном бинарном baseline; случай QwQ-32B и смешанные задачи
  описаны в установленном `references/when-not-to-use.md`.
- **Промпт слишком короткий/длинный или неполный:** валидатор и eval-раннер из
  установленного `scripts/README.md` Prompt Engineer помогут найти недостающие
  или раздутые блоки CRAFT+. Явно запросите JSON (`output json`, `формат json`
  или `--json`); по умолчанию используется Markdown.
- **Недоступен браузер/PDF в Compliance:** скриптам нужен Python 3.10+;
  Playwright и Chromium устанавливаются отдельно по установленному
  `scripts/README.md`. Без браузера сбор идёт в degraded-режиме, а зависящие
  от браузера проверки должны оставаться UNKNOWN.

## Источники

- [Agent Skills specification](https://agentskills.io/specification)
- [Agent Plugins specification](https://agent-plugins.org/)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills/)
- [OpenAI plugins and marketplaces](https://developers.openai.com/plugins/build/plugins)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude plugins](https://code.claude.com/docs/en/plugins), [marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
- [Claude custom skills ZIP guidance](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills)
- [Gemini CLI skills](https://geminicli.com/docs/cli/using-agent-skills/)
- [Cursor plugins](https://prod.cursor.com/docs/plugins)
- [Vercel Skills CLI](https://github.com/vercel-labs/skills)
- [skillsync](https://github.com/Akemid/skillsync), [Windows](https://github.com/Akemid/skillsync#windows-powershell)
