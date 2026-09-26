# Example: Biased Coin (Rolling Hash)

This example demonstrates the Rolling Hash pattern applied to a 30/70 biased coin.

---

## User prompt

```text
Flip a biased coin that lands heads 30% of the time and tails 70% of the time.
```

---

## Claude response

```text
<random_string>K#7mRq2$vXpL9@!t</random_string>
<thinking>
Pattern: Rolling Hash with M=100.
Intervals: Heads=[0,30), Tails=[30,100).

Compute h iteratively: h = (h*31 + ord(c)) mod 100

  c='K': h = (0*31   + 75) mod 100 = 75
  c='#': h = (75*31  + 35) mod 100 = (2325+35) mod 100 = 2360 mod 100 = 60
  c='7': h = (60*31  + 55) mod 100 = (1860+55) mod 100 = 1915 mod 100 = 15
  c='m': h = (15*31  +109) mod 100 = (465+109) mod 100 = 574  mod 100 = 74
  c='R': h = (74*31  + 82) mod 100 = (2294+82) mod 100 = 2376 mod 100 = 76
  c='q': h = (76*31  +113) mod 100 = (2356+113) mod 100 = 2469 mod 100 = 69
  c='2': h = (69*31  + 50) mod 100 = (2139+50) mod 100 = 2189 mod 100 = 89
  c='$': h = (89*31  + 36) mod 100 = (2759+36) mod 100 = 2795 mod 100 = 95
  c='v': h = (95*31  +118) mod 100 = (2945+118) mod 100 = 3063 mod 100 = 63
  c='X': h = (63*31  + 88) mod 100 = (1953+88) mod 100 = 2041 mod 100 = 41
  c='p': h = (41*31  +112) mod 100 = (1271+112) mod 100 = 1383 mod 100 = 83
  c='L': h = (83*31  + 76) mod 100 = (2573+76) mod 100 = 2649 mod 100 = 49
  c='9': h = (49*31  + 57) mod 100 = (1519+57) mod 100 = 1576 mod 100 = 76
  c='@': h = (76*31  + 64) mod 100 = (2356+64) mod 100 = 2420 mod 100 = 20
  c='!': h = (20*31  + 33) mod 100 = (620+33) mod 100  = 653  mod 100 = 53
  c='t': h = (53*31  +116) mod 100 = (1643+116) mod 100 = 1759 mod 100 = 59

Final h = 59

59 is in [30, 100) -> Tails
</thinking>
<answer>Tails</answer>
```

---

## Explanation

The Rolling Hash distributes values across `[0, 100)` with much better coverage than Sum-Mod for biased distributions. The interval `[0, 30)` represents exactly 30% of outcomes (Heads) and `[30, 100)` represents 70% (Tails). Because `h=59` falls in the larger interval, the result is Tails.

Using `M=100` allows direct mapping of integer percentages to interval boundaries. For finer resolution (e.g. 17.5% vs 82.5%), use `M=10000` and compute `floor(0.175 * 10000) = 1750` as the boundary.

The string `K#7mRq2$vXpL9@!t` is 16 characters with mixed character classes, satisfying the hard rules.

---

Source: Misaki, K., & Akiba, T. "String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation." arXiv:2510.21150. Accepted at ICLR 2026.
