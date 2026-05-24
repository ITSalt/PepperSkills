# `itsalt:creative-mode`

A portable skill that unlocks **distribution-faithful sampling** and **diverse generation** in LLMs by instructing them to seed their own decisions with a self-generated random string.

Technique: **"String Seed of Thought"** — Misaki & Akiba, Sakana AI, ICLR 2026.
[Paper](https://arxiv.org/abs/2510.21150) · [Project page](https://pub.sakana.ai/ssot/)

## What it solves

Frontier LLMs show systematic bias when they must produce stochastic output:

- "Flip a fair coin" often lands ~78/22 instead of ~50/50
- Creative prompts collapse to a narrow set of variants (every fable is tortoise-and-hare)
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

Do not apply `itsalt:creative-mode` to tasks with a single correct answer: math, factual lookup, code debugging, classification, translation. It adds noise without benefit and can distract the model.

## Effectiveness

- Best on reasoning models — DeepSeek-R1 approaches true PRNG quality on the paper's benchmarks
- Weaker on small models that struggle to execute modulo arithmetic autonomously
- NoveltyBench: higher Distinct score, competitive Utility

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
