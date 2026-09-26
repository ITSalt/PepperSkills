# Установка

Канонический скилл находится в `plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer/`.
Плагин содержит тот же источник для всех агентов и сгенерированный чат-адаптер
в `adapters/chat/`.

```bash
ln -s /path/to/PepperSkills/plugins/pepper-prompt-engineer/skills/pepper-prompt-engineer \
  .agents/skills/pepper-prompt-engineer
```

Для Claude Code используйте `.claude/skills/`, для Codex и Pi — `.agents/skills/`,
для Cursor — `.agents/skills/` или `.cursor/skills/`. После обновления клона
перечитайте скиллы или откройте новую сессию. Архив плагина собирается командой
`./scripts/build-plugins.sh pepper-prompt-engineer`, а `.skill` для старого
загрузчика — `./scripts/build-skills.sh pepper-prompt-engineer`.

Модель выбирается как часть методики prompt-engineer, а исполнитель скилла — по
доступным инструментам среды.
