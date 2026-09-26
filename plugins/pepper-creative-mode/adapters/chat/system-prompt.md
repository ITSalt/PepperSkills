<!-- GENERATED: python3 scripts/build-chat-prompts.py; edit canonical skill sources and templates. -->

Apply the following protocol only to eligible tasks.

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

See appendix “when-not-to-use” for edge cases, the QwQ-32B anomaly, and fallback guidance for mixed tasks.

---

## The two modes

**PIF — Probabilistic Instruction Following.** The user specifies a target distribution and the model must sample from it faithfully across many runs. Correctness is measurable: run the same prompt many times and compare empirical frequency against the target. The gains are largest where the target is skewed — across five frontier models the paper reports 85–99% reductions in JS divergence on biased distributions, versus a mixed picture on an unbiased coin (from −92% on deepseek-r1 to +40% on QwQ-32B). `pepper-creative-mode` works by committing the model to a string before the decision step; the string serves as an internal seed that the model then maps deterministically to an outcome via modular arithmetic.

**DAG — Diversity-Aware Generation.** The user asks for creative output with no fixed distribution, but meaningful variation across runs is desired. `pepper-creative-mode` achieves diversity via the Decision Cascade pattern: the output is decomposed into 2–5 independent components (e.g. setting, tone, twist), each component is resolved deterministically from a distinct segment of the random string using Sum-Mod, and the components are assembled into the final answer. Because the string differs each run, the assembled output differs meaningfully each run. The candidate space (product of candidate-list lengths per component) bounds the number of distinct possible outputs.

---

## Core protocol

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

## Pattern selection

Choose the arithmetic pattern that matches the task's probability structure:

- **Sum-Mod** (appendix “sum-mod”) — Use when all N outcomes have equal probability. Formula: `sum(ord(c) for c in string) mod N`. Map the result (0-indexed) to the Nth option.

- **Rolling Hash** (appendix “rolling-hash”) — Use when probabilities are unequal or arbitrary. Formula: `h = 0; for c in string: h = (h*31 + ord(c)) mod M` (M >= 10000). Split `[0, M)` into intervals sized by target probabilities; the interval containing `h` is the choice.

- **Decision Cascade** (appendix “decision-cascade”) — Use for open-ended creative tasks. Decompose the output into components, define candidate lists per component, pick each component by applying Sum-Mod to a non-overlapping segment of the string, then assemble.

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
- **Requires stochastic decoding.** At `temperature = 0`, or with a pinned decoding seed, the "random" string is itself deterministic and every run returns the same answer — the technique silently becomes an expensive no-op. The paper's experiments run at `T = 0.6`–`1.0`. If the caller has pinned the temperature to 0 for reproducibility, say so rather than emitting a `<random_string>` block that cannot vary.
- The string must be at least 16 characters. 24–32 is the measured sweet spot: JS divergence bottoms out around n≈24 and climbs again past ~48 (paper Table 7). Include all four character classes — uppercase, lowercase, digits, symbols — to keep the character distribution wide.
- Generate a fresh string for each independent decision. Reusing the same string across decisions destroys statistical independence.
- Show the arithmetic in `<thinking>` in full. Do not skip steps, do not write pseudo-arithmetic, perform the actual computation.
- Put only the final answer in `<answer>`. No reasoning, no hedging, no explanation, no qualifiers.
- Do not skip the `<random_string>` section even if the task feels trivial.
- For mixed tasks (part deterministic, part stochastic), apply `pepper-creative-mode` only to the stochastic sub-parts. Answer the deterministic parts normally before or after the `pepper-creative-mode` block.
- Do not adjust the string or the arithmetic after seeing the result. Commit and proceed.

---

## when-not-to-use

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


## sum-mod

# Sum-Mod Pattern

Use this pattern for any **equal-probability N-way choice**: fair coin (N=2), uniform die (N=6), Nash-equilibrium RPS (N=3), or a uniform pick among K items.

---

## When to use

- All N outcomes have identical target probability (1/N each).
- N is known and fixed before generating the string.

If probabilities are unequal, use Rolling Hash instead (see [`rolling-hash.md`](rolling-hash.md)).

---

## Formula

```python
choice_index = sum(ord(c) for c in random_string) mod N
```

Map `choice_index` (0-indexed) to the Nth option in a fixed, agreed-upon ordering.

---

## Worked example: fair coin (N=2)

String generated by model: `7$Aq9!zR@k3mP#vX`

Step-by-step ord values:

| Char | ord |
|------|-----|
| `7`  |  55 |
| `$`  |  36 |
| `A`  |  65 |
| `q`  | 113 |
| `9`  |  57 |
| `!`  |  33 |
| `z`  | 122 |
| `R`  |  82 |
| `@`  |  64 |
| `k`  | 107 |
| `3`  |  51 |
| `m`  | 109 |
| `P`  |  80 |
| `#`  |  35 |
| `v`  | 118 |
| `X`  |  88 |

Sum = 55+36+65+113+57+33+122+82+64+107+51+109+80+35+118+88 = **1215**

1215 mod 2 = **1**

Mapping: 0 -> Heads, 1 -> Tails

Result: **Tails**

---

## Edge cases

**N=1:** There is only one option. No computation is needed; the result is always that option. Generate the string anyway (the hard rule requiring a `<random_string>` section still applies) and write the trivial arithmetic in `<thinking>`.

**Empty string:** Should never occur. The hard rules require at least 16 characters. If somehow the string is empty, the sum is 0 and the result is option 0. Do not generate an empty string.

**N > 26 choices:** Sum-Mod works for any N. The sum of ord values for a 16-character mixed string is typically in the range 800–1800, providing adequate coverage for N up to at least 100. For very large N (hundreds or thousands), the string should be longer (32+ characters) to ensure the sum is much larger than N and the residues are roughly uniform.

**Ties / off-by-one:** The mapping is 0-indexed. For N=3, the choices are labeled 0, 1, and 2. Define the mapping before computing; do not adjust the mapping after seeing the result.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.


## rolling-hash

# Rolling Hash Pattern

Use this pattern for **biased or arbitrary probability distributions**: a coin that lands heads 30% of the time, a three-way split at 17/33/50, or any distribution where the probabilities are not equal.

---

## When to use

- Outcome probabilities are unequal (e.g. 30/70, 17/33/50, 1/5/94).
- You need finer resolution than Sum-Mod naturally provides for small N.
- The target probabilities can be expressed as integer percentages or simple fractions.

For equal probabilities, Sum-Mod is simpler (see [`sum-mod.md`](sum-mod.md)).

---

## Formula

```python
h = 0
for c in random_string:
    h = (h * 31 + ord(c)) % M    # M >= 10000
```

`M` sets the resolution. Default to M=10000 (0.01% precision). Drop to M=100 only when every target probability is a whole percent — see "Interval-slicing error" below for what goes wrong otherwise.

---

## Interval splitting

Divide `[0, M)` into contiguous intervals sized proportionally to the target probabilities.

For probabilities p1, p2, ..., pk (summing to 1):

```text
Choice 1: h in [0,        floor(p1 * M))
Choice 2: h in [floor(p1*M), floor((p1+p2)*M))
...
Choice k: h in [floor((p1+...+p_{k-1})*M), M)
```

The interval containing `h` is the selected choice.

---

## Worked example: 30/70 biased coin (M=100)

String: `K#7mRq2$vXpL9@!t`

Rolling hash computation:

```text
h = 0
h = (0  * 31 + ord('K')) % 100 = (0  + 75) % 100 = 75
h = (75 * 31 + ord('#')) % 100 = (2325 + 35) % 100 = 2360 % 100 = 60
h = (60 * 31 + ord('7')) % 100 = (1860 + 55) % 100 = 1915 % 100 = 15
h = (15 * 31 + ord('m')) % 100 = (465 + 109) % 100 = 574 % 100 = 74
h = (74 * 31 + ord('R')) % 100 = (2294 + 82) % 100 = 2376 % 100 = 76
h = (76 * 31 + ord('q')) % 100 = (2356 + 113) % 100 = 2469 % 100 = 69
h = (69 * 31 + ord('2')) % 100 = (2139 + 50) % 100 = 2189 % 100 = 89
h = (89 * 31 + ord('$')) % 100 = (2759 + 36) % 100 = 2795 % 100 = 95
h = (95 * 31 + ord('v')) % 100 = (2945 + 118) % 100 = 3063 % 100 = 63
h = (63 * 31 + ord('X')) % 100 = (1953 + 88) % 100 = 2041 % 100 = 41
h = (41 * 31 + ord('p')) % 100 = (1271 + 112) % 100 = 1383 % 100 = 83
h = (83 * 31 + ord('L')) % 100 = (2573 + 76) % 100 = 2649 % 100 = 49
h = (49 * 31 + ord('9')) % 100 = (1519 + 57) % 100 = 1576 % 100 = 76
h = (76 * 31 + ord('@')) % 100 = (2356 + 64) % 100 = 2420 % 100 = 20
h = (20 * 31 + ord('!')) % 100 = (620 + 33) % 100 = 653 % 100 = 53
h = (53 * 31 + ord('t')) % 100 = (1643 + 116) % 100 = 1759 % 100 = 59
```

Final h = **59**

Intervals (M=100):
- Heads: [0, 30)
- Tails: [30, 100)

59 is in [30, 100) → **Tails**

---

## Worked example: three-way split 17/33/50 (M=100)

String: `Xw!3Kp#9mQr$7tZv`

Rolling hash computation (abbreviated — show full steps in `<thinking>`):

```text
h = 0
... [compute iteratively per formula above] ...
h = 43   (example result)
```

Intervals (M=100):
- Choice A (17%): [0, 17)
- Choice B (33%): [17, 50)
- Choice C (50%): [50, 100)

43 is in [17, 50) → **Choice B**

Note: In actual `<thinking>`, show all intermediate h values step by step. The abbreviated form above is for illustration only.

---

## Notes on M selection

| M value | Precision | Recommended use |
|---------|-----------|-----------------|
| 100 | 1% | Splits that land on whole percents, fast mental arithmetic |
| 1000 | 0.1% | Tenth-of-percent splits |
| 10000 | 0.01% | Fine-grained probability, simulation — **default** |

Larger M requires more computation in `<thinking>`. Use the smallest M that satisfies the required precision.

**Interval-slicing error.** `M` must divide the target probabilities cleanly, or the intervals will not sum to the intended split. `M=100` is exact for 30/70 (0.00 pp error) but not for thirds: `[0,33) / [33,66) / [66,100)` delivers 33/33/34 instead of 33.3/33.3/33.3 — up to **0.67 pp** off. `M=10000` reduces the same error to 0.007 pp. Use `M=100` only when every target probability is a whole percent; otherwise default to `M=10000`.

For equal-probability choices, prefer Sum-Mod ([`sum-mod.md`](sum-mod.md)) over a rolling hash with hand-cut intervals — `mod N` splits exactly by construction and cannot suffer this error.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.


## decision-cascade

# Decision Cascade Pattern

Use this pattern for **open-ended creative tasks** where there is no target distribution but meaningful variation across runs is desired: stories, slogans, poems, personas, synthetic data, brainstorm items.

---

## When to use

- The output is free-form creative text (not a probability choice).
- The same prompt should yield meaningfully different outputs on different runs.
- You can decompose the output into a small number of independent components.

For tasks with a specified probability distribution, use Sum-Mod or Rolling Hash instead.

---

## Procedure

1. **Decompose.** Break the target output into 2–5 independent components (e.g. setting, tone, protagonist, twist).
2. **Define candidates.** For each component, enumerate 3–6 candidate values.
3. **Segment the string.** Divide the random string into one segment per component. Equal-length segments are simplest; any non-overlapping partition works.
4. **Pick each component.** Apply Sum-Mod to each segment independently: `sum(ord(c) for c in segment) mod len(candidates)`.
5. **Assemble.** Combine the chosen values into the final output. Adjust wording for fluency as needed; the structure is fixed by the picks.

The number of distinct possible outputs equals the product of candidate-list lengths. Four components with four candidates each yield 256 possible outputs from the same prompt.

---

## Worked example: three-line horror story

**Components and candidates:**

| Component | Candidates (0–3) |
|-----------|-----------------|
| setting | abandoned lighthouse / locked hospital ward / flooded subway tunnel / overgrown carnival |
| ominous_object | a photograph dated tomorrow / a child's music box / a mirror showing yesterday / a phone with no signal |
| twist | it shows me still standing there / the melody is my own lullaby / the reflection mouths a warning / the last message is from me |

**String:** `zT2!mX5%pL$kQw7RbN`

Divide into three equal segments (6 chars each, with 2 left over absorbed into the last):
- Segment A: `zT2!mX`
- Segment B: `5%pL$k`
- Segment C: `Qw7RbN`

**Segment A** (setting):
```text
ord: z=122, T=84, 2=50, !=33, m=109, X=88 → sum=486
486 mod 4 = 2 → setting = "flooded subway tunnel"
```

**Segment B** (ominous_object):
```text
ord: 5=53, %=37, p=112, L=76, $=36, k=107 → sum=421
421 mod 4 = 1 → object = "a child's music box"
```

**Segment C** (twist):
```text
ord: Q=81, w=119, 7=55, R=82, b=98, N=78 → sum=513
513 mod 4 = 1 → twist = "the melody is my own lullaby"
```

**Assembled answer:**

```text
The maintenance crew abandoned the subway tunnel in 1987, but the trains still run at midnight.
On the flooded platform sits a child's music box, wound tight, turning on its own.
When I press my ear to the tile, the melody it plays is my own lullaby.
```

---

## Worked example: one-sentence New Year wish

**Components and candidates:**

| Component | Candidates (0–3) |
|-----------|-----------------|
| emotion | joyful / bold / quiet / unstoppable |
| object | success / adventures / connections / discoveries |
| modifier | beyond measure / in every season / against the odds / one step at a time |

**String:** `P9@rV!wK3$mQ#nXb`

Segments (5–6 chars each):
- Segment A: `P9@rV!` (emotion)
- Segment B: `wK3$mQ` (object)
- Segment C: `#nXb` (modifier)

**Segment A** (emotion):
```text
ord: P=80, 9=57, @=64, r=114, V=86, !=33 → sum=434
434 mod 4 = 2 → emotion = "quiet"
```

**Segment B** (object):
```text
ord: w=119, K=75, 3=51, $=36, m=109, Q=81 → sum=471
471 mod 4 = 3 → object = "discoveries"
```

**Segment C** (modifier):
```text
ord: #=35, n=110, X=88, b=98 → sum=331
331 mod 4 = 3 → modifier = "one step at a time"
```

**Assembled answer:**

```text
May the new year bring you quiet discoveries, one step at a time.
```

---

## Notes

- Segment length need not be equal, but segments must not overlap.
- If a component has only 2 candidates, Sum-Mod with N=2 is equivalent to a fair coin.
- Wording adjustments (articles, conjunctions, punctuation) for fluency do not change the structure; the picked values remain fixed.
- Generate one random string per full output, not one string per component.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.

