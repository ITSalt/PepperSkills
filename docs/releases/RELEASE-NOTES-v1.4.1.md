# PepperSkills v1.4.1 — `pepper-ru-web-compliance` 1.0.1

Установка: пути для приложений Claude и для GPT.

## Что изменилось

**Приложения Claude.** Путь загрузки скилла в интерфейсе другой, чем был
описан: **Customize → Skills → Add → Upload skill**, а скиллам со скриптами
дополнительно нужно включённое **Settings → Capabilities → Code execution and
file creation** (на Team и Enterprise это делает администратор в *Organization
settings → Skills*). Старый путь был в обоих корневых README.

**Таблица возможностей вместо обещаний.** `INSTALL.md` теперь начинается с
того, что где работает:

| Окружение | Обход сайта | Госреестры | PDF |
|-----------|-------------|------------|-----|
| Claude Code | да | да | да |
| Claude в браузере и десктопе | нет | зависит от настроек сети | да |
| Claude API | нет | нет | да |
| GPT | нет | нет | нет |

У среды исполнения в приложениях Claude нет браузера, а сетевой доступ зависит
от настроек аккаунта, поэтому полный автоматический прогон возможен только в
Claude Code. В остальных окружениях скилл остаётся полезным: разбирает
принесённые артефакты и собирает записку — и честнее сказать это сразу, чем
отвечать потом на вопрос «почему ничего не проверилось».

**Издание для GPT** получило три конкретных пути запуска: Custom GPT
(инструкции плюс чек-лист в Knowledge), обычный ChatGPT через Custom
Instructions и вызов через API.

Архив пересобран, чтобы `INSTALL.md` внутри совпадал с репозиторием.

## Установка

- **Claude Code** — распаковать в `~/.claude/skills/pepper-ru-web-compliance`.
- **Claude в браузере и десктопе** — включить исполнение кода, скачать
  `pepper-ru-web-compliance.skill` из этого релиза, загрузить через
  *Customize → Skills → Add → Upload skill*.
- **GPT** — `openai/system-prompt.md` в Instructions, `openai/manual-checklist.md`
  в Knowledge.

Полное описание — [`anthropic/INSTALL.md`](../../pepper-ru-web-compliance/anthropic/INSTALL.md).
