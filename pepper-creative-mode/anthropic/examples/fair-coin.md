# Example: Fair Coin Flip (Sum-Mod)

This example demonstrates the Sum-Mod pattern applied to a fair 50/50 coin flip.

---

## User prompt

```text
Flip a fair coin and tell me the result.
```

---

## Claude response

```text
<random_string>7$Aq9!zR@k3mP#vX</random_string>
<thinking>
Pattern: Sum-Mod with N=2 (Heads=0, Tails=1).

Compute ord() for each character:
  7  -> 55
  $  -> 36
  A  -> 65
  q  -> 113
  9  -> 57
  !  -> 33
  z  -> 122
  R  -> 82
  @  -> 64
  k  -> 107
  3  -> 51
  m  -> 109
  P  -> 80
  #  -> 35
  v  -> 118
  X  -> 88

Sum = 55+36+65+113+57+33+122+82+64+107+51+109+80+35+118+88 = 1215

1215 mod 2 = 1

Mapping: 0->Heads, 1->Tails
Result index 1 -> Tails
</thinking>
<answer>Tails</answer>
```

---

## Explanation

The string `7$Aq9!zR@k3mP#vX` is 16 characters long and contains uppercase letters, lowercase letters, digits, and symbols — satisfying the hard rules. The arithmetic is shown in full so the result is verifiable. The `<answer>` section contains only the final output.

Because N=2, this is equivalent to checking whether the sum is even (Heads) or odd (Tails). The model commits to the string before the arithmetic, which breaks the pattern-completion path that biases bare "flip a coin" prompts.

Note that the unbiased coin is the *weakest* case for this technique — it is the one setting where the paper reports a model getting worse (QwQ-32B, 2.43 → 3.39 ×10⁻³). The technique earns its keep on skewed targets; see [`biased-decision.md`](biased-decision.md).

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
