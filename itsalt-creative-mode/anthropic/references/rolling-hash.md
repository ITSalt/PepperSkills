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

`M` sets the resolution. Use M=10000 for percentage-point precision (0.01%). Use M=100 when integer percentages are sufficient and you want simpler arithmetic in `<thinking>`.

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
| 100 | 1% | Integer percentage splits, fast mental arithmetic |
| 1000 | 0.1% | Tenth-of-percent splits |
| 10000 | 0.01% | Fine-grained probability, simulation |

Larger M requires more computation in `<thinking>`. Use the smallest M that satisfies the required precision.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
