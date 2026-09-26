# Transition releases — 2026-09-26 / Переходные релизы

| Product / Продукт | Release / Релиз |
| --- | --- |
| `pepper-creative-mode` | [2.0.0](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-creative-mode-v2.0.0) |
| `pepper-prompt-engineer` | [2.5.0](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-prompt-engineer-v2.5.0) |
| `pepper-ru-web-compliance` | [2.0.0](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-ru-web-compliance-v2.0.0) |

Each release contains the standalone skill ZIP, full plugin ZIP and SHA256SUMS.
Choose the product-specific release above; the repository-wide latest release
points to only one product.

## Migration / Миграция

Canonical source: `plugins/<name>/skills/<name>/`. Old root paths and their seven
transition symlinks remain available. Root `.skill` files stay frozen at `4128fe6`;
they are not the packages for these releases. Historical releases and tags remain.

Канонический исходник: `plugins/<name>/skills/<name>/`. Старые пути пока сохранены.
Перед отдельным этапом B перенастройте ручные симлинки по инструкции. Публикация
этих релизов сама по себе не удаляет старые пути и не меняет установки пользователей.

[Installation and migration](../installation-and-updates.md) ·
[Установка и миграция](../installation-and-updates.ru.md)

## Verification / Проверки

Package source: `391696c13720fba4e6c4f3e77b696442361a55fa`.
[Main CI](https://github.com/ITSalt/PepperSkills/actions/runs/36255079601) passed on
Ubuntu/Python 3.10, Ubuntu/Python 3.12 and macOS/Python 3.12. The comparison job
confirmed identical archive SHA-256 values across all three environments.

On 2026-09-26, the three exact standalone ZIPs were uploaded in Claude web through
Customize → Skills → Upload. With the account owner's explicit approval, existing
skills were updated using Upload and replace. Claude reported **3 skills added**.
This confirms ZIP import/update acceptance. Invocation quality, Desktop/Cowork
execution, plugin marketplace acceptance, live website collection and PDF rendering
remain separate checks; they are not claimed by this release record.

26 сентября 2026 года все три ZIP приняты Claude web с обновлением существующих
скиллов по явному разрешению владельца аккаунта. Проверка охватывает импорт и
обновление ZIP; выполнение сценариев и приёмка маркетплейсами проверяются отдельно.
