# Scope Check — Mega-Task Detection

Some user requests describe deliverables that cannot fit in a single prompt — multi-subsystem projects, vague "make it like Google's", or content volumes exceeding model output limits. The skill warns the user and lets them choose how to proceed.

## Triggers (any one)

1. **Multiple unrelated subsystems** named in the same request
   - "CRM + analytics + billing"
   - "app with auth, chat, and payments"
   - "platform with marketplace, payments, and admin panel"

2. **Vague scope without a concrete deliverable**
   - "make it like Google's"
   - "full-fledged system"
   - "entire platform"
   - "комплексное решение"
   - «целая экосистема»

3. **Output volume physically doesn't fit one response**
   - >10000 words of code
   - >50 pages of text
   - Hundreds of items to generate

## On trigger → output clarification

Set `status = "clarification_needed"` (Markdown: Structure B; JSON: standard schema).

`clarifying_questions` contains exactly ONE warning question with 3 numbered options.

### Russian template

```
Эта задача похожа на мега-проект (несколько подсистем / размытый scope). Один промпт даст поверхностный результат. Варианты:
1) Собрать промпт на упрощённую MVP-версию — напиши, что критично из всего объёма
2) Не собирать сейчас — ты разобьёшь задачу на этапы и вернёшься с узкими подзадачами
3) Всё равно собрать промпт на всю задачу как описано — понимаю риски

Ответь номером (1 / 2 / 3), при выборе 1 — кратким уточнением scope.
```

### English template

```
This task looks like a mega-project (multiple subsystems / vague scope). One prompt will produce a shallow result. Options:
1) Build a prompt for a simplified MVP version — describe what's critical from the entire scope
2) Don't build now — you'll split the task into stages and return with narrower subtasks
3) Build the prompt for the full task as described — I understand the risks

Reply with a number (1 / 2 / 3); for option 1 — briefly clarify scope.
```

## User response handling

### If user chose option 1 (MVP)

Proceed with the workflow using the narrowed MVP scope. Log in `assumptions` what was de-scoped: "Сужен scope с [original] до [MVP] согласно выбору пользователя." / "Scope narrowed from [original] to [MVP] per user choice."

### If user chose option 2 (don't build)

Acknowledge briefly and exit. Don't push back.

### If user chose option 3 (build anyway)

Comply. Build the prompt for the full task. Add to `assumptions`:
- **RU:** "Пользователь сознательно выбрал собрать промпт на мега-задачу несмотря на предупреждение о возможной поверхностности результата."
- **EN:** "User consciously chose to build a prompt for a mega-task despite the warning about possibly shallow results."

## Why this matters

Building a single prompt for a mega-task produces vague high-level output that doesn't actually help the user implement anything. The warning protects the user from wasting their time and the executing model's tokens on a known-failed approach.

But: the user owns the decision. If they want to try anyway, comply — possibly they have context the skill doesn't (e.g., they want a high-level architecture sketch, not implementation).

## Out of scope

**Full mega-task decomposition** — splitting a mega-task into a sequence of narrower prompts with handoff points — is a separate concern. Not this skill's job. The user can build a separate "task decomposer" skill or do it manually.
