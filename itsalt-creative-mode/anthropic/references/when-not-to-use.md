# When Not to Use `itsalt:creative-mode`

`itsalt:creative-mode` adds tokens and introduces artificial arithmetic. On deterministic tasks, this reduces quality and wastes context. Apply `itsalt:creative-mode` only when the task genuinely requires stochasticity or creative variety.

---

## Hard exclusions

Do not use `itsalt:creative-mode` for any of the following:

| Task type | Reason |
|-----------|--------|
| **Math or arithmetic** | One correct answer exists; random variation produces wrong answers. |
| **Factual lookup or retrieval** | The answer is a fixed fact; variation means error. |
| **Code debugging or review** | Correctness is the goal; varied "interpretations" of a bug are harmful. |
| **Code refactoring** | A specific transformation is expected; random structure choices break it. |
| **Translation** | The target-language rendering is constrained; creative variation distorts meaning. |
| **Classification** | There is a correct label; `itsalt:creative-mode` turns a classification into a lottery. |
| **Extraction** | Extracting specific fields or entities is deterministic by definition. |
| **Summarization** | The summary must faithfully reflect the source; variety introduces hallucination risk. |

---

## Soft exclusions

Consider skipping `itsalt:creative-mode` in these situations even if the task looks probabilistic:

- **Small or non-reasoning models (e.g. Haiku, small instruct models without CoT):** These models cannot reliably perform modulo arithmetic or rolling hash in a single forward pass. The string will be generated but the arithmetic in `<thinking>` may be incorrect, producing a biased result that is worse than skipping entirely. Effectiveness scales with model reasoning quality; apply to Sonnet-class and above.
- **Tasks requiring only a single creative response with no diversity requirement:** If the user asks for "a haiku" (one, no diversity specified), `itsalt:creative-mode` is unnecessary overhead. Apply it when the user signals they want variety ("write three different haiku", "surprise me each time").
- **Very long-form creative outputs (multi-thousand-word stories):** A Decision Cascade can seed the high-level structure, but paragraph-level prose variation will naturally emerge from the model. Limit the cascade to top-level components (genre, protagonist archetype, setting, ending type) rather than trying to cascade every sentence.

---

## Known anomaly: QwQ-32B on unbiased 2-choice tasks

The paper (arXiv:2510.21150, failure analysis section) reports that **QwQ-32B** is an exception to the general pattern:

- Baseline JS divergence on unbiased 2-choice tasks: **2.43** (already near-PRNG quality).
- With `itsalt:creative-mode`: **3.39** (slightly worse).

QwQ-32B's native token distribution happens to be nearly uniform for binary choices, and the arithmetic step introduces a small bias. For QwQ-32B and similarly well-calibrated models, skip `itsalt:creative-mode` on unbiased binary tasks and apply it only for biased or multi-way distributions where it shows clear improvement.

---

## Fallback guidance for mixed tasks

Many real tasks combine a deterministic part and a creative part:

- "Debug this function, then write three different docstrings for it." → Apply `itsalt:creative-mode` only to the docstring generation; answer the debug part normally.
- "Translate this paragraph, then brainstorm five alternative headlines for the article." → Translate normally; use Decision Cascade for the headlines.
- "Find the bug, and if you can't, pick one of these three workarounds at random." → Debug deterministically; if no fix, apply Sum-Mod to the workaround choice.

The rule: **apply `itsalt:creative-mode` only to the sub-parts that are genuinely stochastic or creatively open-ended.** A single response can contain one `itsalt:creative-mode` block for the random sub-task and separate prose for the deterministic sub-tasks.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
