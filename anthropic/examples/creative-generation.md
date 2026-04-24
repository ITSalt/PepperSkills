# Example: Creative Generation (Decision Cascade)

This example shows the same prompt run three times. Each run produces a different `<random_string>`, which drives a different set of component picks, producing three distinct outputs.

---

## User prompt (all three runs)

```text
Write a one-sentence New Year wish I can send to a colleague.
```

---

## Components and candidates

| Component | Index | Candidates |
|-----------|-------|------------|
| emotion | 0 | joyful |
| | 1 | bold |
| | 2 | quiet |
| | 3 | unstoppable |
| object | 0 | success |
| | 1 | adventures |
| | 2 | connections |
| | 3 | discoveries |
| modifier | 0 | beyond measure |
| | 1 | in every season |
| | 2 | against the odds |
| | 3 | one step at a time |

String segmentation: 16-character string split into segments of 5, 5, and 6 characters.

---

## Run 1

```text
<random_string>P9@rV!wK3$mQ#nXb</random_string>
<thinking>
Segments: A="P9@rV!", B="wK3$mQ", C="#nXb__" (last 4 chars: #nXb)

Segment A (emotion, N=4):
  P=80, 9=57, @=64, r=114, V=86, !=33 -> sum=434
  434 mod 4 = 2 -> emotion = "quiet"

Segment B (object, N=4):
  w=119, K=75, 3=51, $=36, m=109, Q=81 -> sum=471
  471 mod 4 = 3 -> object = "discoveries"

Segment C (modifier, N=4):
  #=35, n=110, X=88, b=98 -> sum=331
  331 mod 4 = 3 -> modifier = "one step at a time"

Assembly: "May the new year bring you quiet discoveries, one step at a time."
</thinking>
<answer>May the new year bring you quiet discoveries, one step at a time.</answer>
```

---

## Run 2

```text
<random_string>m!7Zq$Lx2#pK@9vR</random_string>
<thinking>
Segments: A="m!7Zq$", B="Lx2#pK", C="@9vR__" (last 4 chars: @9vR)

Segment A (emotion, N=4):
  m=109, !=33, 7=55, Z=90, q=113, $=36 -> sum=436
  436 mod 4 = 0 -> emotion = "joyful"

Segment B (object, N=4):
  L=76, x=120, 2=50, #=35, p=112, K=75 -> sum=468
  468 mod 4 = 0 -> object = "success"

Segment C (modifier, N=4):
  @=64, 9=57, v=118, R=82 -> sum=321
  321 mod 4 = 1 -> modifier = "in every season"

Assembly: "May the new year bring you joyful success, in every season."
</thinking>
<answer>May the new year bring you joyful success, in every season.</answer>
```

---

## Run 3

```text
<random_string>4&Tn%rW8!kB$xMqH</random_string>
<thinking>
Segments: A="4&Tn%r", B="W8!kB$", C="xMqH__" (last 4 chars: xMqH)

Segment A (emotion, N=4):
  4=52, &=38, T=84, n=110, %=37, r=114 -> sum=435
  435 mod 4 = 3 -> emotion = "unstoppable"

Segment B (object, N=4):
  W=87, 8=56, !=33, k=107, B=66, $=36 -> sum=385
  385 mod 4 = 1 -> object = "adventures"

Segment C (modifier, N=4):
  x=120, M=77, q=113, H=72 -> sum=382
  382 mod 4 = 2 -> modifier = "against the odds"

Assembly: "May the new year bring you unstoppable adventures, against the odds."
</thinking>
<answer>May the new year bring you unstoppable adventures, against the odds.</answer>
```

---

## Summary

| Run | String | emotion | object | modifier | Output |
|-----|--------|---------|--------|----------|--------|
| 1 | `P9@rV!wK3$mQ#nXb` | quiet | discoveries | one step at a time | "May the new year bring you quiet discoveries, one step at a time." |
| 2 | `m!7Zq$Lx2#pK@9vR` | joyful | success | in every season | "May the new year bring you joyful success, in every season." |
| 3 | `4&Tn%rW8!kB$xMqH` | unstoppable | adventures | against the odds | "May the new year bring you unstoppable adventures, against the odds." |

Three distinct strings produce three meaningfully different outputs from the same prompt. The candidate space (4 x 4 x 4 = 64 combinations) ensures substantial variety across runs.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
