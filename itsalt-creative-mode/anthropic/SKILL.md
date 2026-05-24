---
name: itsalt:creative-mode
description: "This skill instructs Claude to perform distribution-faithful sampling and diverse generation by seeding randomness from a self-generated string rather than relying on token-completion patterns. Apply it when the task requires genuine stochasticity or meaningful variation across runs: creative writing, brainstorming, variant generation, probabilistic sampling, mixed-strategy games, and agent simulation. Trigger phrases include: \"write 5 different\", \"brainstorm\", \"flip a coin\", \"pick randomly\", \"generate variants\", \"surprise me\", \"diverse\", \"different versions\". Do not apply for math, factual lookup, code debugging, translation, classification, extraction, or any single-answer task where variability reduces correctness."
---

# itsalt:creative-mode

Provenance: see `../README.md`. Technique: String Seed of Thought, Misaki & Akiba, arXiv:2510.21150, accepted ICLR 2026.

---

## Background

Frontier LLMs show systematic bias when they must produce stochastic output. Left to their own token-completion patterns, models produce "heads" ~78% of the time on a nominal 50/50 coin flip, collapse creative prompts to a narrow set of recurring outputs (fables default to tortoise-and-hare variants), and play exploitable strategies in mixed-strategy games. The root causes are RLHF-induced mode collapse, typicality bias in preference data, and tokenization asymmetries (e.g. "heads" is one token, "tails" is two). `itsalt:creative-mode` addresses this by inserting a self-generated random string before the decision step. The model commits to the string first, then derives the answer deterministically via arithmetic on that string. This breaks the path that leads to biased pattern completion without requiring any external tool.

---

## When to apply

Activate this skill when any of the following conditions hold:

- **Probabilistic choice is required.**
  Example: "Flip a fair coin." / "Roll a six-sided die." / "Pick one of these three options at random."

- **Biased sampling is required.**
  Example: "Choose heads 30% of the time." / "Pick option A with probability 1/5, option B with 4/5."

- **Multiple diverse creative outputs are requested.**
  Example: "Write 5 different taglines." / "Generate variants of this headline." / "Brainstorm 10 product names."

- **A single creative output is requested with a novelty or surprise signal.**
  Example: "Surprise me with an opening line." / "Give me something unexpected."

- **Mixed-strategy game play under Nash equilibrium.**
  Example: "Pick an RPS move against an adversarial opponent (1/3 each)."

- **Agent simulation with stochastic behavior.**
  Example: "Simulate a customer who buys 40% of the time and browses 60% of the time."

- **Synthetic data requiring variety across many samples.**
  Example: "Generate 20 diverse customer reviews of this product."

- **The user prompt contains any of these trigger phrases:**
  "write 5 different", "brainstorm", "flip a coin", "pick randomly", "generate variants",
  "surprise me", "diverse", "different versions", "at random", "pick one", "vary each time."

---

## When to skip

Do NOT activate for:

- **Math or arithmetic** — one correct answer exists; random variation produces wrong answers.
- **Factual lookup or retrieval** — the answer is a fixed fact; variation means error.
- **Code debugging, review, or refactoring** — correctness is the only goal.
- **Translation** — unless explicitly framed as creative or adaptive translation.
- **Classification, extraction, or summarization** — deterministic tasks with objectively better answers.
- **Any task where the same correct answer is expected on every run.**

See [`references/when-not-to-use.md`](references/when-not-to-use.md) for edge cases, the QwQ-32B anomaly, and fallback guidance for mixed tasks.

---

## The two modes

**PIF — Probabilistic Instruction Following.** The user specifies a target distribution and the model must sample from it faithfully across many runs. Correctness is measurable: run the same prompt 1000 times and measure empirical frequency against the target. Frontier models without `itsalt:creative-mode` fail badly — producing "heads" at ~78% on a nominal 50/50 coin due to RLHF-induced mode collapse and tokenization asymmetries. `itsalt:creative-mode` fixes this by committing the model to a string before the decision step; the string serves as an internal seed that the model then maps deterministically to an outcome via modular arithmetic.

**DAG — Diversity-Aware Generation.** The user asks for creative output with no fixed distribution, but meaningful variation across runs is desired. `itsalt:creative-mode` achieves diversity via the Decision Cascade pattern: the output is decomposed into 2–5 independent components (e.g. setting, tone, twist), each component is resolved deterministically from a distinct segment of the random string using Sum-Mod, and the components are assembled into the final answer. Because the string differs each run, the assembled output differs meaningfully each run. The candidate space (product of candidate-list lengths per component) bounds the number of distinct possible outputs.

---

## Core protocol

Every `itsalt:creative-mode` response uses exactly three tagged sections in this order:

```text
<random_string>
  [16+ characters, mixed case, digits, and symbols — generated internally, no external tools]
</random_string>

<thinking>
  [Deterministic arithmetic on the string. Show every computation step explicitly.]
</thinking>

<answer>
  [Final answer only. No reasoning, no hedging, no extra text.]
</answer>
```

Minimal inline example (fair coin, Sum-Mod):

```text
<random_string>7$Aq9!zR@k3mP#vX</random_string>
<thinking>
ord sum = 55+36+65+113+57+33+122+82+64+107+51+109+80+35+118+88 = 1215
1215 mod 2 = 1
mapping: 0->Heads, 1->Tails -> Tails
</thinking>
<answer>Tails</answer>
```

---

## Pattern selection

Choose the arithmetic pattern that matches the task's probability structure:

- **Sum-Mod** ([`references/sum-mod.md`](references/sum-mod.md)) — Use when all N outcomes have equal probability. Formula: `sum(ord(c) for c in string) mod N`. Map the result (0-indexed) to the Nth option.

- **Rolling Hash** ([`references/rolling-hash.md`](references/rolling-hash.md)) — Use when probabilities are unequal or arbitrary. Formula: `h = 0; for c in string: h = (h*31 + ord(c)) mod M` (M >= 10000). Split `[0, M)` into intervals sized by target probabilities; the interval containing `h` is the choice.

- **Decision Cascade** ([`references/decision-cascade.md`](references/decision-cascade.md)) — Use for open-ended creative tasks. Decompose the output into components, define candidate lists per component, pick each component by applying Sum-Mod to a non-overlapping segment of the string, then assemble.

Quick selection guide:

| Task type | Pattern |
|-----------|---------|
| Fair coin, uniform die, uniform pick | Sum-Mod |
| Biased coin, weighted choice, arbitrary split | Rolling Hash |
| Creative story, slogan, poem, brainstorm | Decision Cascade |
| RPS / Nash equilibrium (N equal options) | Sum-Mod |
| Agent behavior (e.g. buy 40% / browse 60%) | Rolling Hash |

---

## Hard rules

Follow all of these without exception:

- Generate the random string internally. Do not call any external tool, API, or function to obtain it. No mention of "random number generator", "PRNG", "Math.random()", or any external source.
- The string must be at least 16 characters and include all four character classes: uppercase letters, lowercase letters, digits, and symbols.
- Generate a fresh string for each independent decision. Reusing the same string across decisions destroys statistical independence.
- Show the arithmetic in `<thinking>` in full. Do not skip steps, do not write pseudo-arithmetic, perform the actual computation.
- Put only the final answer in `<answer>`. No reasoning, no hedging, no explanation, no qualifiers.
- Do not skip the `<random_string>` section even if the task feels trivial.
- For mixed tasks (part deterministic, part stochastic), apply `itsalt:creative-mode` only to the stochastic sub-parts. Answer the deterministic parts normally before or after the `itsalt:creative-mode` block.
- Do not adjust the string or the arithmetic after seeing the result. Commit and proceed.

---

## References

- [`references/sum-mod.md`](references/sum-mod.md) — Sum-Mod: formula, step-by-step worked example, edge cases (N=1, N>26, empty string).
- [`references/rolling-hash.md`](references/rolling-hash.md) — Rolling Hash: formula, interval splitting, worked examples for 30/70 and 17/33/50 splits.
- [`references/decision-cascade.md`](references/decision-cascade.md) — Decision Cascade: decomposition procedure, two worked examples (horror story and New Year wish).
- [`references/when-not-to-use.md`](references/when-not-to-use.md) — Hard exclusions, soft exclusions, QwQ-32B anomaly, fallback for mixed tasks.

## Examples

- [`examples/fair-coin.md`](examples/fair-coin.md) — Sum-Mod, fair 50/50 coin flip, complete trace with arithmetic.
- [`examples/biased-decision.md`](examples/biased-decision.md) — Rolling Hash, 30/70 biased coin, complete trace with all hash steps.
- [`examples/creative-generation.md`](examples/creative-generation.md) — Decision Cascade, same prompt run three times with three distinct outputs.
- [`examples/mixed-strategy.md`](examples/mixed-strategy.md) — Sum-Mod N=3, Rock-Paper-Scissors Nash equilibrium move selection.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
