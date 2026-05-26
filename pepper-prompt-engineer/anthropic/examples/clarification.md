# Example: clarification needed

## Input (user message)

> Хочу промпт для анализа конкурентов

## Trigger analysis

- Task scope is unclear (which industry? what data on hand?)
- target_model not specified
- Three critical gaps detected — bundle into one round of 3 questions

## Output (Markdown mode, USER_LANG = ru)

````markdown
## 🤔 Уточни, пожалуйста

**1. Под какую нейросеть собрать промпт?**
- 1) Claude (Opus / Sonnet)
- 2) ChatGPT (GPT-5+)
- 3) Gemini (2.5 / 3.x)
- 4) DeepSeek-Chat (V3/V4)
- 5) Universal

**2. В какой нише / индустрии конкуренты?**
- 1) SaaS / IT-продукт
- 2) E-commerce / маркетплейс-товары
- 3) Услуги (консалтинг / агентство / фриланс)
- 4) Офлайн-бизнес
- 5) Свой вариант — опиши

**3. Что на входе для анализа?**
- 1) Список сайтов конкурентов (URL)
- 2) Скриншоты / выгрузки уже собрал руками
- 3) Только названия конкурентов — найди ты
- 4) Ничего, нужен общий шаблон вопросов для самостоятельного анализа

*Ответь номерами: 1 — ..., 2 — ..., 3 — ...*
````

## Why these questions

- **Q1 target_model:** unavoidable — without it, formatting decisions cannot be made
- **Q2 industry:** changes ROLE assignment (B2B SaaS vs e-commerce vs services have very different competitor-analysis frameworks)
- **Q3 input data:** changes whether to include fact-checking module, web search instructions, or pure templating

## Why NOT these questions

- ❌ "What role should I assign?" — strategy says decide yourself; ROLE will follow from Q2
- ❌ "What tone?" — pick by domain
- ❌ "How many competitors?" — reasonable default (5-7) can go into assumptions
- ❌ "What output format?" — table format is logical default for competitor analysis
- ❌ "Quantitative or qualitative analysis?" — both, by default; user can narrow later

## Multi-turn continuation

After user replies (e.g., "1 - Claude, 2 - SaaS, 3 - 1, у меня список из 5 URL"):

- The skill recognizes Case B (previous response was clarification) per Step 0a
- Combines original request + answers
- Jumps to Step 4 of workflow (reasoning mode selection)
- Builds the ready prompt without re-asking
