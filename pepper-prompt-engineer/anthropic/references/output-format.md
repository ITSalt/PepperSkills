# Output Format — Markdown templates + JSON schema

The skill supports two output modes. **Markdown is the default** (chat-friendly with copy buttons on code blocks). JSON activates only on explicit request.

## Contents

- Mode detection
- Markdown templates
- JSON schema
- TARGET_MODEL_DISPLAY values
- Section ordering rules

---

## Mode detection

Default: **Markdown**.

JSON activates when ANY of these triggers fire:

1. **Explicit format request in the user message:**
   - EN: "output json", "in json format", "json please", "give me json", "as JSON", "--json"
   - RU: «формат json», «выдай в json», «json пожалуйста», «верни json», «как JSON»
2. **System context signals programmatic consumption** (e.g., the skill is being called via API with a structured-output config, or a wrapper system asks for machine-parseable output).

If unsure between Markdown and JSON, default to Markdown and mention in `assumptions` that the user can request JSON if they need it.

---

## Markdown templates

### Structure A. Ready (prompt is built)

Section headers translate to USER_LANG. Templates for both supported languages below.

#### Russian variant (USER_LANG = ru)

````markdown
## 🎯 Готовый промпт (для [TARGET_MODEL_DISPLAY])

```
[Full prompt text. Plain text inside the code block — no syntax language identifier. Copy-paste-ready.]
```

## ⚙️ Настройки перед использованием
- [user_instruction 1]
- [user_instruction 2]

## 💡 Что я решил за тебя
- [assumption 1]
- [assumption 2]

[OPTIONAL — include ONLY if SSoT module was embedded:]
## 📚 SSoT техника
Промпт использует String Seed of Thought для повышения разнообразия ответов. Модель будет показывать промежуточные расчёты (random_string и thinking) — это ожидаемое поведение, не баг. Финальный ответ — внутри тегов `<answer>`. Подробнее: [arXiv:2510.21150](https://arxiv.org/abs/2510.21150) (ICLR 2026).

[OPTIONAL — include ONLY if mode = "improve":]
## 🔄 Что улучшено в твоём промпте
- [improvement 1]
- [improvement 2]

---
*Если что-то поменять — скажи, переделаю.*
````

#### English variant (USER_LANG = en)

````markdown
## 🎯 Ready prompt (for [TARGET_MODEL_DISPLAY])

```
[Full prompt text]
```

## ⚙️ Setup before use
- [user_instruction 1]
- [user_instruction 2]

## 💡 Decisions I made for you
- [assumption 1]
- [assumption 2]

[OPTIONAL — if SSoT embedded:]
## 📚 SSoT technique
This prompt uses String Seed of Thought to enhance response diversity. The model will show intermediate computations (random_string and thinking) — this is expected, not a bug. Final answer sits inside `<answer>` tags. Reference: [arXiv:2510.21150](https://arxiv.org/abs/2510.21150) (ICLR 2026).

[OPTIONAL — if mode = "improve":]
## 🔄 What I improved in your prompt
- [improvement 1]
- [improvement 2]

---
*Let me know if you want adjustments.*
````

### Structure B. Clarification needed

#### Russian variant

```markdown
## 🤔 Уточни, пожалуйста

**1. [Question 1]**
- 1) [Option 1]
- 2) [Option 2]
- 3) [Option 3]
- 4) [Custom — describe]

**2. [Question 2]**
- 1) ...
- 2) ...

*Ответь номерами: 1 — ..., 2 — ..., 3 — ...*
```

#### English variant

```markdown
## 🤔 A few clarifications

**1. [Question 1]**
- 1) [Option 1]
- 2) [Option 2]
- 3) [Option 3]
- 4) [Custom — describe]

**2. [Question 2]**
- 1) ...
- 2) ...

*Reply with numbers: 1 — ..., 2 — ..., 3 — ...*
```

---

## JSON schema

When JSON mode is active, output a single valid JSON object with this exact structure:

```json
{
  "status": "clarification_needed" | "ready",
  "target_model": "claude" | "gpt" | "gemini" | "deepseek-chat" | "universal" | null,
  "clarifying_questions": [
    "Numbered question 1 (with embedded option hints)",
    "Numbered question 2"
  ],
  "prompt": "Full prompt text, ready for the user to copy",
  "user_instructions": [
    "UI setup instruction 1",
    "UI setup instruction 2"
  ],
  "assumptions": [
    "Assumption 1 with rationale"
  ],
  "useSSOT": true | false,
  "mode": "generate" | "improve"
}
```

### JSON field-filling rules

**status = "clarification_needed":**
- `clarifying_questions`: 1-3 numbered questions in USER_LANG (with option hints)
- `prompt`: `null`
- `user_instructions`: `[]`
- `assumptions`: `[]`
- `useSSOT`: `false`
- `target_model`: value if determined, else `null`
- `mode`: value if determined, else `null`

**status = "ready":**
- `prompt`: full final prompt
- `user_instructions`: array of UI hints in USER_LANG
- `assumptions`: array of decisions; `[]` if none
- `useSSOT`: `true` only if SSoT module embedded
- `target_model`: one of 5 values
- `mode`: `"generate"` or `"improve"`
- `clarifying_questions`: `[]`

### JSON output discipline

- Return EXACTLY ONE valid JSON object, nothing else
- No text before or after the JSON
- No Markdown wrappers around the JSON (` ```json ... ``` `)
- No comments inside JSON
- No trailing commas
- UTF-8 for Cyrillic and other non-ASCII

---

## TARGET_MODEL_DISPLAY values

When the section header says "for [TARGET_MODEL_DISPLAY]", use these display names:

| target_model | Display |
|---|---|
| claude | Claude |
| gpt | ChatGPT |
| gemini | Gemini |
| deepseek-chat | DeepSeek |
| universal | Universal |

---

## Section ordering rules (Markdown)

For Structure A (ready), the order is fixed:

1. Header (🎯 Готовый промпт / Ready prompt)
2. Prompt code block
3. Setup section (⚙️)
4. Decisions section (💡) — omit entirely if `assumptions` is empty
5. SSoT section (📚) — include ONLY if SSoT module embedded
6. Improvements section (🔄) — include ONLY if mode = "improve"
7. Horizontal rule `---`
8. Italic adjustment line

Deviations from this order are forbidden.

For Structure B (clarification), the order is:

1. Header (🤔)
2. Numbered questions with options
3. Italic answer template

No code blocks, no extra sections.
