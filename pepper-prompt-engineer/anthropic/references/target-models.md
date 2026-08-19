# Target-Model Formatting

After assembling the 10 CRAFT+ blocks + active conditional modules (Steps 5-6 of the
workflow), Step 7 polishes the prompt for the chosen target_model.

> **This file is the single source of truth for anything version-dependent.**
> Model generations, API parameter names, identifiers, and UI paths live here and
> nowhere else in the skill. Every other file refers to this one instead of naming a
> model version. When a vendor ships a new generation, this file is the only edit.

## Contents

- Current generations
- Display names
- Reasoning control (applies to every target)
- Formatting rules per target: claude / gpt / gemini / deepseek / universal
- Quick comparison
- Decision when target_model = "universal"
- Old patterns

---

## Current generations

| target_model | Family | Notable members |
|---|---|---|
| claude | Claude 5 | Fable 5, Mythos 5, Opus 5, Sonnet 5; Opus 4.8/4.7/4.6, Sonnet 4.6, Haiku 4.5 still current |
| gpt | GPT-5.6 | Sol (flagship), Terra (balanced), Luna (fast) |
| gemini | Gemini 3.x | current docs reference 3.1 Pro and 3.5 Flash |
| deepseek | DeepSeek V4 | `deepseek-v4-pro`, `deepseek-v4-flash` |
| universal | — | targets the intersection of the four above |

Vendor references: Anthropic keeps one living page, *Prompting best practices*, plus a
per-model page for each new generation. OpenAI: *Prompt engineering* guide and the GPT-5
prompting guide in the Cookbook. Google: *Gemini 3 Developer Guide*. DeepSeek: API docs
changelog.

## Display names

When showing the chosen target in the output's section header:

| target_model | Display name |
|---|---|
| claude | Claude |
| gpt | ChatGPT |
| gemini | Gemini |
| deepseek | DeepSeek |
| universal | Universal |

---

## Reasoning control (applies to every target)

All four vendors now expose a user-settable reasoning-depth control. This is the single
highest-leverage setting available to the user, and it lives **outside** the prompt text —
so it must be surfaced as a `user_instruction`, not embedded in the prompt.

**Every ready output includes one reasoning-depth line in the ⚙️ setup section.** Phrase it
mechanism-first, with the concrete path in parentheses, so the line survives a UI change.

| target_model | Mechanism | RU | EN |
|---|---|---|---|
| claude | Adaptive thinking (on by default on current models); depth follows the `effort` parameter on the API | Для сложной задачи выбери режим с расширенным мышлением или подними `effort` (на API — `thinking: {type: "adaptive"}` + `effort`). | For a complex task pick the extended-thinking mode or raise `effort` (on the API — `thinking: {type: "adaptive"}` plus `effort`). |
| gpt | `reasoning_effort`: low / medium (default) / high, plus a minimal tier | Для сложной задачи включи режим рассуждения или подними `reasoning_effort` до `high`. | For a complex task switch to a thinking mode or raise `reasoning_effort` to `high`. |
| gemini | `thinking_level` | Для сложной задачи выстави `thinking_level: "high"` вместо усложнения промпта. | For a complex task set `thinking_level: "high"` rather than complicating the prompt. |
| deepseek | Thinking effort: low / high / max | Для сложной задачи подними уровень thinking-усилия (low / high / max). | For a complex task raise the thinking effort level (low / high / max). |
| universal | Varies by client | Если интерфейс даёт выбор глубины размышления — для сложной задачи включи максимальную. | If your interface exposes a reasoning-depth control, set it high for a complex task. |

**Corollary — do not inject "think step by step".** Every target above reasons internally
when its control is engaged; an explicit decomposition instruction competes with that and
adds tokens without adding depth. Set the control instead. This applies to all five
targets, `deepseek` included — the V4 generation has its own thinking modes, unlike the
retired chat model this skill used to target.

---

## Formatting rules per target

### claude

- **Block wrapping:** XML tags for every CRAFT+ block: `<role>`, `<task>`, `<context>`,
  `<success_criteria>`, `<actions>`, `<constraints>`, `<reasoning_mode>`,
  `<output_format>`, `<examples>`, `<verification>`
- **Inside tags:** Markdown allowed (lists, bold, code spans)
- **Conditional modules:** wrapped in XML too (`<fact_checking>`, `<computation_strategy>`,
  `<creativity_protocol>`, `<multimodal_input>`)
- **Examples:** wrap each in `<example>`, the set in `<examples>`
- **Verbosity:** Opus 5 runs longer by default than prior models, and raising or lowering
  `effort` does not reliably change visible response length. If the deliverable needs to be
  short, say so explicitly in OUTPUT_FORMAT rather than relying on the model's default
- **Emphasis:** avoid `CRITICAL: YOU MUST`-style escalation on instructions that steer
  *tool or skill triggering* — current models over-trigger on it, and plain "Use X when…"
  works better. Ordinary `NEVER` / `MUST` / `DO NOT` inside formatting and grounding rules
  is fine; the vendor's own sample prompts use it
- **Avoid:** prefilled assistant responses — unsupported, see Old patterns

### gpt

- **Block wrapping:** Markdown headers for hierarchy — `# Role`, `# Task`, `# Context`,
  `# Success Criteria`, `# Actions`, `# Constraints`, `# Reasoning Mode`, `# Output Format`,
  `# Examples`, `# Verification` — **combined with XML tags to delineate content**, which is
  what the vendor guide recommends. Markdown marks sections and hierarchy; XML marks where a
  piece of content begins and ends. Use XML for anything the model must treat as a unit:
  examples, supplied context, input data, embedded specs
- **Canonical shape:** the vendor's developer-message skeleton is Identity → Instructions →
  Examples → Context. The CRAFT+ block order already satisfies it; keep it
- **Subcategories:** `##` for nesting
- **Long or agentic prompts:** open with a `# Persistence` section — "Keep going until the
  user's query is completely resolved, before ending your turn and yielding back to the
  user." This is the vendor's recommended wording. No quantified gain is claimed for it
- **Conditional modules:** headers (`# Fact Checking`, `# Computation Strategy`) or XML —
  both work; XML is preferred when the module's content should be treated as a unit

### gemini

- **Block wrapping:** Markdown headers (`## Role`, `## Task`, `## Context`, etc.)
- **Structured data:** use Markdown tables for comparisons or matrices
- **Section separation:** `---` (three hyphens) between major sections
- **Opening:** explicit goal sentence at the start: `Goal: [single sentence describing the
  deliverable]`
- **Style:** literal, direct, and **short**. This generation is less verbose than its
  predecessors and prefers direct answers; the vendor guide asks for concise input prompts
  and warns that verbose prompt engineering can cause over-analysis. Of the five targets,
  this is the one to trim hardest
- **Objective constraints only:** the vendor guide singles out subjective qualifiers —
  "write a summary of 3 sentences or less", not "write a brief summary". This matches the
  SUCCESS_CRITERIA rule in `methodology.md`
- **Temperature:** leave it at the default 1.0. Lowering it for determinism can cause
  looping or degraded performance on complex tasks. If the user mentions pinning
  temperature, flag this in `user_instructions`
- **Images:** `media_resolution` trades tokens for recognition accuracy — raise it when the
  task depends on reading text inside an image
- **Conditional modules:** wrap in `## Fact Checking`, `## Computation Strategy`, etc.

### deepseek

- **Block wrapping:** either Markdown headers OR XML tags — both work
- **Standard CRAFT+ approach:** no model-specific tweaks needed beyond reasoning control
- **Model selection:** `deepseek-v4-pro` for quality-sensitive reasoning,
  `deepseek-v4-flash` for faster and cheaper serving. Both are open-weight under MIT with a
  1,048,576-token context window
- **Reasoning:** use the thinking effort levels (low / high / max) rather than writing
  decomposition instructions into the prompt

### universal

- **Block wrapping:** hybrid format — XML tags as the scaffold + Markdown content inside the
  tags. This is the intersection that all four vendors accept: Claude wants XML, GPT accepts
  and benefits from it, Gemini and DeepSeek tolerate it
- **Conditional modules:** wrap in XML
- **Minimum-risk choices:**
  - No escalated emphasis on tool-triggering instructions
  - No "think step by step" injection
  - No prefilled responses
  - Examples only if genuinely needed for format reproduction
  - Keep it short — the Gemini constraint is the binding one across the set
- **Goal:** a prompt that works adequately on all four families at the cost of being
  slightly suboptimal on each compared to its target-specific format

## Quick comparison

| Aspect | Claude | GPT | Gemini | DeepSeek | Universal |
|---|---|---|---|---|---|
| Block wrap | XML | Markdown `#` + XML for content | Markdown `##` | Either | XML + Markdown |
| Reasoning control | `effort` / extended-thinking mode | `reasoning_effort` | `thinking_level` | thinking effort low/high/max | whatever the client exposes |
| CoT injection | Never | Never | Never | Never | Never |
| Emphasis | Gentle on tool triggers | Standard | Direct | Standard | Gentle |
| Length pressure | Opus 5 runs long — ask for short | Standard | Trim hardest | Standard | Trim |
| Section break | XML closing tags | Markdown spacing | `---` | Either | XML closing |
| Tables | Inside XML | Inside `#` sections | Native fit | Either | Inside XML |

## Decision when target_model = "universal"

If you must pick "universal", explain in the response's `assumptions` field (or visible
section) that the prompt is intentionally model-agnostic and may be slightly suboptimal on
any specific target. Recommend the user pick a specific target if they know which model
they'll use.

---

## Old patterns

<details>
<summary>Retired identifiers and techniques — kept for recognition, do not emit</summary>

**`deepseek-chat` / `deepseek-reasoner`.** Both identifiers were discontinued. The skill's
target id is now `deepseek`, and the API identifiers are `deepseek-v4-pro` /
`deepseek-v4-flash`. The old rule that DeepSeek was "the one target where explicit
chain-of-thought injection is still useful" went with it: the V4 generation has its own
thinking-effort levels. `validate.py` still accepts `deepseek-chat` as a hidden alias so
existing callers do not break.

**Prefilled assistant responses.** Providing a partial assistant message on the last turn
is no longer supported starting with Claude 4.6 models; such requests return a 400 error.
Anthropic's documented migrations: Structured Outputs for format coercion, an explicit
"respond directly without preamble" instruction for preamble removal, and moving
continuations into the user turn.

**`budget_tokens` for extended thinking.** Deprecated on Opus 4.6 / Sonnet 4.6 and returns a
400 error on Claude 4.7 and later. Use `effort` with adaptive thinking, or `max_tokens` as a
hard ceiling.

**"Think step by step" as a quality lever.** Useful before models reasoned internally.
Today it competes with the reasoning control on every supported target. See *Reasoning
control* above.

</details>
