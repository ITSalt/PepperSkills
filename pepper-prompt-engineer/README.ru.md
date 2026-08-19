# `pepper-prompt-engineer` — CRAFT+ Prompt Engineer

Портативный скилл по промпт-инжинирингу: превращает любое описание задачи в production-ready промпт под конкретную модель по методологии **CRAFT+** (классический CRAFT, расширенный блоками success criteria, conditional modules, verification и полировкой под целевую модель).

Источники методологии: Anthropic *Prompting best practices* и *Skill authoring best practices*, OpenAI *Prompt engineering* guide и GPT-5 prompting guide, Google *Gemini 3 Developer Guide*, документация DeepSeek API, Misaki & Akiba — [String Seed of Thought](https://arxiv.org/abs/2510.21150) (ICLR 2026). Какое поколение моделей покрывает каждый источник — записано в [`anthropic/references/target-models.md`](./anthropic/references/target-models.md), единственном файле скилла с версионно-зависимыми фактами.

## Какую проблему решает

Промпты «на коленке» недоформулируют критерии успеха, забывают форматирование под целевую модель (Claude → XML / GPT → Markdown плюс XML / Gemini → лаконичный Markdown / DeepSeek → любой) и пропускают conditional modules (факт-чекинг, исполнение кода, SSoT-разнообразие, мульти-модальность). Скилл упаковывает рабочий процесс senior prompt engineer в одного агента, который:

- определяет целевую модель, классифицирует задачу, задаёт максимум 3 критичных уточнения;
- собирает 10 CRAFT+ блоков (role, task, context, success criteria, actions, constraints, reasoning mode, output format, examples, verification);
- по двуязычным (RU+EN) триггерам встраивает модули факт-чекинга / исполнения кода / SSoT / мульти-модального ввода;
- полирует форматирование под выбранную модель;
- выдаёт настройку глубины размышления под выбранную модель — самый сильный рычаг качества, который живёт вне текста промпта;
- прогоняет результат через 14-пунктный self-check, плюс опциональный программный валидатор.

## Два режима поставки

| Режим | Когда применять | Где |
|-------|-----------------|-----|
| **Универсальный chat-промпт** | Один раз вставил — работает в Claude.ai Projects, ChatGPT Custom GPT, Gemini Gem, DeepSeek chat | [`chat-prompt.md`](./chat-prompt.md) |
| **Claude Code скилл** | Полный набор: references, примеры, программный валидатор, evals | [`anthropic/SKILL.md`](./anthropic/SKILL.md) |

Под капотом — одна и та же CRAFT+ методология, причём буквально: `chat-prompt.md` генерируется из исходников скилла скриптом `scripts/build-chat-prompt.py`, поэтому два издания не могут разойтись. Chat-режим даёт минимальное трение (одна вставка, работает в любом chat UI); скилл — повторяемое использование внутри Claude Code с авто-подгрузкой references.

## Выбери платформу

| Платформа | Файл |
|-----------|------|
| Любой чат (Claude.ai / ChatGPT / Gemini / DeepSeek) — вставить как system-сообщение | [`chat-prompt.md`](./chat-prompt.md) |
| Claude Code — установить как скилл (один файл) | [`pepper-prompt-engineer.skill`](./pepper-prompt-engineer.skill) |
| Claude Code — установить как скилл (предварительно посмотреть файлы) | [`anthropic/SKILL.md`](./anthropic/SKILL.md) + [`anthropic/INSTALL.md`](./anthropic/INSTALL.md) |

## Как пользоваться chat-промптом

1. Открой чат с любой frontier-моделью (Claude.ai, ChatGPT, Gemini, DeepSeek).
2. Скопируй блок из [`chat-prompt.md`](./chat-prompt.md) и отправь **первым** сообщением.
3. Дождись двуязычного приветствия — агент **не** обрабатывает мастер-промпт как задачу.
4. Опиши задачу, например: *«собери промпт под Claude для парсинга телеграм-каналов на Python»*. Если сразу указать целевую модель — пропустишь раунд уточнений.
5. Получишь готовый промпт в code-блоке с кнопкой Copy. Вставь в новый чат с целевой моделью.

**Совет — постоянная установка.** В Claude.ai создай Project с промптом в поле System Prompt; в ChatGPT — Custom GPT с этим текстом в Instructions; в Gemini — Gem. Приветствие при chat-активации не сработает (нет первого user-сообщения с мастер-промптом), и агент сразу начнёт обрабатывать задачи.

## Как установить Claude Code скилл

Два пути — выбери удобный:

- **Один файл:** скачай [`pepper-prompt-engineer.skill`](./pepper-prompt-engineer.skill) и установи как Claude Code скилл.
- **Сначала посмотреть:** прочитай [`anthropic/SKILL.md`](./anthropic/SKILL.md) и сопровождающие файлы в [`anthropic/`](./anthropic/), потом следуй пошаговой инструкции в [`anthropic/INSTALL.md`](./anthropic/INSTALL.md).

В обоих случаях получаешь один набор файлов: SKILL.md, INSTALL.md, 7 references, 6 примеров, валидатор и раннер evals с README к ним, набор сценариев evals.

## Когда НЕ использовать

Скилл **не** предназначен для прямого выполнения задачи пользователя — он строит промпты для других сессий. Активация — только по явным триггерам построения промпта (RU: «собери промпт», «улучши промпт» / EN: «build a prompt», «improve this prompt»). Для обычного выполнения задач — пусть базовая модель отрабатывает запрос напрямую.

## Версии документации

- English — [`README.md`](./README.md)
- Русский — этот файл

## Лицензия

[MIT](../LICENSE) © ITSalt.
