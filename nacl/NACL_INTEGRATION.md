# NACL_INTEGRATION — nacl-ssot

## Status

Phase 2A — authored from inspection of the live NaCl repository at
`/Users/maxnikitin/projects/nacl/`. Three skills were examined:
`nacl-ba-analyze` (BA phase), `nacl-sa-architect` (SA phase), `nacl-tl-dev` (TL phase).

---

## Role in the NaCl Framework

`nacl-ssot` is a **cross-cutting modifier skill**. It does not belong to a single pipeline
phase. Instead, it augments individual generative steps inside other skills when those steps
require either distribution-faithful sampling or meaningful diversity across repeated invocations.

In NaCl terminology this is an **aspect**: a reusable behavioral contract that can be composed
into any skill phase by referencing it in that phase's instructions.

---

## Phases That Benefit

### BA Phase (`nacl-ba-*`)

| Skill | Where SSoT adds value |
|---|---|
| `nacl-ba-full` | Generating diverse example scenarios or personas for process documentation |
| `nacl-ba-import-doc` | Synthesizing varied test stakeholder names and role descriptions |
| `nacl-ba-glossary` | Picking illustrative examples when multiple equally valid ones exist |
| `nacl-ba-context` | Sampling from a set of plausible system-context descriptions |

BA skills produce Russian-language artifacts. `nacl-ssot` is language-agnostic — the `<answer>`
block inherits whatever language the calling skill operates in.

### SA Phase (`nacl-sa-*`)

| Skill | Where SSoT adds value |
|---|---|
| `nacl-sa-domain` | Generating diverse synthetic domain entity names during schema sketching |
| `nacl-sa-uc` | Selecting representative use-case actors from a candidate pool for examples |
| `nacl-sa-ui` | Proposing varied UI copy or placeholder text for wireframes |

### TL Phase (`nacl-tl-*`)

| Skill | Where SSoT adds value |
|---|---|
| `nacl-tl-dev-be` | Generating diverse synthetic test fixtures (names, IDs, amounts) |
| `nacl-tl-dev-fe` | Creating varied Storybook story props and mock user objects |
| `nacl-tl-qa` | Selecting a random test execution order for non-sequential suites |
| `nacl-tl-plan` | Breaking a tie between equally prioritized tasks when sequencing matters |

---

## Concrete Integration Example

### nacl-tl-dev-be: Diverse Synthetic Test Fixtures

`nacl-tl-dev-be` writes backend tests following TDD. During the RED phase it creates test
fixtures. Without SSoT, the model always generates the same handful of names and values, making
coverage appear broad while actually repeating the same data shape.

**Before (without SSoT):**

The model generates fixtures with predictable values — `"John Doe"`, `"test@example.com"`,
`amount: 100` — every time the same test suite is scaffolded.

**After (with SSoT applied to one fixture generation step):**

The skill's RED phase instruction reads:

> "When generating synthetic user fixtures for this test, apply SSoT Decision Cascade to pick
>  first name, last name domain, and account tier. See `/nacl-ssot` for the protocol."

The model then executes:

```
<random_string>9pLmQ!7xR#vK2$bYzT</random_string>
<thinking>
Components: [first_name, domain, tier]
Candidates:
  first_name ∈ {Alice, Bruno, Chiara, Dmitri}        — 4 options
  domain     ∈ {example.org, corp.io, labs.dev, test.net} — 4 options
  tier       ∈ {free, pro, enterprise, trial}          — 4 options
seg A = chars 0-5 "9pLmQ!" → ord sum=390 → 390 mod 4 = 2 → "Chiara"
seg B = chars 6-11 "7xR#vK" → ord sum=436 → 436 mod 4 = 0 → "example.org"
seg C = chars 12-17 "2$bYzT" → ord sum=416 → 416 mod 4 = 0 → "free"
</thinking>
<answer>{ "name": "Chiara", "email": "chiara@example.org", "tier": "free" }</answer>
```

Subsequent runs of the same skill on the same task will produce different fixtures because the
random string changes. This increases effective test-data coverage without requiring a fixture
library.

---

## Invocation Patterns

### Pattern 1 — Inline reference (recommended)

Inside the phase instructions of a calling skill, add one sentence:

```markdown
For this generative step, apply SSoT — invoke `/nacl-ssot` with the candidate list and desired
distribution, then use the `<answer>` value as the output of this step.
```

### Pattern 2 — Standalone invocation

The user calls `nacl-ssot` directly for a one-off probabilistic decision:

```
/nacl-ssot Pick one of these three API authentication schemes at random: JWT, OAuth2, API Key
```

The skill executes Sum-Mod over three options and returns the chosen scheme.

### Pattern 3 — Multiple independent decisions in one phase

If a phase needs K independent random choices, each must use a fresh string. The calling skill
instruction should read:

```markdown
For each of the N independent choices, apply SSoT with a freshly generated string. Do NOT reuse
the same string across choices.
```

---

## Tool-Restriction Caveats

`nacl-ssot` must **never** call any tool to obtain its random value. This is an absolute
restriction, not a preference:

- No `mcp__*` tool calls
- No Bash execution of `python -c "import random; ..."`
- No web fetches to randomness APIs
- No file reads to obtain seed values

The entire entropy source is the model's internal generation of the `<random_string>` content.
Calling skills that wrap SSoT should not attempt to supply a seed via tool output — if a seed is
provided externally, the technique degrades to a deterministic hash with no diversity benefit.

**NaCl MCP tools are safe to use in the calling skill's other phases.** The restriction applies
only to the SSoT step itself (generating `<random_string>`).

---

## Modifier / Aspect Pattern

In NaCl's design vocabulary, `nacl-ssot` is an **aspect**: it modifies the behavior of a specific
step within a host skill's workflow without changing the host skill's phase structure or graph
interactions.

Contrast with:
- A **sub-skill** (e.g. `nacl-ba-sync` called from `nacl-ba-analyze`) — replaces an entire
  phase with a dedicated workflow.
- A **shared reference** (e.g. `nacl-core`) — provides data or constants, not behavior.

`nacl-ssot` provides behavior: it replaces "generate freely" with "generate via string-seeded
arithmetic." It is invoked by name inside the host skill's phase instructions, contributes its
three-tag output to that step, and then the host skill continues.

---

## Effort and Model Guidance

`nacl-ssot` is declared as `effort: low` because the additional tokens are modest: one random
string (16-32 chars), a few lines of arithmetic in `<thinking>`, and the final `<answer>`.

Model recommendation: use the same model as the calling skill. If the calling skill runs on
`haiku`, SSoT will still work but modulo arithmetic reliability is lower on smaller models.
For tasks where distribution fidelity is critical (e.g. agent simulations, statistical test data),
use `sonnet` or higher.

---

## Checklist for Integrating nacl-ssot into a New Skill

- [ ] Identify the specific generative step that benefits from SSoT
- [ ] Confirm the step is PIF (sampling) or DAG (diversity) — not a deterministic task
- [ ] Add one inline reference to `/nacl-ssot` in that phase's instructions
- [ ] If multiple independent choices exist in the same phase, note the fresh-string requirement
- [ ] Confirm no tool calls are used to supply the random value
- [ ] Test the integration by running the host skill twice with the same input — outputs should differ
