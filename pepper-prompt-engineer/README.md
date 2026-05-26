# `pepper-prompt-engineer` — CRAFT+ Prompt Engineer

A portable prompt-engineering skill that turns any task description into a production-ready, target-model-specific prompt using the **CRAFT+ methodology** (CRAFT extended with 2026 best practices: success criteria, conditional modules, verification, target-model polish).

Methodology sources: Anthropic Prompt Engineering Best Practices (Apr 2026), OpenAI GPT-5 Prompting Guide (Mar 2026), Google Gemini API System Instructions (Mar 2026), DeepSeek V4 Docs (Apr 2026), Misaki & Akiba — [String Seed of Thought](https://arxiv.org/abs/2510.21150) (ICLR 2026).

## What it solves

Ad-hoc prompts under-specify success criteria, miss target-model formatting (Claude XML / GPT Markdown / Gemini tables / DeepSeek CoT), and forget conditional modules (fact-checking, code execution, SSoT diversity, multi-modal). This skill packages a senior-prompt-engineer workflow into one agent that:

- detects target model, classifies the task, asks at most 3 critical clarifications;
- assembles the 10 CRAFT+ blocks (role, task, context, success criteria, actions, constraints, reasoning mode, output format, examples, verification);
- conditionally embeds fact-checking / code-execution / SSoT / multi-modal modules based on bilingual (RU+EN) triggers;
- polishes formatting for the chosen target model;
- self-checks the result against a 13-item checklist before returning it.

## Two delivery modes

| Mode | Use case | Where |
|------|----------|-------|
| **Universal chat prompt** | Paste-once system prompt for Claude.ai Projects, ChatGPT Custom GPT, Gemini Gem, DeepSeek chat | [`chat-prompt.md`](./chat-prompt.md) |
| **Claude Code skill** | Full toolset: references, examples, programmatic validator, evals | [`anthropic/SKILL.md`](./anthropic/SKILL.md) |

Both modes share the same CRAFT+ methodology. Pick chat for the lowest-friction path (one paste, works in any chat UI); pick the skill for repeatable use inside Claude Code with auto-loaded references.

## Pick your platform

| Platform | File |
|----------|------|
| Any chat (Claude.ai / ChatGPT / Gemini / DeepSeek) — paste as system message | [`chat-prompt.md`](./chat-prompt.md) |
| Claude Code — install as a skill (single-file download) | [`pepper-prompt-engineer.skill`](./pepper-prompt-engineer.skill) |
| Claude Code — install as a skill (browse files first) | [`anthropic/SKILL.md`](./anthropic/SKILL.md) + [`anthropic/INSTALL.md`](./anthropic/INSTALL.md) |

## Using the chat prompt

1. Open a chat with any frontier model (Claude.ai, ChatGPT, Gemini, DeepSeek).
2. Copy the fenced block from [`chat-prompt.md`](./chat-prompt.md) and paste it as the **first** message.
3. Wait for the bilingual greeting — the agent does **not** process the master prompt itself as a task.
4. Describe your task, e.g. *"build a Claude prompt for parsing Telegram channels in Python"*. Naming the target model upfront skips a clarification round.
5. You'll get a ready prompt inside a code block with a Copy button. Paste it into a new chat with the target model.

**Tip — persistent install.** In Claude.ai create a Project with the prompt in the System Prompt field; in ChatGPT create a Custom GPT with it in Instructions; in Gemini create a Gem. The chat-activation greeting then doesn't fire (no first user message) and the agent jumps straight to handling tasks.

## Installing the Claude Code skill

Two paths — pick the one you prefer:

- **One-file download:** grab [`pepper-prompt-engineer.skill`](./pepper-prompt-engineer.skill) and install it as a Claude Code skill.
- **Browse first:** read [`anthropic/SKILL.md`](./anthropic/SKILL.md) and the supporting files under [`anthropic/`](./anthropic/), then follow the step-by-step setup in [`anthropic/INSTALL.md`](./anthropic/INSTALL.md).

Both deliver the same 23 files (SKILL.md, INSTALL.md, 7 references, 6 examples, validator + script README, and an evals suite).

## When NOT to use

Do **not** activate this skill to execute the user's task directly. It builds prompts for *other* sessions to execute. Activation requires explicit construction triggers (RU: «собери промпт», «улучши промпт» / EN: "build a prompt", "improve this prompt"). For straight task execution, let the underlying model handle the request without this skill.

## Language versions

- English — this file
- Русский — [`README.ru.md`](./README.ru.md)

## License

[MIT](../LICENSE) © ITSalt.
