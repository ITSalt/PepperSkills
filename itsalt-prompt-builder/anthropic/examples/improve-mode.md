# Example: mode = improve

## Input (user message)

> Improve this prompt for GPT: "Write a LinkedIn post about AI. Make it good and interesting."

## Trigger analysis

- "Improve this prompt" — explicit `mode = "improve"` trigger
- target_model = "gpt" (explicit)
- Existing prompt to rewrite, not new task from scratch

## Detected weaknesses in the existing prompt

The skill parses the existing prompt against CRAFT+ and finds:

| Block | Status | Issue |
|---|---|---|
| ROLE | Missing | No role assigned |
| TASK | Vague | "Write a LinkedIn post about AI" — too broad |
| CONTEXT | Missing | No audience, no channel context |
| SUCCESS_CRITERIA | Vague | "Good and interesting" — not measurable |
| ACTIONS | Missing | No procedural guidance |
| CONSTRAINTS | Missing | No exclusions, no uncertainty rule |
| REASONING_MODE | Missing | Implicit Direct, but not stated |
| OUTPUT_FORMAT | Missing | No structure specified |
| EXAMPLES | Missing | No examples |
| VERIFICATION | Missing | No self-check |

Score: 1/10 blocks adequately filled.

## Output (Markdown mode, USER_LANG = en)

````markdown
## 🎯 Ready prompt (for ChatGPT)

```
Respond to the user in English. If you need to ask for clarifications, ask them in English.

# Persistence
Keep working until the user's request is fully resolved. Verify against the success criteria before finalizing.

# Role
You are a senior LinkedIn content strategist with 8+ years of experience writing for tech audiences. Your audience: LinkedIn users in tech (product, engineering, founder, investor roles) who scroll fast and reward concrete insight over hype.

# Task
Write one LinkedIn post about an AI topic the user specifies.

# Context
LinkedIn 2026 algorithm rewards hooks within the first 3 lines (the "see more" cutoff), specificity over generality, and 1200-1800 character posts with strong dwell time. Tech LinkedIn audience is saturated with AI content — only specific, contrarian, or data-driven takes break through.

# Success Criteria
- Hook is in line 1, stops scroll without clickbait
- Total length 1200-1800 characters
- At least one specific number, name, or example (not just abstractions)
- One concrete CTA at the end (comment prompt, link, or DM invitation)
- ≤ 2 emoji total

# Actions
1. Read the AI topic from the user's input
2. Identify the most counter-intuitive or specific angle on the topic
3. Draft a 1-line hook
4. Develop 3 main points: setup → insight → implication
5. Write CTA matching the post's goal
6. Tighten language: cut generic adjectives, replace clichés with concrete nouns

# Constraints
- Do NOT use "excited to share", "thrilled to announce", "AI is changing everything"
- Do NOT use generic adjectives ("amazing", "incredible", "game-changing", "powerful")
- Do NOT structure as a numbered list — write in flowing paragraphs
- If you lack data to complete the task (e.g., user didn't specify the AI topic): state explicitly what is missing and ask ONE clarifying question. Do not fabricate facts.

# Reasoning Mode
Direct.

# Output Format
Return only the post text formatted as it should appear on LinkedIn (line breaks preserved). No meta-commentary, no "Here's your post:".

# Verification
Before outputting, verify:
- [ ] Hook in line 1 (~200 chars max)
- [ ] Total length 1200-1800 chars
- [ ] At least one specific number/name/example present
- [ ] One CTA at the end
- [ ] ≤ 2 emoji
- [ ] No banned clichés present
- [ ] Flowing paragraphs (not numbered list)
```

## ⚙️ Setup before use
- Paste this prompt into a ChatGPT chat
- In the next message, specify the AI topic (e.g., "fine-tuning vs RAG tradeoffs", "the cost curve of frontier models", "what 2026 multimodal means for product teams")
- No Web Search or Code Interpreter needed unless the topic involves recent events

## 💡 Decisions I made for you
- Took role "senior LinkedIn content strategist for tech audiences" — best for the AI topic domain
- Length 1200-1800 chars (LinkedIn 2026 algorithm sweet spot)
- Added "# Persistence" header per OpenAI Cookbook recommendation
- Banned 7 specific phrases that tank engagement
- Required at least one specific number/name/example — converts "good and interesting" into a measurable criterion

## 🔄 What I improved in your prompt
- **Added ROLE** with concrete expertise and audience — was missing
- **Specified TASK** from "AI post" to "AI post on a user-specified topic" — clarified that the topic is an input, not the prompt
- **Added CONTEXT** about LinkedIn 2026 algorithm and tech audience saturation
- **Replaced "good and interesting"** with 5 measurable success criteria (length, hook position, specificity requirement, CTA, emoji limit)
- **Added 6 procedural ACTIONS** to guide the writing process
- **Added CONSTRAINTS** with specific banned phrases (7 of them) and the uncertainty rule
- **Specified OUTPUT_FORMAT** explicitly — flowing paragraphs, not list
- **Added VERIFICATION checklist** mirroring success criteria

---
*Let me know if you want adjustments.*
````

## Why this works

- Full CRAFT+ rewrite — all 10 blocks now present where 9 were missing
- "🔄 What I improved" section explicitly shows the user what changed (transparency)
- Each improvement is concrete (number of phrases banned, specific length range), not vague ("made it better")
- Original task intent preserved (LinkedIn post about AI) — the rewrite doesn't change what the user wanted, only how it's specified
