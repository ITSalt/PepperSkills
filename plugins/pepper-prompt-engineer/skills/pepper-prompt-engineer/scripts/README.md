# Scripts

## validate.py

Programmatic validator for CRAFT+ generated prompts.

**How many checks.** 16 checks always run. Two more are target-conditional — the
escalated-emphasis check applies to `claude` and `universal`, and the
chain-of-thought-injection check applies to every target — so a run reports 17 or 18
depending on the target. The report prints the actual count rather than a fixed number.

### When to use

- **Always** in `improve` mode (where you may inherit hidden defects from the original prompt)
- **Always** for complex prompts (multiple conditional modules active, or close to the length ceiling)
- **Optionally** in `generate` mode as a final safety net

### Usage

**From the command line:**

```bash
# Read prompt from a file
python validate.py prompt.txt --target claude

# Read from stdin
cat prompt.txt | python validate.py --stdin --target gpt

# With SSoT module active
python validate.py prompt.txt --target gpt --use-ssot

# Improve mode
python validate.py prompt.txt --target claude --mode improve

# JSON output
python validate.py prompt.txt --target claude --json
```

Targets: `claude`, `gpt`, `gemini`, `deepseek`, `universal`. The retired `deepseek-chat`
is still accepted and maps onto `deepseek` with a note on stderr.

**As a Python library:**

```python
from validate import validate_prompt

result = validate_prompt(
    prompt=prompt_text,
    target_model="claude",
    use_ssot=False,
    mode="generate",
)

print(result.report())   # human-readable
print(result.to_dict())  # dict for serialization
print(result.all_passed) # boolean
print(result.failed_count)
```

### What it checks

1. **Language instruction is the first line** — `Respond to the user in [LANG]...`, in the
   position SKILL.md Step 6 requires. Presence alone is not enough
2-11. **Each CRAFT+ block present** (10 blocks). `actions` and `examples` can be skipped for
   simple tasks; all others mandatory. Block detection follows the target's format —
   XML for Claude/Universal, Markdown headers *or* XML for GPT/Gemini/DeepSeek, matched
   case-insensitively
12. **Uncertainty rule embedded** — looks for "do not fabricate facts"
13. **Length within 700 words** — ceiling only. There is no floor: padding a simple prompt
   to reach a word count is the over-engineering pitfall SKILL.md warns about
14. **No escalated emphasis on tool/skill directives** (Claude/Universal) — the narrow case
   the vendor guidance actually covers. Ordinary `NEVER`/`MUST` in formatting rules passes
15. **No "think step by step" injection** — every current target reasons internally once its
   reasoning-depth control is engaged; raise the control instead
16. **No vague phrases** — scoped to `success_criteria` and `verification`. Scanning the
   whole prompt produced false positives on tasks that are legitimately about creativity
17. **SSoT consistency** — `useSSOT=true` ↔ a creativity-protocol block present in any of
   the wrapping forms `target-models.md` allows (XML tag or Markdown header)
18. **No injection-defense clutter** — the inner prompt should not contain "ignore previous
   instructions" defense; the user is writing a task to themselves

### Exit codes

- `0` — all checks passed
- `1` — one or more checks failed
- `2` — invalid invocation

### Validator-loop pattern (recommended)

```
1. Skill generates prompt
2. Run validate.py
3. If all checks pass → present to user
4. If checks fail → fix the listed issues
5. Re-run validate.py
6. Loop max 3 times; if still failing, surface remaining issues to user
```

Anthropic's skill-authoring guidance calls this out under "implement feedback loops":
run validator → fix errors → repeat, proceeding only when validation passes.

### Limitations

- The validator is a syntactic check — it confirms structure but cannot judge content quality
- Vague-phrase detection uses a fixed list; novel forms of vagueness may pass
- Block detection assumes the target's expected formatting; an off-format prompt may fail
  checks even if semantically complete
- Does not check examples for quality (mock examples can pass)
- Cannot verify that the reasoning-depth `user_instruction` was emitted — that lives in the
  skill's response, not in the prompt text

### Dependencies

Standard library only (`argparse`, `json`, `re`, `dataclasses`, `typing`). No pip install
needed. Python 3.10+ (uses union types and `Literal`).

---

## run_evals.py

Harness for `evals/evals.json`. It does two things:

- **Schema check** — validates every scenario against the expected shape and fails loudly
  on a malformed file
- **Run sheet** — prints each scenario's query and its `expected_behavior` items as a
  checklist, so a run against a live model can be scored consistently

```bash
python run_evals.py                 # print the run sheet
python run_evals.py --check-only    # schema validation only, no output body
python run_evals.py --json          # machine-readable
```

It deliberately does **not** call a model. Scoring a prompt-construction skill needs
judgement about the produced prompt, so the harness structures that judgement rather than
faking it. Exit code `0` if the file is well-formed, `1` otherwise.
