# Скрипты

Слои конвейера. Каждый следующий читает артефакты предыдущего и ничего
не запрашивает у сайта повторно — это делает проверку воспроизводимой
и позволяет предъявить доказательство по любому пункту отчёта.

| Скрипт | Слой | Вход | Выход |
|--------|------|------|-------|
| `collect.py` | 0. Сбор | URL сайта | `artifacts/` — DOM, текст, формы, сеть, cookie, скриншоты, инфраструктура |
| `registries.py` | 1. Реестры | — | кэш нормализованных госреестров |
| `detect.py` | 2. Детекторы | `artifacts/` + реестры | `findings.json` |
| `gen_checklist.py` | сервис | `rules.yaml`, `signatures.yaml` | `references/checklist.md`, JSON-двойники |

`rules.yaml` — единственный источник правды по правилам. `signatures.yaml` —
данные детекторов: домены, паттерны, маппинг «домен → юрисдикция оператора».

## Установка

Нужен [uv](https://docs.astral.sh/uv/getting-started/installation/); Python 3.10+
указан в PEP 723 заголовках скриптов. `uv run --no-project` использует отдельное
окружение, не добавляя зависимости в проект сайта. Базовый сбор и детекторы
работают на стандартной библиотеке. Для браузера/PDF добавляйте `--with playwright`
при каждом запуске. Команды выполняются из корня распакованного скилла:

```bash
uv run --no-project --with playwright python -m playwright install chromium
```

Для разработки: `gen_checklist.py --write` требует PyYAML; `--check` проверяет
checklist и оба JSON-файла без записи. В поставке JSON позволяет детекторам
работать без PyYAML.

Без playwright `collect.py` переходит в режим degraded и помечает это в
`manifest.json`. Детекторы обязаны читать этот флаг и выставлять `UNKNOWN`
вместо `PASS` по правилам, которые без рендера не проверяются.

## Сбор

```bash
uv run --no-project --with playwright scripts/collect.py https://example.ru --out artifacts/
uv run --no-project --with playwright scripts/collect.py https://example.ru --out artifacts/ --max-pages 25
uv run --no-project scripts/collect.py https://example.ru --out artifacts/ --no-browser
```

Сбор разделяет независимые сценарии `before_consent`, `after_consent`,
`after_reject` и `revisit_reject`. Сравниваются сеть и cookie; наличие кнопки
не доказывает работающий отказ. Используйте одного пользователя и одинаковый
`PLAYWRIGHT_BROWSERS_PATH` при установке Chromium и при запуске.

## Проверка и документы

```bash
uv run --no-project scripts/detect.py --artifacts artifacts/ --out findings.json
uv run --no-project scripts/render.py --findings findings.json --out-dir report/ --format md,html
uv run --no-project --with playwright scripts/render.py --findings findings.json --out-dir report/ --format md,html,pdf
uv run --no-project scripts/selftest.py
uv run --no-project scripts/gen_checklist.py --check
```

`uv` может загружать Python и пакеты при первом запуске. Для автономной работы
подготовьте кэш заранее. Отсутствие браузера явно ограничивает покрытие;
`--no-browser` не является полной проверкой.


### Контекст сетевых доказательств (2.2.0)

Журнал запросов сохраняет `observation_version: 2`, `request_id`, страницу,
сценарий, фрейм, доступный инициатор CDP и тип содержимого. `payload_shape`
содержит только известные имена полей без значений; вложенные и неизвестные
ключи не сохраняются. Тело запроса не записывается. Исходный URL остаётся в
журнале для воспроизводимости; в отчёт выводится адрес без параметров,
фрагмента и учётных данных. Журналы и cookie являются внутренними артефактами.

`form_relation` подтверждает нативную отправку формы только по событию
браузера `Page.frameRequestedNavigation`. Это не доказательство наличия ПДн
или географии хранения. AJAX без отдельного подтверждения остаётся запросом
неустановленного назначения. Инициатор и связь с формой могут отсутствовать,
в том числе для worker/отдельных iframe: отсутствие данных не означает PASS.
Классификация по адресу имеет суффикс `_candidate`. CSP и аналитика остаются
в инвентаре и могут требовать отдельной оценки. Старые журналы читаются без
восстановления отсутствующих сведений.

Офлайн-регрессии: `uv run --no-project scripts/test_network_evidence.py`.
Браузерная приёмка на перехваченных тестовых страницах (без запросов к сайтам):

```bash
uv run --no-project --with playwright scripts/test_network_browser.py --out /tmp/pepper-evidence-qa
```

Она проверяет нативные GET/POST-формы, AJAX, фреймы, повторные подключения
сборщика, синтетический Markdown/HTML/PDF, якоря и ширину HTML. Просмотр
изображений и PDF выполняется отдельно. В общий offline gate браузер не входит.
