# PepperSkills Privacy Policy

Effective date: 1 October 2026. [Русская версия](PRIVACY.ru.md).

## Publisher and scope

The publisher is **Никитин Максим Геннадиевич (Nikitin Maksim Gennadievich)**, an individual. PepperSkills and ITSalt are project names used in this repository; they do not identify a separate publisher for this policy.

This policy covers Pepper Creative Mode, Pepper Prompt Engineer, Pepper Orchestrator and Pepper RU Web Compliance. Contact for support and privacy requests: **mnikitin@itsalt.ru**. Source code and public issue tracker: [ITSalt/PepperSkills](https://github.com/ITSalt/PepperSkills).

## Information used by the plugins

**Creative Mode** uses the topics, alternatives, weights and creative instructions supplied for a task. **Prompt Engineer** uses task descriptions, examples, constraints and prompt drafts. These skill packages do not include a publisher-operated service that receives those prompts. The selected AI application processes task content under its own terms and settings.

**Orchestrator** uses the authorized workspace: plans, work packages, status records, repository and pull-request references, and verification reports. It can run authorized local tools and interact with Git, GitHub, agent clients and user-configured environments. Data sent to those systems depends on the specific operation and project settings. Workspace files may be committed to a repository; repository visibility and access settings determine who can see them.

Orchestrator can prepare a plugin bug report with private details replaced by placeholders. Automated redaction is not guaranteed to remove every sensitive detail. Review the report before allowing it to be sent. Posting to GitHub Issues requires explicit permission or an automatic-reporting mode previously authorized by the user. Public issues and comments are visible to everyone.

**RU Web Compliance** collects website evidence in the user's execution environment. Artifacts can include HTML, text, screenshots, form-field descriptions, network URLs, cookies, infrastructure information, public-registry responses and reports. Its collector does not submit forms containing personal data, but may click consent and rejection controls. The saved refusal state can contain cookies and localStorage and is not intended for public sharing. Audit only sites you are authorized to inspect.

## RU Web Compliance relay and other recipients

The default managed route uses the publisher's Russian HTTPS relay at `https://lts.itsalt.ru/ru-audit`. The relay handles source connection IP addresses, destinations, traffic volumes and durations to forward requests, enforce quotas and diagnose failures. Quota identifiers are HMAC-derived from an IP address or IPv6 prefix; idempotency identifiers use a HMAC of the target URL. These are pseudonymous identifiers, not a promise of anonymity.

The relay does not decrypt HTTPS traffic to the audited site. Unencrypted HTTP traffic is technically visible to the proxy. The gateway does not run a server-side audit browser or retain audit artifacts, HTTP bodies, cookies or user reports. Registry responses pass through service memory. Logs contain failure reasons, volumes and durations; full URLs, query parameters and access tokens are not logged by the gateway application.

The audited website and its resources, public registries and infrastructure-information providers receive the requests needed for the audit. A preflight request to `ipinfo.io` checks the outgoing IP and country through the selected route. Dependency installation contacts the relevant package repositories and CDNs. A user-supplied proxy has its own data practices. See the [detailed RU Web Compliance data-flow description](plugins/pepper-ru-web-compliance/submission/privacy.md); the publisher identity and support-retention terms in this policy take precedence over older wording in that description.

Across the plugins, other recipients can include the selected AI provider, GitHub, and environments or tools authorized by the user. They process the data supplied to the corresponding operation under their own terms. The publisher does not control those providers' chat storage, model-training settings, repository history or backup retention.

## Retention and deletion

- **Local files and Git history:** kept in the user's environment until the user removes them. The plugins do not automatically expire these materials. Deleting a local file does not remove Git history, chat history, remote copies or backups.
- **Relay quota records:** removed after 48 hours, with cleanup once per minute. Active relay sessions are held in memory for their lifetime. The repository's deployment configuration rotates application logs by size, with up to three 10 MB files per container; this is not a fixed calendar retention period. Additional host and infrastructure logs follow the hosting operator's retention arrangements. Contact the publisher for questions or deletion requests concerning publisher-managed data.
- **Email support:** the publisher receives the sender's address and information voluntarily included in the message to answer and resolve the request. Support correspondence and copies managed by the publisher are deleted no later than 30 days after the request is closed. Separate retention by the email provider is governed by that provider’s own policies.
- **Public GitHub issues:** remain public until removed or edited through GitHub. Closing an issue does not delete it. GitHub may retain history and backups under its own policies.

To request access, correction or deletion of information held by the publisher, email **mnikitin@itsalt.ru** with enough context to identify the material. Do not send passwords, API keys or unnecessary identity documents. Copies held by an AI provider, GitHub or another service may require a separate request or action in that service.

## User choices

Share only the information needed for the task. Keep secrets and unnecessary personal data out of prompts, plans, reports and public issues. Review outputs before publishing them. Use the host application's permission controls for workspace access, network operations and external writes. You can decline an operation or disable a plugin; disabling it does not automatically delete previously saved data.

## Changes

Changes to this policy will be published on this page with an updated effective date. Earlier versions are available in the repository's Git history.
