# Pepper Orchestrator 0.14.0: упаковка публичного релиза

31 октября 2026 года. Публичный preview, тег [`pepper-orchestrator-v0.14.0`](https://github.com/ITSalt/PepperSkills/releases/tag/pepper-orchestrator-v0.14.0).
[English](pepper-orchestrator-0.14.0-release.md).

После сквозной приёмки Linux/macOS владелец отдельно поручил публичный выпуск. Обновлены README EN/RU, CHANGELOG, инструкция Windows, руководства private owner и статус плана. Сгенерированные manifests уже содержат 0.14.0; marketplace использует канонический plugin source. Установка не включает автономность автоматически, не меняет пользовательские настройки и не запускает сервис.

## Артефакты

| Файл | SHA256 |
|---|---|
| `pepper-orchestrator.plugin.zip` | `c1975b462d4e28273dc63d69fd853d90bb6997691709f19ffd5b9e85be7d3b96` |
| `pepper-orchestrator.zip` | `7371ec92ecd182f58a8366ac9e3b3a9d4ceca37a1c886883c9b1aed65f9faf19` |

В Assets также находится `SHA256SUMS`; сверьте хеш до распаковки. Plugin ZIP включает отдельный Codex entrypoint и канонические ресурсы, standalone ZIP — канонический skill для private-owner launcher.

## Связь с живой приёмкой

[Отчёт Linux/macOS](pepper-orchestrator-0.14.0-private-owner.ru.md) сохраняет хеши реально исполненного архива, из которого также прошла Claude Linux регрессия. Он собран из `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d`; коммит evidence/test-driver `ee8a6fc` не менял пакет.

Публичный релиз пересобран после обновления документации. **Его ZIP не совпадает побайтово с архивом модельных сценариев.** [Машинное сравнение](evidence/orchestrator-0140-release-20261031/archive-comparison.json) подтверждает:

- Состав файлов сохранён; добавленных и удалённых entries нет.
- Plugin: 225 entries, изменены 12 Markdown entries; все 82 копии скриптов идентичны.
- Standalone: 101 entries, изменены четыре Markdown references; все 41 скрипт идентичны.
- Остальные файлы, включая SKILL.md, manifests, конфигурации, команды, шаблоны и исполняемый код, совпадают побайтово. Различия — версии/статусы, ссылки на релиз и пояснения установки/обновления.

Уже публичный plugin ZIP дополнительно прошёл zero-model project-MCP/redirected-commondir пробы на **Linux и macOS**, native Codex 0.165.0. Сохранены workspace-write, on-request, reviewer=user, network=true, без дополнительных базовых writable roots. Project MCP не запускался; native runtime завершены, копии auth удалены. Модельные сценарии для пересборки с изменениями только Markdown повторно не запускались. [Evidence выпуска](evidence/orchestrator-0140-release-20261031/README.md).

Полный локальный `scripts/check.sh` прошёл для релизного дерева: извлечённые/сгенерированные копии, 20 owner-тестов, 41 autonomy (15 Claude), воспроизводимость, неизменность исходников, проверка приватных следов. [CI PR #42](https://github.com/ITSalt/PepperSkills/pull/42/checks) проверяет Linux/macOS/Windows и совпадение пакетов Linux/macOS на разных Python. Windows имеет core/native plugin/App Server smoke; живая приёмка private owner там не заявляется.

## Воспроизведение

В отдельных checkout соберите accepted commit `0d6311a2234dbfccd15eddda7a06a9d28abc3c7d` и тег `pepper-orchestrator-v0.14.0` командой `bash scripts/build-plugins.sh pepper-orchestrator` с документированными build-зависимостями. Запустите [compare-archives.py](evidence/orchestrator-0140-release-20261031/compare-archives.py) с двумя каталогами `dist/pepper-orchestrator/0.14.0`; результат должен совпасть с `archive-comparison.json`. Пример команды — в английском отчёте. Публикация на GitHub не означает одобрения во внешнем магазине плагинов.

[Инструкция private owner](../../plugins/pepper-orchestrator/skills/pepper-orchestrator/references/private-owner.ru.md): защищённая установка, manifest фиксированных actors, zero-model preflight и явные console grants. Перед обновлением работающего owner остановите его. `--resume` требует неизменных code/config, доказанного завершения старого runtime и сохранённых thread ID. Производственные approvals не подтверждаются автоматически.
