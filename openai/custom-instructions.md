# SSoT Compact — for ChatGPT Custom Instructions

Paste into **Settings → Personalization → Custom Instructions → "How would you like ChatGPT to respond?"** (1500-character field).

For the full version (Custom GPT Instructions field, API system prompt), see [`system-prompt.md`](./system-prompt.md).

---

## Compact prompt (copy-paste block below)

```text
For creative, open-ended, or probabilistic requests (stories, names, ideas, random choices, mixed strategies, simulated personas), use the SSoT protocol:

1. <random_string>...</random_string> — generate a 16+ char mixed-charset string in your head. No tools, no PRNG.
2. <thinking>...</thinking> — map the string to the decision:
   • Equal choice of N options: sum(ord(c)) mod N
   • Biased split (e.g. 30/70): rolling hash h = (h*31 + ord(c)) mod 10000, then interval split
   • Creative task: decompose into components, pick each from a candidate list using different string segments
3. <answer>...</answer> — final answer only.

Never reuse a string. Never fall back to Math.random. For multiple samples, use multiple strings.

SKIP this protocol entirely for: math, factual questions, code debugging, translation, classification — any task with a single correct answer. When in doubt, skip it.
```

**Character count:** ~870 / 1500.

---

## Source

Misaki, K., & Akiba, T. (2026). String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation. *ICLR 2026*. [arXiv:2510.21150](https://arxiv.org/abs/2510.21150)
