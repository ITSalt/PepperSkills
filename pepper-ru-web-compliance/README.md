# `pepper-ru-web-compliance`

A skill that audits a website against Russian legal requirements and produces
two documents: an analytical note for the site owner and their lawyer, and a
remediation plan for a developer agent.

The audit is black-box: the skill opens the site as an ordinary visitor and
reads the markup, the network log, the cookies and the published legal
documents. Source access is optional — when it is available, the plan points at
files instead of selectors.

## The problem

A site owner usually knows that "something about personal data" is required and
not what exactly. A lawyer knows the statutes but does not open DevTools. A
developer reads the network log but does not know that art. 9(4) of the Personal
Data Act requires a live link to the policy inside the consent checkbox label.

The site keeps running with violations that became considerably more expensive
in 2025: up to ₽700,000 for a form without consent, up to ₽6,000,000 for failing
to report a breach, and from 07.07.2026 up to ₽700,000 for offering sign-in
through a foreign provider.

The skill closes the gap: scripts establish facts, the model qualifies them, and
the output is a document both the lawyer and the developer can act on.

## What is inside

44 rules, grouped by subject:

| Group | Rules | Subject |
|-------|-------|---------|
| Authorization | 8 | art. 8(10) of the Information Act, art. 13.55 of the Administrative Code: Google, Apple, Telegram, foreign IDaaS |
| Disclaimers and symbols | 9 | foreign-agent labels (Government Decree 2108), extremist and undesirable organizations, Meta symbols |
| Personal data | 13 | Personal Data Act: policy, consents, cross-border transfer, data localization, notification to the regulator |
| Cookies and trackers | 7 | consent banner, trackers firing before consent, jurisdiction of recipients |
| Infrastructure | 4 | HTTPS, hosting, geography of form endpoints |
| Company details | 3 | Consumer Rights Act and art. 22.1 of the Personal Data Act |

By method: 22 rules are settled by scripts, 12 are hybrid (the script collects
the evidence, the model assigns the status), 8 are semantic, and 2 exist purely
to suppress false positives.

Every rule carries the statute, the penalty article, the fine range for a legal
entity, the way it is checked, a fix hint, and a manual-check procedure for the
cases where no automatic verdict is possible.

## How it works

```
collect.py     gather facts        -> artifacts/
registries.py  state registries    -> cache
detect.py      detectors           -> findings.json
semantic layer qualification       -> enriched findings.json
render.py      assemble documents  -> note + plan
```

The split is substantive, not organizational. A script cannot tell whether a
privacy policy is complete, or whether the organization it matched in the text
is the one in the registry. A model cannot reliably diff two network logs or
verify a hundred taxpayer-ID checksums.

### Three rules that outrank convenience

**No status without evidence.** Every item in the note carries a network
request, a selector or a quote from the site. Nothing to back it up means
`UNKNOWN`, not a carefully worded guess.

**Missing data is not a `PASS`.** A registry that failed to load or a page that
did not open lands in "could not verify" together with instructions. A quiet "no
violations found" drawn from incomplete data is this skill's worst failure mode.

**Provenance travels with the conclusion.** "No foreign agents mentioned" backed
by the official registry and the same sentence backed by a mirror are claims of
different strength, and the note keeps them apart.

## State registries

Five of them: foreign agents, extremist organizations, the federal list of
terrorist organizations, undesirable organizations, and the federal list of
extremist materials.

They live on `*.gov.ru` hosts that answer Russian addresses only — and Claude is
not available in Russia. So a source is resolved along a chain: official site →
official through the user's proxy → published mirror → cache. The user chooses:
run a proxy with a Russian exit (`PEPPER_RU_REGISTRY_PROXY`), or use the
[`ITSalt/ru-registries-mirror`](https://github.com/ITSalt/ru-registries-mirror)
mirror, refreshed from the primary sources on a schedule from a Russian VPS.

Registry snapshots are deliberately **not** shipped with the skill: the
foreign-agent list grows weekly, and a stale copy does not produce "no data" —
it produces a quiet false "no mentions found".

## Output

**`compliance-report.pdf`** (plus `.md` and `.html`) — one document in two
parts.

*Part I, the note* — summary, exposure in roubles, a checklist covering every
rule with its statute, status and fine range, a detailed section per violation
with evidence, and a "check manually" section with a concrete procedure for each
unresolved item.

*Part II, the plan* — tasks ordered by descending risk: what to do, where
exactly, the acceptance criterion, and a link back to the note. Tasks that need
legal wording are marked "client input required" — without that mark a developer
agent will draft the privacy policy itself, and the client ends up with a
document that looks legal but is not.

**`remediation-plan.md`** — the same Part II as a standalone file, ready to hand
to a developer agent without the statutes and the evidence.

## What the skill does not do

It does not give legal opinions and does not replace a lawyer. It does not write
policies or consent texts — it only reports what is missing from them. It does
not inspect third-party platforms. It does not cover sector-specific regimes
(government, education, healthcare). It never modifies the site: read only.

Two rules stay without an automatic verdict by design, and that is an honest
boundary rather than a gap: the unified registry of prohibited information is
machine-readable only for licensed telecom operators with a qualified electronic
signature, and the regulator's operator registry answers Russian addresses only.
For both, the note prints a manual procedure with a direct link.

## Disclaimer

The skill performs a **technical** inspection of a website and is not a legal
service. Statuses, statutes and penalty amounts are informational, current as of
the audit date, and do not account for sector specifics, case law, or the
circumstances of a particular operator. Legal qualification is a lawyer's job.

The author and ITSalt accept no liability for decisions taken on the basis of
the documents this skill produces, or for the consequences of such decisions,
including administrative penalties. The software is provided "as is" — see
[MIT](../LICENSE).

## Installation

Details in [`anthropic/INSTALL.md`](./anthropic/INSTALL.md).

```bash
cp -R anthropic ~/.claude/skills/pepper-ru-web-compliance
```

No dependencies: Python 3.10+ standard library only. Playwright is optional and
widens coverage — without it the rules about the cookie banner, checkbox state
and network requests fall back to `UNKNOWN`.

## Pick your platform

| Platform | File |
|----------|------|
| Anthropic — Claude Code, Claude Desktop, claude.ai | [`anthropic/SKILL.md`](./anthropic/SKILL.md) |
| OpenAI — API / Custom GPT (manual checklist, no scripts) | [`openai/system-prompt.md`](./openai/system-prompt.md) |
| OpenAI — ChatGPT Custom Instructions (compact) | [`openai/custom-instructions.md`](./openai/custom-instructions.md) |

The OpenAI edition is deliberately reduced: without code execution there is no
crawl and no registry lookup, so it ships a manual review checklist rather than
an audit.

## Checks

```bash
python3 scripts/selftest.py                # detector and matcher regressions, offline
python3 scripts/gen_checklist.py --check   # checklist matches rules.yaml
```

Trigger eval sets live in [`anthropic/evals/`](./anthropic/evals/).

## Documentation versions

- English — this file
- Русский — [`README.ru.md`](./README.ru.md)
- Technical deep dive (Russian) — [`docs/ru-web-compliance-deep-dive.ru.md`](../docs/ru-web-compliance-deep-dive.ru.md)

## License

[MIT](../LICENSE) © ITSalt. Provenance of third-party material —
[`NOTICE.md`](./NOTICE.md).
