# Conditional Modules — detection and embedding

Four conditional modules extend the base CRAFT+ prompt when specific triggers fire. Each
module has bilingual (RU + EN) trigger phrases, an embeddable block (in English, inserted
before OUTPUT_FORMAT in the prompt), and target-model-specific user_instructions.

Model identifiers and UI paths referenced below come from `target-models.md`, which is the
single source of truth for anything version-dependent. UI instructions are phrased
mechanism-first with the concrete path in parentheses, so they survive an interface change.

## Contents

- Module A. Fact-checking
- Module B. Python / Code Execution
- Module C. SSoT (Creativity Protocol)
- Module D. Multi-modal Input
- Detection pipeline (Step 4.5 of workflow)

---

## Module A. Fact-checking

### Triggers (any one fires the module)

- Request contains dates, names of real people/companies, events, statistics, prices,
  "current/now/today/latest"
- Task type: research, news summary, market analysis, biographical, regulatory/legal info,
  medical info
- Bilingual trigger words:
  - **EN:** "facts", "data", "research shows", "statistics", "actual", "latest", "current",
    "as of today"
  - **RU:** «факты», «данные», «исследование показывает», «по статистике», «актуально»,
    «текущий», «последний», «сейчас», «сегодня»

### Embedded block (insert into prompt before OUTPUT_FORMAT)

```
<fact_checking>
This task involves factual claims that must be verified (dates, names, events, statistics, current state). Strict rules:
- If you have web search / browsing tool available: use it to verify every factual claim before stating. Cite sources inline.
- If you do NOT have web search available: do NOT fabricate. Output exactly this disclaimer instead: "I cannot verify facts without web access for this task. Please verify independently or rerun with a web-enabled model."
- Never present unverified claims as confirmed facts. Mark uncertain items as [UNVERIFIED].
</fact_checking>
```

### user_instructions per target_model (output in USER_LANG)

| target_model | RU | EN |
|---|---|---|
| claude | Включи веб-поиск в меню инструментов перед отправкой (иконка-слайдер слева внизу поля ввода). | Enable web search in the tool menu before sending (slider icon at the bottom left of the composer). |
| gpt | Включи веб-поиск в меню инструментов перед отправкой. | Enable web search in the tool menu before sending. |
| gemini | По умолчанию использует Google Search — дополнительных действий не требуется. | Uses Google Search by default — no additional setup needed. |
| deepseek | Включи поиск перед отправкой (на deepseek.com — кнопка Search рядом с полем ввода). | Enable search before sending (on deepseek.com — the Search button next to the input field). |
| universal | Убедись, что в выбранной модели включён поиск по интернету. | Ensure web search is enabled in your chosen model. |

---

## Module B. Python / Code Execution

### Triggers (any one)

- Calculations, statistics, data aggregation, transformations with >5 operations
- CSV / JSON / Excel / large tables
- Financial modeling, simulations, metrics
- Bilingual trigger words:
  - **EN:** "calculate", "compute", "process data", "transform", "aggregate",
    "generate N records" (N>10), "analyze dataset"
  - **RU:** «посчитай», «вычисли», «обработай данные», «преобразуй», «сравни значения»,
    «сгенерируй N записей» (N>10), «проанализируй датасет», «агрегируй»

**NOT a trigger:** one-off simple operations (single formula, single number, "2+2",
"convert 5kg to pounds").

### Embedded block

```
<computation_strategy>
This task involves calculations or data transformations. Strict priority:
1. If you have code execution / Python tool / Code Interpreter available: use it for ALL computations. Do not perform multi-step arithmetic in prose.
2. If you do NOT have code execution available: output a self-contained Python script that solves the task, plus a clear description of expected input data structure. Tell the user to paste it into Google Colab (https://colab.research.google.com), replace the data placeholder, and run.
Prefer code execution for three reasons: the result is reproducible and inspectable, it scales past the volume of data that fits in a response, and it removes error propagation through long chains of dependent steps.
</computation_strategy>
```

> **Why no error-rate figure here.** Earlier versions of this module claimed multi-step
> mental arithmetic fails at a specific rate on frontier models. That figure had no source
> and current benchmarks contradict it — leading models now score in the high 90s to 100%
> on multi-step arithmetic. The reasons above hold regardless of raw arithmetic accuracy.

### user_instructions per target_model

| target_model | RU | EN |
|---|---|---|
| claude | Включи инструмент исполнения кода (анализ) в меню инструментов. | Enable the code-execution (analysis) tool in the tool menu. |
| gpt | Убедись, что доступно исполнение кода (Code Interpreter / анализ данных), прежде чем отправлять. | Make sure code execution (Code Interpreter / data analysis) is available before sending. |
| gemini | Включи Code Execution в настройках Gemini. | Enable Code Execution in Gemini settings. |
| deepseek | Если в твоём клиенте нет исполнения кода — модель выдаст Python-скрипт для запуска в Google Colab. | If your client has no code execution, the model will output a Python script to run in Google Colab. |
| universal | Если в твоей модели нет встроенного code execution, скопируй выданный Python-скрипт в Google Colab. | If your model lacks built-in code execution, copy the produced Python script into Google Colab. |

---

## Module C. SSoT (Creativity Protocol)

**Source:** Misaki & Akiba, "String Seed of Thought",
[arXiv:2510.21150](https://arxiv.org/abs/2510.21150), ICLR 2026.

**Purpose:** raise genuine diversity across independent runs on creative tasks, and improve
adherence to a stated target distribution on stochastic ones.

The sibling skill `pepper-creative-mode` implements the same technique in depth and its
claims were audited against the paper's full text. The constraints below are carried over
from that audit — in particular the temperature requirement and the measured string length,
both of which were missing from earlier versions of this module.

### Triggers (any one)

- N>1 distinct variants of one type requested ("5 headlines", "10 names", "several ideas",
  "variants", "brainstorm")
- Creative task with explicit diversity signal ("surprise me", "unconventional", "creative",
  "different", "non-repeating")
- Random selection / probability distribution / mixed-strategy games
- Stochastic agent simulation
- Bilingual trigger words:
  - **EN:** "5 different", "brainstorm", "variants", "options", "surprise me", "diverse",
    "distinct", "varied", "random", "pick one", "vary each time"
  - **RU:** «несколько вариантов», «разные», «варианты», «придумай N» (N>1), «удиви»,
    «нестандартно», «креативно», «не повторяющиеся», «выбери случайно», «брейншторм»

**NOT a trigger:**
- Math, factual lookup, classification, translation, summarization, debug,
  single-correct-answer tasks
- Creative task WITHOUT multiplicity request (one headline, one story — without
  "surprise me")

**Hard precondition:** the technique needs stochastic decoding. At `temperature = 0`, or
with a pinned decoding seed, the "random" string is itself deterministic and every run
returns the same answer — the protocol becomes an expensive no-op. If the user has stated
they run at temperature 0, do not embed this module; log the reason in `assumptions`.

### Embedded block

```
<creativity_protocol>
For each independent variant required, follow this protocol to raise diversity across runs (String Seed of Thought — Misaki & Akiba, ICLR 2026):

Step 1. Generate a fresh random string of 24-32 characters (mix uppercase letters, lowercase letters, digits, symbols) inside <random_string>...</random_string>. Generate internally — do NOT call external tools.

Step 2. Derive the variant deterministically inside <thinking>...</thinking>:
- Uniform choice among N options: result = sum(ord(c) for c in string) mod N
- Weighted distribution: rolling hash h = 0; for c in string: h = (h*31 + ord(c)) mod 10000; split [0, 10000) into intervals proportional to target weights; pick interval containing h
- Creative composition: split string into 2-5 non-overlapping segments; for each segment pick one component (setting / tone / character / twist / mood / etc.) from a candidate list via Sum-Mod; assemble

Step 3. Output ONLY the final variant inside <answer>...</answer>. No commentary.

Show all arithmetic explicitly. Generate a NEW string for EACH independent decision — reusing strings destroys statistical independence.
</creativity_protocol>
```

**String length.** 24–32 characters is the measured sweet spot: divergence from the target
distribution bottoms out around n≈24 and rises again past ~48 (paper Table 7). Earlier
versions of this module said "16+", which is the floor, not the optimum.

### user_instructions (same for all target_model)

- **RU:** Этот промпт использует технику SSoT для повышения разнообразия ответов. Нужна
  ненулевая температура — при `temperature = 0` приём не работает. Модель будет показывать
  промежуточные расчёты (random_string и thinking) — это ожидаемое поведение, не баг.
  Финальный ответ — внутри тегов `<answer>`.
- **EN:** This prompt uses the SSoT technique to enhance response diversity. It needs
  non-zero temperature — at `temperature = 0` the technique does nothing. The model will
  show intermediate computations (random_string and thinking) — this is expected behavior,
  not a bug. Final answer is inside `<answer>` tags.

### When this module fires

Set `useSSOT = true` in the output (JSON field, or the visible Markdown section
"📚 SSoT техника / SSoT technique" with the arXiv link).

---

## Module D. Multi-modal Input

### Triggers

- User message has attached images / PDFs / documents (visible by API message structure or
  implied by user wording)
- Bilingual trigger words:
  - **EN:** "image", "picture", "photo", "screenshot", "PDF", "document", "file", "upload",
    "attachment", "describe what's in", "extract from PDF"
  - **RU:** «изображение», «картинка», «фото», «скриншот», «PDF», «документ», «файл»,
    «загружу», «вложение», «опиши что на картинке», «извлеки текст из PDF»
- Visual content analysis request: "describe what's in the image", "extract text from PDF",
  "what's wrong with this layout"

### Embedded block

```
<multimodal_input>
This task involves image, PDF, or other non-text input. Strict rules:
- Reference each input file/image explicitly: "In the image..." or "On page 3 of the PDF..."
- Quote relevant text from documents using exact wording before analyzing
- For images: describe what you see in the relevant region BEFORE drawing conclusions
- For multi-page documents: cite page numbers
- Do not assume content not visible in the input — if unclear, mark as [UNCLEAR] or ask
</multimodal_input>
```

### user_instructions

- **RU:** Прикрепи к промпту все упомянутые файлы / изображения / PDF одним сообщением
  вместе с промптом.
- **EN:** Attach all mentioned files / images / PDFs in the same message as the prompt.

For `target_model = gemini`, add: input image resolution is a settable parameter
(`media_resolution`) that trades tokens for recognition accuracy — worth raising when the
task depends on reading text inside an image. See `target-models.md`.

---

## Detection pipeline (Step 4.5 of the workflow)

For each module in order: A → B → C → D, check the trigger list. Multiple modules can fire
simultaneously (e.g., research task with calculations triggers both A and B).

Insertion order inside the prompt (before OUTPUT_FORMAT):
1. Multi-modal (if active)
2. Fact-checking (if active)
3. Computation strategy (if active)
4. Creativity protocol (if active)

This order matters: multi-modal context is established first, then research rules, then
computation, then creativity — each subsequent module builds on the previous.
