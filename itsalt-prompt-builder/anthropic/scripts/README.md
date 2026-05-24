# Scripts

## validate.py

Programmatic validator for CRAFT+ generated prompts. Checks 18 items derived from the SKILL.md self-check list and methodology rules.

### When to use

- **Always** in `improve` mode (where you may inherit hidden defects from the original prompt)
- **Always** for complex prompts (> 500 words, multiple conditional modules active)
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

**As a Python library:**

```python
from validate import validate_prompt

result = validate_prompt(
    prompt=prompt_text,
    target_model="claude",
    use_ssot=False,
    mode="generate",
)

print(result.report())  # human-readable
print(result.to_dict())  # dict for serialization
print(result.all_passed)  # boolean
print(result.failed_count)  # int
```

### What it checks (18 items)

1. **First line is language instruction** — `Respond to the user in [LANG]...`
2-11. **Each CRAFT+ block present** (10 blocks). `actions` and `examples` can be skipped for simple tasks; all others mandatory.
12. **Uncertainty rule embedded** — looks for "do not fabricate facts" in CONSTRAINTS
13. **Length 200-700 words** — sweet spot for frontier models 2026
14. **No aggressive emphasis** (Claude/Universal targets only) — "CRITICAL: YOU MUST", "IMPORTANT!!!", caps
15. **No "think step by step" injection** (Claude/GPT/Gemini/Universal targets) — frontier models do CoT internally
16. **No vague phrases** — "write well", "be creative", "make it good", etc.
17. **SSoT consistency** — `useSSOT=true` ↔ `creativity_protocol` block present
18. **No injection-defense clutter** — inner prompt should not contain "ignore previous instructions" defense (user is writing a task to themselves)

### Exit codes

- `0` — all checks passed
- `1` — one or more checks failed
- `2` — invalid invocation

### Validator-loop pattern (recommended)

For the cleanest output, integrate the validator into a self-correction loop:

```
1. Skill generates prompt
2. Run validate.py
3. If all checks pass → present to user
4. If checks fail → fix the listed issues
5. Re-run validate.py
6. Loop max 3 times; if still failing, surface remaining issues to user
```

This pattern is recommended by Anthropic's official skill best practices (May 2026 documentation).

### Limitations

- The validator is a syntactic check — it confirms structure but cannot judge content quality
- Vague phrase detection uses a fixed list; novel forms of vagueness may pass
- Block detection assumes the target_model's expected formatting; an off-format prompt may fail checks even if semantically complete
- Does not check examples for quality (mock examples can pass)

### Dependencies

Standard library only (`argparse`, `json`, `re`, `dataclasses`, `typing`). No pip install needed. Python 3.10+ (uses union types and `Literal`).
