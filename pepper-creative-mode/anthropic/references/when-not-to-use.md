# When Not to Use `pepper-creative-mode`

`pepper-creative-mode` adds tokens and introduces artificial arithmetic. On deterministic tasks, this reduces quality and wastes context. Apply `pepper-creative-mode` only when the task genuinely requires stochasticity or creative variety.

---

## Hard exclusions

Do not use `pepper-creative-mode` for any of the following:

| Task type | Reason |
|-----------|--------|
| **Math or arithmetic** | One correct answer exists; random variation produces wrong answers. |
| **Factual lookup or retrieval** | The answer is a fixed fact; variation means error. |
| **Code debugging or review** | Correctness is the goal; varied "interpretations" of a bug are harmful. |
| **Code refactoring** | A specific transformation is expected; random structure choices break it. |
| **Translation** | The target-language rendering is constrained; creative variation distorts meaning. |
| **Classification** | There is a correct label; `pepper-creative-mode` turns a classification into a lottery. |
| **Extraction** | Extracting specific fields or entities is deterministic by definition. |
| **Summarization** | The summary must faithfully reflect the source; variety introduces hallucination risk. |

---

## Soft exclusions

Consider skipping `pepper-creative-mode` in these situations even if the task looks probabilistic:

- **Non-reasoning models:** These cannot reliably perform modulo arithmetic or rolling hash. The string gets generated but the arithmetic in `<thinking>` comes out wrong, producing a result *worse* than skipping entirely. The paper's small-model table makes the size-vs-reasoning distinction sharp: on the unbiased 2-choice task Qwen3-4B degrades by **436%** and Qwen3-1.7B by **413%**, while the *thinking* variant of that same 4B model improves by **88%**. The dividing line is reasoning capability, not parameter count. Apply to Sonnet-class and above.
- **Diversity-Aware Generation on non-reasoning models specifically:** an independent 2026 evaluation ([arXiv:2606.10302](https://arxiv.org/abs/2606.10302)) measured how much of the injected randomness actually reaches the output and found it near zero for this technique on four non-reasoning backbones — the random string is generated and then largely ignored. That study did not test reasoning models, where the original results were obtained. Treat the DAG half of this skill as reasoning-model-dependent, and prefer raising temperature if you are on a non-reasoning model.
- **Tasks requiring only a single creative response with no diversity requirement:** If the user asks for "a haiku" (one, no diversity specified), `pepper-creative-mode` is unnecessary overhead. Apply it when the user signals they want variety ("write three different haiku", "surprise me each time").
- **Very long-form creative outputs (multi-thousand-word stories):** A Decision Cascade can seed the high-level structure, but paragraph-level prose variation will naturally emerge from the model. Limit the cascade to top-level components (genre, protagonist archetype, setting, ending type) rather than trying to cascade every sentence.

---

## Known anomaly: QwQ-32B on unbiased 2-choice tasks

The paper (arXiv:2510.21150, Table 1) reports that **QwQ-32B** is the one exception to the general pattern:

- Baseline JS divergence on unbiased 2-choice tasks: **2.43 ×10⁻³** (already near-PRNG quality — the PRNG reference is 1.85 ×10⁻³).
- With `pepper-creative-mode`: **3.39 ×10⁻³** (slightly worse).

All JS divergences in the paper are reported in units of 10⁻³. Read bare figures like "2.43" accordingly: JS divergence is bounded above by ln 2 ≈ 0.693, so an unscaled 2.43 would be impossible.

On the *biased* tasks the same model improves by 96–99%, which is the pattern to remember: the anomaly is confined to the unbiased binary case.

The likely reading — the paper reports the result without attributing a cause — is that QwQ-32B's native output distribution is already close to uniform for binary choices, leaving nothing to fix while the arithmetic step adds its own small error. The operational rule generalises beyond this one model: **if the baseline is already near-uniform, skip the technique.** Apply it to biased or multi-way distributions, where it shows clear and consistent improvement.

---

## Fallback guidance for mixed tasks

Many real tasks combine a deterministic part and a creative part:

- "Debug this function, then write three different docstrings for it." → Apply `pepper-creative-mode` only to the docstring generation; answer the debug part normally.
- "Translate this paragraph, then brainstorm five alternative headlines for the article." → Translate normally; use Decision Cascade for the headlines.
- "Find the bug, and if you can't, pick one of these three workarounds at random." → Debug deterministically; if no fix, apply Sum-Mod to the workaround choice.

The rule: **apply `pepper-creative-mode` only to the sub-parts that are genuinely stochastic or creatively open-ended.** A single response can contain one `pepper-creative-mode` block for the random sub-task and separate prose for the deterministic sub-tasks.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
