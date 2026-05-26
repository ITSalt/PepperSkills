# CRAFT+ Methodology — full block specification

This document defines the 10 semantic blocks of the CRAFT+ prompt. The skill assembles every prompt using these blocks (target-model formatting from `target-models.md` determines the syntactic wrapper — XML, Markdown headers, or hybrid).

## Contents

- 1. ROLE
- 2. TASK
- 3. CONTEXT
- 4. SUCCESS_CRITERIA
- 5. ACTIONS
- 6. CONSTRAINTS
- 7. REASONING_MODE
- 8. OUTPUT_FORMAT
- 9. EXAMPLES
- 10. VERIFICATION
- Block skipping rules
- The uncertainty rule

---

## 1. ROLE

**What:** Who the model should act as — role title, expertise level, and target audience for the output.

**Pattern:**
```
You are a [role title] with [N+ years / specific credentials] in [domain].
Your audience: [who will consume the output].
```

**Good example:**
> You are a senior e-commerce copywriter with 10+ years of experience writing for Russian marketplaces (Wildberries, Ozon). Your audience: Russian-speaking mothers aged 25-35 making purchase decisions for their children's clothing.

**Bad example:**
> You are a helpful assistant. (Too generic — provides no behavioral steering.)

**Decision criteria for the skill:** pick the most domain-relevant senior role automatically; do not ask the user.

---

## 2. TASK

**What:** What exactly the model should do, as a single imperative sentence.

**Pattern:**
```
[Verb] [object] [qualifier].
```

**Good example:**
> Generate marketplace product descriptions for children's clothing items.

**Bad example:**
> Help with descriptions. (Vague — no clear deliverable.)

**Rule:** one task per prompt. If the user request implies multiple tasks, either (a) merge them if they're sequential parts of one deliverable, or (b) trigger scope check (`scope-check.md`).

---

## 3. CONTEXT

**What:** Background information the executing model needs — input data description, domain knowledge, situational facts.

**Critical anti-pattern:** do NOT paraphrase the user's request to the agent ("User wants product descriptions"). Describe the task essence for the executing model ("Descriptions display on Wildberries product cards. Russian mothers 25-35 are primary readers...").

**Length:** 1-4 sentences. If longer is needed, use bullet structure.

---

## 4. SUCCESS_CRITERIA

**What:** 3-5 measurable criteria for "done and good". Each criterion must be objectively verifiable.

**Pattern:** bullet list of measurable items.

**Good criteria:**
- Title is under 60 characters
- 5 bullet points present
- Each bullet ≤ 80 characters
- No exclamation marks
- Cites at least 2 authoritative sources

**Bad criteria (forbidden):**
- Written well
- Engaging tone
- Quality output
- Reads naturally

**Rule:** if you cannot write a test that programmatically distinguishes pass from fail, the criterion is too vague — rewrite it.

---

## 5. ACTIONS

**What:** Numbered procedural steps the executing model should follow.

**When to include:** task is moderate or complex (multi-step reasoning, transformations, structured generation).

**When to skip:** simple one-step tasks where the action is obvious from TASK + OUTPUT_FORMAT.

**Pattern:** numbered list of imperative steps, each one action.

**Good example:**
```
1. Read product details from user input
2. Identify the top emotional benefit for the target audience
3. Write title with primary keyword + benefit
4. Write 5 bullets ordered: safety → comfort → durability → versatility → value
```

---

## 6. CONSTRAINTS

**What:** What NOT to do, scope boundaries, exclusions, and the mandatory uncertainty rule.

**Sections in this block:**

### Negative instructions
What to avoid: forbidden words, banned formats, prohibited tones.

### Scope
What is in scope and what is out of scope for this prompt.

### Uncertainty rule (MANDATORY)

Always embed:
```
If you lack data to complete the task: state explicitly what is missing and ask ONE clarifying question. Do not fabricate facts.
```

This anti-hallucination clause is non-negotiable.

### Conflicting requirements

If success criteria contain potentially conflicting requirements (e.g., "concise" + "comprehensive"), resolve by priority:
```
Priority 1: [requirement A]
Priority 2: [requirement B if A is satisfied]
```

---

## 7. REASONING_MODE

**What:** Explicit signal of how the executing model should think.

**Options:**

- **Direct** — for simple unambiguous tasks; no special signal needed
- **Chain-of-Thought** — multi-step reasoning. ⚠️ ONLY add to the prompt for `target_model = deepseek-chat`. Claude 4.6+, GPT-5+, and Gemini Deep Think do CoT internally via API params; explicit "think step by step" is redundant or harmful.
- **Tree-of-Thoughts** — explore multiple solution paths in parallel, then converge
- **ReAct** — Thought → Action → Observation loop for tool use
- **Self-Consistency** — generate N independent reasoning paths, then vote/aggregate; use for high-stakes (medicine, finance, security)

**Pattern (when adding CoT for DeepSeek):**
```
Reasoning mode: Chain-of-Thought.
Before producing the final answer, decompose the task into sub-steps in a <thinking> block, then output the answer in an <answer> block.
```

**Pattern (when not adding explicit reasoning, e.g., Direct):**
The REASONING_MODE block can be a single line: `Reasoning mode: Direct.`

---

## 8. OUTPUT_FORMAT

**What:** Exact structure of the executing model's output — sections, length, tone, format type (Markdown / JSON / plaintext / table / code).

**Pattern:** specify the literal template.

**Good example:**
```
Return in this exact structure:

TITLE: [text, ≤60 chars]

BULLETS:
• [bullet 1]
• [bullet 2]
...
```

**Anti-pattern:** vague format hints like "in a clean format" — replace with literal templates.

**Length guidance:** specify in characters / words / pages / bullets, not "short" or "detailed".

---

## 9. EXAMPLES

**What:** 1-3 few-shot examples showing input → output mapping.

**When to include:**
- Format is unusual or specific
- Style/tone is hard to describe in words but easy to demonstrate
- Edge cases need illustration

**When to skip:**
- Format is fully specified in OUTPUT_FORMAT
- Examples would be longer than the task itself
- You're unsure the example is correct (mock examples are worse than none)

**Rule:** maximum 3 examples. Many-shot (8-12) used to be recommended in 2023-2024, but on frontier reasoning models 2026 it causes context degradation past ~3000 tokens. Stay lean.

---

## 10. VERIFICATION

**What:** A 3-5-item checklist the executing model runs before outputting.

**Pattern:** checkbox list mirroring the SUCCESS_CRITERIA.

**Good example:**
```
Before outputting, verify:
- [ ] Title ≤ 60 chars
- [ ] Each bullet ≤ 80 chars
- [ ] All 5 bullets start with a benefit verb
- [ ] No exclamation marks
```

**Effect:** measurable improvement in compliance on frontier models — the executing model treats the checklist as a stop-gate before producing output.

---

## Block skipping rules

Only **ACTIONS** and **EXAMPLES** may be skipped — and only when:

- **ACTIONS:** task is simple/atomic (single-step), and the action is obvious from TASK + OUTPUT_FORMAT
- **EXAMPLES:** format is fully specified in OUTPUT_FORMAT and no stylistic ambiguity remains

All other blocks (ROLE, TASK, CONTEXT, SUCCESS_CRITERIA, CONSTRAINTS, REASONING_MODE, OUTPUT_FORMAT, VERIFICATION) are mandatory in every prompt. A minimally-filled block is acceptable; a removed block is not.

---

## The uncertainty rule (recap)

Always present in CONSTRAINTS, verbatim:

```
If you lack data to complete the task: state explicitly what is missing and ask ONE clarifying question. Do not fabricate facts.
```

This single sentence reduces hallucination rates measurably across frontier models. It is part of the CRAFT+ contract, not a stylistic choice.
