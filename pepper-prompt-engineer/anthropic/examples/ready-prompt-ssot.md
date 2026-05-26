# Example: ready prompt with SSoT module active

## Input (user message)

> 10 разных слоганов для кофейни в стиле slow life. Под GPT.

## Trigger analysis

- N>1 distinct variants of same type → SSoT trigger fires
- target_model = "gpt" → Markdown headers format
- Domain: creative copywriting → role pick handled by strategy
- `useSSOT = true` in this output

## Output (Markdown mode, USER_LANG = ru)

````markdown
## 🎯 Готовый промпт (для ChatGPT)

```
Respond to the user in Russian. If you need to ask for clarifications, ask them in Russian.

# Role
You are a senior copywriter specializing in lifestyle brand voice for independent coffee shops. Your audience: founders / brand managers of small coffee shops, age 25-40, who care about distinctive identity over generic taglines.

# Task
Generate 10 distinct slogans for a slow-life-themed coffee shop.

# Context
"Slow life" positioning rejects hustle culture. The audience wants slogans that feel calm, deliberate, slightly poetic — not corporate, not trendy. Slogans will appear on signage, social media bios, and printed materials.

# Success Criteria
- Exactly 10 slogans
- Each ≤ 8 words (signage-friendly)
- Each slogan distinctly different in mood / structure (no repetition of "moment", "pause", "slow" as the dominant noun across multiple slogans)
- Russian-language slogans (target audience reads Russian)
- No clichés: "best coffee in town", "your daily dose of caffeine", "wake up and smell"

# Actions
1. For each of the 10 slogans, run the creativity protocol below to ensure genuine diversity
2. After all 10 generated, scan for repetition; if 2 slogans share dominant noun or structure, regenerate the second one

# Constraints
- No exclamation marks
- No imperative verbs as openings ("Drink", "Try", "Order")
- Stay in Russian even if tempted to drop in English words
- If you lack data to complete the task: state explicitly what is missing and ask ONE clarifying question. Do not fabricate facts.

# Reasoning Mode
Direct.

# Creativity Protocol
<creativity_protocol>
For each independent variant required, follow this protocol to ensure genuine diversity (bypasses RLHF mode collapse — Misaki & Akiba, ICLR 2026):

Step 1. Generate a fresh random string (16+ chars: mix uppercase letters, lowercase letters, digits, symbols) inside <random_string>...</random_string>. Generate internally — do NOT call external tools.

Step 2. Derive the variant deterministically inside <thinking>...</thinking>:
- Uniform choice among N options: result = sum(ord(c) for c in string) mod N
- Weighted distribution: rolling hash h = 0; for c in string: h = (h*31 + ord(c)) mod 10000; split [0, 10000) into intervals proportional to target weights; pick interval containing h
- Creative composition: split string into 2-5 non-overlapping segments; for each segment pick one component (setting / tone / character / twist / mood / etc.) from a candidate list via Sum-Mod; assemble

Step 3. Output ONLY the final variant inside <answer>...</answer>. No commentary.

Show all arithmetic explicitly. Generate a NEW string for EACH independent decision — reusing strings destroys statistical independence.
</creativity_protocol>

For this task, decompose each slogan into 4 dimensions for SSoT composition:
- Dimension 1 (mood): contemplative / warm / minimalist / wistful / playful
- Dimension 2 (focal noun): moment, light, silence, breath, page, route, table, window
- Dimension 3 (structure): 2-word / 3-word phrase / sentence fragment / nominal phrase
- Dimension 4 (rhythm): single stress / dual stress / flowing / abrupt

# Output Format
Output 10 numbered slogans. For each, show the random_string and thinking blocks as required by the creativity protocol, then the slogan inside <answer> tags.

Final list at the end: just the 10 slogans, numbered, in a clean block (no protocol traces).

# Verification
Before producing the final list:
- [ ] 10 slogans total
- [ ] Each ≤ 8 words
- [ ] Different dominant noun across the set
- [ ] No banned clichés present
- [ ] All in Russian
- [ ] Each generated through fresh random_string (not pattern-matched)
```

## ⚙️ Настройки перед использованием
- Дополнительных настроек не требуется — модель отработает промпт как есть
- Этот промпт использует технику SSoT для повышения разнообразия ответов. Модель будет показывать промежуточные расчёты (random_string и thinking) — это ожидаемое поведение, не баг. Финальный ответ — внутри тегов `<answer>`.

## 💡 Что я решил за тебя
- Принял роль "senior copywriter, lifestyle brand voice for independent coffee shops"
- Длина слогана ≤ 8 слов — типичный размер для signage
- Декомпозиция SSoT по 4 осям (mood / focal noun / structure / rhythm) — для разнообразия по нескольким измерениям, не только по одному
- 5 запрещённых клише — измеримые границы вкуса
- Reasoning mode: Direct + протокол SSoT внутри Actions

## 📚 SSoT техника
Промпт использует String Seed of Thought для повышения разнообразия. Модель будет показывать промежуточные расчёты (random_string и thinking) — это ожидаемое поведение, не баг. Финальный ответ — внутри тегов `<answer>`. Подробнее: [arXiv:2510.21150](https://arxiv.org/abs/2510.21150) (ICLR 2026).

---
*Если что-то поменять — скажи, переделаю.*
````

## Why this works

- SSoT trigger correctly identified (N=10 distinct variants of same type)
- Creativity protocol embedded with full text inside `<creativity_protocol>` tags
- Task-specific decomposition into 4 dimensions added in the prompt — guides the SSoT process toward genuinely orthogonal variation axes
- Verification includes "Each generated through fresh random_string (not pattern-matched)" — directly checks the SSoT compliance
- "📚 SSoT техника" visible section present with arXiv link
- All other 10 CRAFT+ blocks intact
