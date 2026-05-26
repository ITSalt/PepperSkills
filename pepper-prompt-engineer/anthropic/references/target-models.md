# Target-Model Formatting

After assembling the 10 CRAFT+ blocks + active conditional modules (Steps 5-6 of the workflow), Step 7 polishes the prompt for the chosen target_model. Each frontier model has known formatting preferences from official documentation (May 2026).

## Display names

When showing the chosen target in the output's section header:

| target_model | Display name |
|---|---|
| claude | Claude |
| gpt | ChatGPT |
| gemini | Gemini |
| deepseek-chat | DeepSeek |
| universal | Universal |

## Formatting rules per target

### claude

- **Block wrapping:** XML tags for every CRAFT+ block: `<role>`, `<task>`, `<context>`, `<success_criteria>`, `<actions>`, `<constraints>`, `<reasoning_mode>`, `<output_format>`, `<examples>`, `<verification>`
- **Inside tags:** Markdown allowed (lists, bold, code spans)
- **Conditional modules:** wrapped in XML too (`<fact_checking>`, `<computation_strategy>`, `<creativity_protocol>`, `<multimodal_input>`)
- **Avoid:** "CRITICAL: YOU MUST", "IMPORTANT!!!", all-caps emphasis — Claude 4.6+ over-triggers on aggressive language
- **Avoid:** "think step by step" injection — Claude does CoT internally via the API's thinking parameter
- **Avoid:** prefilled responses — deprecated since 4.6

### gpt

- **Block wrapping:** Markdown headers: `# Role`, `# Task`, `# Context`, `# Success Criteria`, `# Actions`, `# Constraints`, `# Reasoning Mode`, `# Output Format`, `# Examples`, `# Verification`
- **Subcategories:** `##` for nesting
- **Long prompts:** add at the start a `# Persistence` section with "Keep working until the user's request is fully resolved" — per OpenAI Cookbook gives +20% on agentic tasks
- **Conditional modules:** wrap in headers (`# Fact Checking`, `# Computation Strategy`, etc.) or inline XML — XML is fine
- **Avoid:** "think step by step" — GPT-5+ thinking handles CoT via the API's reasoning.effort param

### gemini

- **Block wrapping:** Markdown headers (`## Role`, `## Task`, `## Context`, etc.)
- **Structured data:** use Markdown tables for comparisons or matrices
- **Section separation:** `---` (three hyphens) between major sections
- **Opening:** explicit goal sentence at the start: `Goal: [single sentence describing the deliverable]`
- **Style:** literal and direct — Gemini's docs explicitly recommend declarative over conversational
- **Conditional modules:** wrap in `## Fact Checking`, `## Computation Strategy`, etc.

### deepseek-chat

- **Block wrapping:** either Markdown headers OR XML tags — both work equivalently for V3/V4
- **Standard CRAFT+ approach:** no model-specific tweaks needed
- **CoT:** explicit "think step by step" can be added if the task requires multi-step decomposition. This is the ONE target where CoT injection is still useful (V3/V4 chat does not auto-CoT like frontier reasoning models).
- **Note:** DeepSeek R1 is NOT covered by this skill (different philosophy — minimalism, no system prompt, no few-shot). See the user's separate skill or guide for R1.

### universal

- **Block wrapping:** hybrid format — XML tags as the scaffold + Markdown content inside the tags
- **Conditional modules:** wrap in XML
- **Minimum-risk choices:**
  - No aggressive emphasis (no caps, no "CRITICAL")
  - No "think step by step" injection
  - No prefilled responses
  - Few-shot examples only if truly critical for format reproduction
- **Goal:** produces a prompt that works adequately on all major frontier models — Claude / GPT / Gemini / DeepSeek-Chat — at the cost of being slightly suboptimal on each compared to its target-specific format

## Quick comparison

| Aspect | Claude | GPT | Gemini | DeepSeek | Universal |
|---|---|---|---|---|---|
| Block wrap | XML | Markdown `#` | Markdown `##` | Either | XML + Markdown |
| Emphasis | Gentle | Standard | Direct | Standard | Gentle |
| CoT trigger | Never | Never | Never | If needed | Never |
| Section break | XML closing tags | Markdown spacing | `---` | Either | XML closing |
| Tables | Inside XML | Inside `#` sections | Native fit | Either | Inside XML |

## Decision when target_model = "universal"

If you must pick "universal", explain in the response's `assumptions` field (or visible section) that the prompt is intentionally model-agnostic and may be slightly suboptimal on any specific target. Recommend the user pick a specific target if they know which model they'll use.
