# Changelog

## 2.4.0 — 2026-09-29

- HTTPS relay v2 on port 443 carries browser and Python traffic through the environment proxy; client capability check runs before quota issuance.
- Session retries survive changing cloud proxy IPs; bounded, offset-based tunnel blocks prevent duplicate upstream writes.
- Reports group network observations, keep a full evidence.html/evidence.json index, and mark unproven collection snapshots as limited.

## 2.3.0 — 2026-09-28

- Локальный аудит через РФ-шлюз: единая сессия, TLS-адаптер, custom-прокси и проверка выхода.
- Go/SQLite сервис с квотами, SSRF-защитой, отзывом туннелей и сетевым фильтром контейнера.
- Снимки реестров в артефактах, офлайн-повтор, явные ограничения и неполные результаты UNKNOWN.
- Развёрнутый РФ-шлюз задан по умолчанию: установка пакета не требует ручного указания адреса.
- Развёртывание и нагрузочный прогон завершены; живая приёмка клиентского аудита остаётся отдельным этапом.

## 2.1.0 — 2026-09-26

- Standardized runtime commands and browser dependency guidance on `uv`.
- Added a public legitimate-interest declaration scaffold, conditional interface
  examples and guidance for removing unnecessary tags without ignoring other obligations.
- Shortened skill instructions and specified concise, evidence-preserving findings.
- Reports now use accepted semantic review for totals, labels and outstanding
  work while retaining machine observations; stale reviews are discarded.
- Documented Pi installation through the shared skill directory.
- Fixed OpenAI final listing text limits; public submission remains pending.

## Unreleased

- Repository transition: old `<name>/anthropic/` now maps to
  `plugins/<name>/skills/<name>/`; old `<name>/openai/` maps to
  `plugins/<name>/adapters/chat/`. Root transition links remain during Phase A.

## 2.0.0

- Added portable Agent Plugin packaging and independent marketplace entry.
- Added evidence-backed processing-basis fields and legitimate-interest review.
- Changed cookie and foreign-tracker findings to require legal qualification
  instead of treating a domain or missing banner as an automatic violation.
- Added concise implementation recommendations and `uv` execution guidance.
