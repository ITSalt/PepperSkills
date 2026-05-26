# Conditional Modules — detection and embedding

Four conditional modules extend the base CRAFT+ prompt when specific triggers fire. Each module has bilingual (RU + EN) trigger phrases, an embeddable block (in English, inserted before OUTPUT_FORMAT in the prompt), and target-model-specific user_instructions.

## Contents

- Module A. Fact-checking
- Module B. Python / Code Execution
- Module C. SSoT (Creativity Protocol)
- Module D. Multi-modal Input
- Detection pipeline (Step 4.5 of workflow)

---

## Module A. Fact-checking

### Triggers (any one fires the module)

- Request contains dates, names of real people/companies, events, statistics, prices, "current/now/today/latest"
- Task type: research, news summary, market analysis, biographical, regulatory/legal info, medical info
- Bilingual trigger words:
  - **EN:** "facts", "data", "research shows", "statistics", "actual", "latest", "current", "as of today"
  - **RU:** «факты», «данные», «исследование показывает», «по статистике», «актуально», «текущий», «последний», «сейчас», «сегодня»

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
| claude | Включи Web Search в настройках чата (иконка глобуса) перед отправкой. | Enable Web Search in chat settings (globe icon) before sending. |
| gpt | Включи Web Search в режиме сообщения перед отправкой. | Enable Web Search in message mode before sending. |
| gemini | По умолчанию использует Google Search — дополнительных действий не требуется. | Uses Google Search by default — no additional setup needed. |
| deepseek-chat | На deepseek.com нажми кнопку 'Search' слева от поля ввода. | On deepseek.com click 'Search' button to the left of the input field. |
| universal | Убедись, что в выбранной модели включён поиск по интернету. | Ensure web search is enabled in your chosen model. |

---

## Module B. Python / Code Execution

### Triggers (any one)

- Calculations, statistics, data aggregation, transformations with >5 operations
- CSV / JSON / Excel / large tables
- Financial modeling, simulations, metrics
- Bilingual trigger words:
  - **EN:** "calculate", "compute", "process data", "transform", "aggregate", "generate N records" (N>10), "analyze dataset"
  - **RU:** «посчитай», «вычисли», «обработай данные», «преобразуй», «сравни значения», «сгенерируй N записей» (N>10), «проанализируй датасет», «агрегируй»

**NOT a trigger:** one-off simple operations (single formula, single number, "2+2", "convert 5kg to pounds").

### Embedded block

```
<computation_strategy>
This task involves calculations or data transformations. Strict priority:
1. If you have code execution / Python tool / Code Interpreter available: use it for ALL computations. Do not perform multi-step arithmetic mentally.
2. If you do NOT have code execution available: output a self-contained Python script that solves the task, plus a clear description of expected input data structure. Tell the user to paste it into Google Colab (https://colab.research.google.com), replace the data placeholder, and run.
Multi-step manual arithmetic has >30% error rate on frontier models — always prefer code execution.
</computation_strategy>
```

### user_instructions per target_model

| target_model | RU | EN |
|---|---|---|
| claude | Включи Analysis tool в настройках чата. | Enable Analysis tool in chat settings. |
| gpt | Перед отправкой убедись, что включён Code Interpreter (значок 🐍 / Advanced Data Analysis). | Ensure Code Interpreter is enabled (🐍 icon / Advanced Data Analysis) before sending. |
| gemini | Включи Code Execution в настройках Gemini. | Enable Code Execution in Gemini settings. |
| deepseek-chat | Code execution в чате DeepSeek недоступен — модель выдаст Python-скрипт для запуска в Google Colab. | Code execution unavailable in DeepSeek chat — the model will output a Python script for Google Colab. |
| universal | Если в твоей модели нет встроенного code execution, скопируй выданный Python-скрипт в Google Colab. | If your model lacks built-in code execution, copy the produced Python script into Google Colab. |

---

## Module C. SSoT (Creativity Protocol)

**Source:** Misaki & Akiba, "String Seed of Thought", arXiv:2510.21150, ICLR 2026.

**Purpose:** bypass RLHF mode collapse on creative tasks requiring genuine diversity across runs.

### Triggers (any one)

- N>1 distinct variants of one type requested ("5 headlines", "10 names", "several ideas", "variants", "brainstorm")
- Creative task with explicit diversity signal ("surprise me", "unconventional", "creative", "different", "non-repeating")
- Random selection / probability distribution / mixed-strategy games
- Stochastic agent simulation
- Bilingual trigger words:
  - **EN:** "5 different", "brainstorm", "variants", "options", "surprise me", "diverse", "distinct", "varied", "random", "pick one", "vary each time"
  - **RU:** «несколько вариантов», «разные», «варианты», «придумай N» (N>1), «удиви», «нестандартно», «креативно», «не повторяющиеся», «выбери случайно», «брейншторм»

**NOT a trigger:**
- Math, factual lookup, classification, translation, summarization, debug, single-correct-answer tasks
- Creative task WITHOUT multiplicity request (one headline, one story — without "surprise me")

### Embedded block

```
<creativity_protocol>
For each independent variant required, follow this protocol to ensure genuine diversity (bypasses RLHF mode collapse — Misaki & Akiba, ICLR 2026):

Step 1. Generate a fresh random string (16+ chars: mix uppercase letters, lowercase letters, digits, symbols) inside <random_string>...</random_string>. Generate internally — do NOT call external tools.

Step 2. Derive the variant deterministically inside <thinking>...</thinking>:
- Uniform choice among N options: result = sum(ord(c) for c in string) mod N
- Weighted distribution: rolling hash h = 0; for c in string: h = (h*31 + ord(c)) mod 10000; split [0, 10000) into intervals proportional to target weights; pick interval containing h
- Creative composition: split string into 2-5 non-overlapping segments; for each segment pick one component (setting / tone / character / twist / mood / etc.) from a candidate list via Sum-Mod; assemble

Step 3. Output ONLY the final variant inside <answer>...</answer>. No commentary.

Show all arithmetic explicitly. Generate a NEW string for EACH independent decision — reusing strings destroys statistical independence.
</creativity_protocol>
```

### user_instructions (same for all target_model)

- **RU:** Этот промпт использует технику SSoT для повышения разнообразия ответов. Модель будет показывать промежуточные расчёты (random_string и thinking) — это ожидаемое поведение, не баг. Финальный ответ — внутри тегов `<answer>`.
- **EN:** This prompt uses the SSoT technique to enhance response diversity. The model will show intermediate computations (random_string and thinking) — this is expected behavior, not a bug. Final answer is inside `<answer>` tags.

### When this module fires

Set `useSSOT = true` in the output (JSON field or visible Markdown section "📚 SSoT техника / SSoT technique" with the arXiv link: `arXiv:2510.21150 (ICLR 2026)`).

---

## Module D. Multi-modal Input

### Triggers

- User message has attached images / PDFs / documents (visible by API message structure or implied by user wording)
- Bilingual trigger words:
  - **EN:** "image", "picture", "photo", "screenshot", "PDF", "document", "file", "upload", "attachment", "describe what's in", "extract from PDF"
  - **RU:** «изображение», «картинка», «фото», «скриншот», «PDF», «документ», «файл», «загружу», «вложение», «опиши что на картинке», «извлеки текст из PDF»
- Visual content analysis request: "describe what's in the image", "extract text from PDF", "what's wrong with this layout"

### Embedded block

```
<multimodal_input>
This task involves image, PDF, or other non-text input. Strict rules:
- Reference each input file/image explicitly: "In the image..." or "On page 3 of the PDF..."
- Quote relevant text from documents using exact wording before analyzing
- For images: describe what you see in the relevant region BEFORE drawing conclusions
- For multi-page documents: cite page numbers
- Do not assume content not visible in the input — if unclear, mark as [UNCLEAR] or ask
- For tasks involving precise visual measurement (counting, alignment, layout): zoom mentally on the relevant region first
</multimodal_input>
```

### user_instructions

- **RU:** Прикрепи к промпту все упомянутые файлы / изображения / PDF одним сообщением вместе с промптом.
- **EN:** Attach all mentioned files / images / PDFs in the same message as the prompt.

---

## Detection pipeline (Step 4.5 of the workflow)

For each module in order: A → B → C → D, check the trigger list. Multiple modules can fire simultaneously (e.g., research task with calculations triggers both A and B).

Insertion order inside the prompt (before OUTPUT_FORMAT):
1. Multi-modal (if active)
2. Fact-checking (if active)
3. Computation strategy (if active)
4. Creativity protocol (if active)

This order matters: multi-modal context is established first, then research rules, then computation, then creativity — each subsequent module builds on the previous.
