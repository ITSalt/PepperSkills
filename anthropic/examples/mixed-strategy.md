# Example: Rock-Paper-Scissors Nash Equilibrium (Sum-Mod, N=3)

This example demonstrates Sum-Mod with N=3, picking a Rock-Paper-Scissors move uniformly at random to approximate Nash equilibrium play (1/3 probability for each move).

---

## User prompt

```text
I am playing Rock-Paper-Scissors against an adversarial opponent who will try to exploit any pattern in my moves. Pick my next move using Nash equilibrium (equal probability for each option).
```

---

## Claude response

```text
<random_string>9pLmQ!7xR#vK2$bY</random_string>
<thinking>
Pattern: Sum-Mod with N=3.
Mapping: 0->Rock, 1->Paper, 2->Scissors.

Compute ord() for each character:
  9  -> 57
  p  -> 112
  L  -> 76
  m  -> 109
  Q  -> 81
  !  -> 33
  7  -> 55
  x  -> 120
  R  -> 82
  #  -> 35
  v  -> 118
  K  -> 75
  2  -> 50
  $  -> 36
  b  -> 98
  Y  -> 89

Sum = 57+112+76+109+81+33+55+120+82+35+118+75+50+36+98+89 = 1226

1226 mod 3 = ?
1226 / 3 = 408 remainder 2
1226 = 408*3 + 2 -> 1226 mod 3 = 2

Mapping: 2 -> Scissors
</thinking>
<answer>Scissors</answer>
```

---

## Explanation

Nash equilibrium for Rock-Paper-Scissors requires each move to be chosen with equal probability (1/3 each). Sum-Mod with N=3 achieves this: the sum of ordinals of a randomly generated string is approximately uniformly distributed modulo 3, so each outcome occurs with probability close to 1/3.

Without SSoT, models tend to favor specific moves due to RLHF-induced patterns — for example, "Rock" is a common default because it appears frequently in training data in positions of strength or first-listing. The SSoT string breaks this pattern by committing the model to an unpredictable intermediate value before the decision is made.

Verification of the arithmetic:

```python
s = "9pLmQ!7xR#vK2$bY"
total = sum(ord(c) for c in s)  # = 1226
result = total % 3               # = 2
moves = ["Rock", "Paper", "Scissors"]
print(moves[result])             # Scissors
```

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
