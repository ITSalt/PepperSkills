# Security Policy

PepperSkills ships prompt-engineering documentation and prompt files. There is
no compiled code, runtime, or service in this repository. In-scope issues:

- A reference, example, or commit accidentally containing secrets, credentials,
  internal URLs, or private data.
- A broken or malicious external link in a published skill (e.g. a citation
  pointing to a hijacked domain).
- A repository-infrastructure issue (workflow misconfiguration, exposed token,
  insecure GitHub Actions setup, etc.) once such infrastructure is added.

Out of scope:

- The fact that a skill changes model output statistics — that is the library's
  documented purpose.
- Disagreements about a skill's effectiveness on a particular model.
- Model-side safety concerns: report those to the relevant model provider
  (Anthropic, OpenAI) using their disclosure channels.

## Reporting a vulnerability

**Please do not open a public GitHub issue.** Instead, use one of:

1. **GitHub Private Vulnerability Reporting** (preferred):
   <https://github.com/ITSalt/PepperSkills/security/advisories/new>
2. **Email**: `mnikitin@itsalt.ru`

Include the affected file path, a description of the issue, and (if relevant)
steps to reproduce. We aim to acknowledge reports within 5 business days and
to publish a fix or documented mitigation within 30 days of confirmation.

## Supported versions

Releases are tagged on `main` using SemVer (`vX.Y.Z`). Only the latest tagged
release and the current `main` branch receive security fixes.
