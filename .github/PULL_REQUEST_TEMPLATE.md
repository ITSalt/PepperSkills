<!-- Thanks for contributing! Please fill in the sections below. -->

## What this changes

<!-- One or two sentences. A fix of a reported defect starts with "Fixes #N". -->

Fixes #

## Type

- [ ] New skill
- [ ] Skill improvement (wording, examples, references)
- [ ] Bug fix (broken link, incorrect instruction, outdated content)
- [ ] Repository docs / tooling

## Checklist

- [ ] I read [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] Canonical sources in `plugins/<name>/` are updated; regenerate checked-in adapters when relevant.
- [ ] Transition compatibility paths remain valid unless this change is an approved Phase B release.
- [ ] Internal links are relative and resolve.
- [ ] I ran the affected examples against a current model and the behavior matches the documentation.
- [ ] No personal data, internal URLs, or secrets in the diff.
- [ ] No private traces: no names, domains or paths of private projects or machines in the diff,
      the commits or this description (`scripts/check.sh` runs `check-private-traces.py`).
- [ ] `bash scripts/check.sh` passes locally.

## Notes for the reviewer

<!-- Optional: anything subtle, intentional tradeoffs, follow-ups. -->
