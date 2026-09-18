# Скрипты

Слои конвейера. Каждый следующий читает артефакты предыдущего и ничего
не запрашивает у сайта повторно — это делает проверку воспроизводимой
и позволяет предъявить доказательство по любому пункту отчёта.

| Скрипт | Слой | Вход | Выход |
|--------|------|------|-------|
| `collect.py` | 0. Сбор | URL сайта | `artifacts/` — DOM, текст, формы, сеть, cookie, скриншоты, инфраструктура |
| `registries.py` | 1. Реестры | — | кэш нормализованных госреестров |
| `detect.py` | 2. Детекторы | `artifacts/` + реестры | `findings.json` |
| `gen_checklist.py` | сервис | `rules.yaml` | `references/checklist.md` |

`rules.yaml` — единственный источник правды по правилам. `signatures.yaml` —
данные детекторов: домены, паттерны, маппинг «домен → юрисдикция оператора».

## Установка

```bash
pip install -r scripts/requirements.txt
python -m playwright install chromium
```

Без playwright `collect.py` переходит в режим degraded и помечает это в
`manifest.json`. Детекторы обязаны читать этот флаг и выставлять `UNKNOWN`
вместо `PASS` по правилам, которые без рендера не проверяются.

## Сбор

```bash
python3 scripts/collect.py https://example.ru --out artifacts/
python3 scripts/collect.py https://example.ru --out artifacts/ --max-pages 25
python3 scripts/collect.py https://example.ru --out artifacts/ --no-browser
```

Главная страница загружается дважды: до взаимодействия с cookie-баннером и
после нажатия кнопки согласия. Разница между `network/before_consent.jsonl` и
`network/after_consent.jsonl` — доказательная база правила `CK-003`.
