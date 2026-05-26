# `pepper-creative-mode`

Портативный скилл, который включает в LLM **честное сэмплирование из заданного распределения** и **разнообразную генерацию** через инструкцию самой сгенерить случайную строку и использовать её как seed для решения.

Техника: **«String Seed of Thought»** — Misaki & Akiba, Sakana AI, ICLR 2026.
[Статья](https://arxiv.org/abs/2510.21150) · [Страница проекта](https://pub.sakana.ai/ssot/)

## Какую проблему решает

Frontier-модели системно врут, когда их просят сгенерить стохастический ответ:

- «Подбрось честную монетку» 1000 раз — получается 78/22 вместо 50/50
- Творческие промпты схлопываются к узкому набору вариантов (все басни про зайца с черепахой)
- В играх со смешанной стратегией модель выдаёт паттерны, которые легко эксплуатируются

Скилл заставляет модель сгенерить случайную строку «в голове», а потом детерминистически отобразить её в ответ через `sum(ASCII) mod N` или rolling-hash. Никаких внешних инструментов, никаких PRNG — только изменение промпта.

## Два режима

| Режим | Когда применять |
|-------|-----------------|
| **PIF** — Probabilistic Instruction Following | Сэмплирование из распределения: coin flip, взвешенный выбор, Nash equilibrium, симуляция агентов |
| **DAG** — Diversity-Aware Generation | Творчество, брейнсторм, генерация вариантов, симуляция персон |

## Выбери платформу

| Платформа | Файл |
|-----------|------|
| Anthropic — Claude.ai / Claude Code / API | [`anthropic/SKILL.md`](./anthropic/SKILL.md) |
| OpenAI — API / Custom GPT | [`openai/system-prompt.md`](./openai/system-prompt.md) |
| OpenAI — ChatGPT Custom Instructions (компактная версия) | [`openai/custom-instructions.md`](./openai/custom-instructions.md) |

## Когда НЕ использовать

Не применяйте `pepper-creative-mode` к задачам с единственным правильным ответом: математика, фактология, отладка кода, классификация, перевод. Это добавляет шум и мешает модели.

## Границы применимости

- Лучше всего на reasoning-моделях — DeepSeek-R1 почти догоняет настоящий PRNG на бенчмарках из статьи
- Хуже — на маленьких моделях, которые не умеют сами выполнить modulo-арифметику
- NoveltyBench: выше Distinct, сопоставимый Utility

## Версии документации

- English — [`README.md`](./README.md)
- Русский — этот файл

## Цитирование

```bibtex
@inproceedings{misaki2026ssot,
  title={String Seed of Thought: Prompting LLMs for Distribution-Faithful and Diverse Generation},
  author={Misaki, Kou and Akiba, Takuya},
  booktitle={International Conference on Learning Representations (ICLR)},
  year={2026}
}
```

## Лицензия

[MIT](../LICENSE) © ITSalt.
