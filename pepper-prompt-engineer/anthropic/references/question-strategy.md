# Question-Asking Strategy

The single rule: **fill in as much as possible yourself.** Ask only what is impossible to assume reasonably.

This document defines:
- Critical-gap criteria (when to ask)
- Decide-yourself criteria (when to log an assumption instead)
- How to phrase questions (when one is unavoidable)
- Forbidden questions (categories the agent must never ask)

## Contents

- Why this matters
- Critical gaps — ask
- Decide yourself — log assumption
- How to ask
- Forbidden questions
- Golden rule

---

## Why this matters

Two failure modes plague prompt-engineering agents:

1. **Asking too much** — the user feels interrogated and gives up. The agent looks unhelpful.
2. **Assuming too much** — the agent guesses wrong on a critical detail (e.g., target model) and produces a misaligned prompt.

The skill's policy: **err strongly toward filling in defaults yourself**, ask only critical questions, give option hints in every question so the user can answer with a number.

A typical good interaction has zero questions. The agent picks role, tone, format, length, and stack defaults silently, logs them in `assumptions`, and produces the prompt. The user reads the assumptions and either accepts or asks to change specifics.

---

## Critical gaps — ASK

A gap is critical only if it would fundamentally change the deliverable AND has no reasonable default. There are exactly five categories:

### 1. Task is fundamentally unclear — no deliverable

Examples:
- "help with the project"
- "do something analytical"
- "advise me"
- «помоги»
- «сделай что-нибудь»

These contain no actionable noun. Ask: what is the deliverable?

### 2. target_model not determined

The user did not specify a target model and it cannot be inferred from context. Always ask:

```
Под какую нейросеть собрать промпт? / Which AI model is the prompt for?
1) Claude (Opus / Sonnet)
2) ChatGPT (GPT-5+)
3) Gemini (2.5 / 3.x)
4) DeepSeek-Chat (V3/V4)
5) Universal (one prompt for any of the above)
```

### 3. Mega-task trigger fired

See `scope-check.md`. Output the warning with 3 options.

### 4. Request references nonexistent data

Examples:
- "describe my company" — which one?
- "analyze my code" — which code?
- «по моему ТЗ» — where's the brief?

The agent has no way to invent the referenced data. Ask for the data itself, or ask the user to paste/describe it.

### 5. Explicitly conflicting requirements

Examples:
- "make a one-line detailed report"
- "concise but exhaustive"
- "creative but only follow the template exactly"

These cannot be resolved by an assumption — the conflict is intrinsic. Ask which side wins.

---

## Decide yourself — LOG ASSUMPTION

Everything below has a reasonable default. The skill picks the default, logs it in the `assumptions` field, and proceeds without asking. The user can override later if needed.

| Element | Default decision rule |
|---|---|
| **Model role** | Pick the most relevant senior role for the domain. Examples: code → "senior Python developer" / "senior TypeScript developer" / "senior backend engineer"; marketing → "senior copywriter for [vertical]"; analytics → "expert market analyst"; UX → "experienced UX writer"; data → "senior data analyst with SQL/Python expertise" |
| **Tone & style** | Match task type. Code = technical-concise. Marketing = energetic-benefit-led. Analytics = formal-structured. Legal = precise-cautious. Creative writing = match the requested genre. |
| **Default tech stack** | Pick the most popular for the domain. Python for scripts/parsing/ML/data. TypeScript for frontend. PostgreSQL for relational DB. Node.js for general backend. React/Next.js for web UI. |
| **Output length** | Match task type. Email = 80-150 words. Blog post = 800-1500 words. Code = unbounded by length, bounded by completeness. Analysis = sectioned with 200-400 per section. |
| **Output format inside the prompt** | Pick the most logical for the deliverable. Marketing copy = Markdown. Data export = JSON. Comparisons = table. Code = code block. Long-form = Markdown. |
| **Success criteria** | Formulate yourself from the task: 3-5 measurable items. Use the methodology rule: each criterion must be objectively verifiable. |
| **Whether to include few-shot examples** | Include if format is unusual or style is hard to describe. Skip if format is fully specified and stylistically standard. |
| **Addressing form** | RU → "ты" by default. EN → "you" always. Override if context implies formal ("for legal department" → "вы"). |

---

## How to ask

When a question is genuinely needed, apply these rules:

1. **Maximum 3 questions per round.** If you have more, pick the 3 most critical and ask the rest after answers come back.

2. **Numbered questions.** Each question gets a number.

3. **Always provide option hints (1/2/3/4).** Closed questions with options are easier to answer than open-ended questions.

   ❌ Bad: "What's the target audience?"

   ✅ Good:
   ```
   Target audience:
   1) domain specialists
   2) non-pro customers
   3) internal team
   4) custom — describe
   ```

4. **Include "custom — describe" as a last option** when the closed options might not cover the user's case.

5. **End with a single-line answer template:** "Reply with numbers: 1 — ..., 2 — ..."

### Good multi-question example

```
🤔 Уточни, пожалуйста

1. Под какую нейросеть собрать промпт?
   1) Claude
   2) ChatGPT
   3) Gemini
   4) DeepSeek-Chat
   5) Universal

2. В какой нише конкуренты?
   1) SaaS / IT-продукт
   2) E-commerce
   3) Услуги
   4) Офлайн-бизнес
   5) Свой вариант — опиши

3. Что на входе?
   1) Список URL
   2) Скриншоты / выгрузки
   3) Только названия — найди ты
   4) Ничего, нужен общий шаблон

Ответь номерами: 1 — ..., 2 — ..., 3 — ...
```

---

## Forbidden questions

The skill MUST NOT ask these — they violate the strategy:

- ❌ "What role should I assign the model?" — pick the most domain-relevant senior role yourself
- ❌ "What tone / style?" — choose by task type
- ❌ "How many words / characters?" — choose by task type
- ❌ "What success criteria?" — formulate yourself
- ❌ "What output format?" — choose by task type
- ❌ "What technologies / framework?" — pick the most popular stack for the domain, log in assumptions
- ❌ "Do you want examples in the prompt?" — decide by complexity
- ❌ "Should I use Markdown or XML?" — decided by target_model (see `target-models.md`)
- ❌ Any question the user themselves likely doesn't know the answer to

If the user actively wants to override one of these decisions, they will say so in their initial request or after seeing the assumptions.

---

## Golden rule

**If you can suggest a reasonable default — take it via `assumptions`, don't ask.**

The user trusts the agent to make sensible choices. Documenting those choices in `assumptions` gives the user transparency and the option to push back. Asking for every decision is interrogation, not engineering.
