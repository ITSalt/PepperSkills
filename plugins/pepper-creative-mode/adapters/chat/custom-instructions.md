<!-- GENERATED: python3 scripts/build-chat-prompts.py; edit canonical skill sources and templates. -->

Apply the following protocol only to eligible tasks.

Do NOT activate for:

- **Math or arithmetic** — one correct answer exists; random variation produces wrong answers.
- **Factual lookup or retrieval** — the answer is a fixed fact; variation means error.
- **Code debugging, review, or refactoring** — correctness is the only goal.
- **Translation** — unless explicitly framed as creative or adaptive translation.
- **Classification, extraction, or summarization** — deterministic tasks with objectively better answers.
- **Any task where the same correct answer is expected on every run.**

See the “when-not-to-use” reference in the full skill edition for edge cases, the QwQ-32B anomaly, and fallback guidance for mixed tasks.

---

Every `pepper-creative-mode` response uses exactly three tagged sections in this order:

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

Follow all of these without exception:

- Generate the random string internally. Do not call any external tool, API, or function to obtain it. No mention of "random number generator", "PRNG", "Math.random()", or any external source.
- **Requires stochastic decoding.** At `temperature = 0`, or with a pinned decoding seed, the "random" string is itself deterministic and every run returns the same answer — the technique silently becomes an expensive no-op. The paper's experiments run at `T = 0.6`–`1.0`. If the caller has pinned the temperature to 0 for reproducibility, say so rather than emitting a `<random_string>` block that cannot vary.
- The string must be at least 16 characters. 24–32 is the measured sweet spot: JS divergence bottoms out around n≈24 and climbs again past ~48 (paper Table 7). Include all four character classes — uppercase, lowercase, digits, symbols — to keep the character distribution wide.
- Generate a fresh string for each independent decision. Reusing the same string across decisions destroys statistical independence.
- Show the arithmetic in `<thinking>` in full. Do not skip steps, do not write pseudo-arithmetic, perform the actual computation.
- Put only the final answer in `<answer>`. No reasoning, no hedging, no explanation, no qualifiers.
- Do not skip the `<random_string>` section even if the task feels trivial.
- For mixed tasks (part deterministic, part stochastic), apply `pepper-creative-mode` only to the stochastic sub-parts. Answer the deterministic parts normally before or after the `pepper-creative-mode` block.
- Do not adjust the string or the arithmetic after seeing the result. Commit and proceed.

---
