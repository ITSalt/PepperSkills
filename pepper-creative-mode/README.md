# `pepper-creative-mode`

A portable skill that unlocks **distribution-faithful sampling** and **diverse generation** in LLMs by instructing them to seed their own decisions with a self-generated random string.

Technique: **"String Seed of Thought"** — Misaki & Akiba, Sakana AI, ICLR 2026.
[Paper](https://arxiv.org/abs/2510.21150) · [Project page](https://pub.sakana.ai/ssot/)

## What it solves

Frontier LLMs show systematic bias when they must produce stochastic output:

- Asked to sample from a stated distribution, models miss it — badly on skewed targets. On a 30/70 split, deepseek-v3 scores a JS divergence of 111.45 ×10⁻³ against 1.93 for a real PRNG
- Creative prompts collapse to a narrow set of recurring variants
- Mixed-strategy game play produces exploitable patterns

This skill makes the model generate a random string in its head, then deterministically map that string to the answer through sum-mod or rolling-hash arithmetic. No tools, no PRNGs — only a prompt change.

## Two modes

| Mode | Use case |
|------|----------|
| **PIF** — Probabilistic Instruction Following | Sampling from a given distribution: coin flips, weighted choices, Nash-equilibrium play, agent simulation |
| **DAG** — Diversity-Aware Generation | Creative writing, brainstorming, variant generation, persona simulation |

## Pick your platform

| Platform | File |
|----------|------|
| Anthropic — Claude.ai / Claude Code / API | [`anthropic/SKILL.md`](./anthropic/SKILL.md) |
| OpenAI — API / Custom GPT | [`openai/system-prompt.md`](./openai/system-prompt.md) |
| OpenAI — ChatGPT Custom Instructions (compact) | [`openai/custom-instructions.md`](./openai/custom-instructions.md) |

## When NOT to use

Do not apply `pepper-creative-mode` to tasks with a single correct answer: math, factual lookup, code debugging, classification, translation. It adds noise without benefit and can distract the model.

## Effectiveness

Numbers below are from the paper (arXiv:2510.21150); JS divergence in units of 10⁻³, lower is better.

- **Strongest on skewed distributions** — 85–99% reduction in JS divergence across all five models tested
- **Mixed on an unbiased coin** — from −92% (deepseek-r1) to **+40%** (QwQ-32B, which was already near-PRNG at baseline). If the model is already well calibrated on a binary choice, skip it
- **Best on reasoning models** — deepseek-r1 reaches 3.03 against a PRNG reference of 1.85
- **Harmful on non-reasoning models** — Qwen3-4B degrades by 436%, while the *thinking* variant of the same 4B model improves by 88%. Reasoning capability is the dividing line, not model size
- **NoveltyBench** — Distinct 4.70 → 6.19, Utility 5.17 → 5.92. Worth knowing: simply setting `temperature = 1.0` reaches Distinct 5.57 at Utility 6.03, so most of the diversity gain is available without the protocol
- **Beats external randomness on creative tasks** — a real RNG tool call scores 5.72 (5.33) on the same benchmark, below this technique's 6.19 (5.92)

## Requirements and caveats

- **Needs stochastic decoding.** At `temperature = 0` or with a pinned seed, the "random" string is deterministic and the technique becomes a no-op. The paper runs at `T = 0.6`–`1.0`
- **Independence needs fresh context.** The paper's measurements use independent calls. Ten coin flips in one conversation are not independent samples
- The diversity half of the technique is contested on non-reasoning models — see [`when-not-to-use.md`](./anthropic/references/when-not-to-use.md)

## Language versions

- English — this file
- Русский — [`README.ru.md`](./README.ru.md)

## Citation

```bibtex
@inproceedings{misaki2026ssot,
  title={String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation},
  author={Misaki, Kou and Akiba, Takuya},
  booktitle={International Conference on Learning Representations (ICLR)},
  year={2026}
}
```

## License

[MIT](../LICENSE) © ITSalt.
