# Установка

Канонический скилл находится в `plugins/pepper-creative-mode/skills/pepper-creative-mode/`.
Установите плагин целиком или свяжите эту папку симлинком с каталогом скиллов.

```bash
ln -s /path/to/PepperSkills/plugins/pepper-creative-mode/skills/pepper-creative-mode \
  .agents/skills/pepper-creative-mode
```

Для Claude Code используйте `.claude/skills/`, для Codex и Pi — `.agents/skills/`,
для Cursor — `.agents/skills/` или `.cursor/skills/`. Обновления приходят через
новую версию плагина или `git pull` клона и новую сессию. Архив без внешних
симлинков собирается командой `./scripts/build-plugins.sh pepper-creative-mode`;
совместимый `.skill` — `./scripts/build-skills.sh pepper-creative-mode`.

Скилл активируется только на запросах, где нужна случайность или несколько
вариантов. Для задач с единственным правильным ответом он не применяется.
