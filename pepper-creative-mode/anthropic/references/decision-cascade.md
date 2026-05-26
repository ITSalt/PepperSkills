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
