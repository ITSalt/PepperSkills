#!/usr/bin/env python3
"""render.py — сборка выходных документов из findings.json.

Один документ, две части — для двух разных читателей.

Часть I отвечает владельцу сайта и его юристу на вопрос «что у нас не так и
чем это грозит»: статус по каждому правилу, норма, санкция и доказательство,
которое можно перепроверить. Часть II отвечает разработчику на вопрос «что
именно сделать»: конкретное место, действие, критерий приёмки.

Разделение содержательное, а не оформительское: в части I нет задач, иначе она
превращается в тикет и теряет доказательность; в части II нет норм КоАП, иначе
исполнитель читает право вместо того, чтобы чинить. Но живут они в одном файле
— иначе при передаче теряется половина, а ссылки из плана на пункты записки
перестают работать.

План дополнительно пишется отдельным файлом: его скармливают агенту-
разработчику, и подавать туда весь документ с нормами незачем.

HTML и Markdown собираются из одной структуры независимо — не конвертацией
одного в другое. Markdown-парсер ради этого был бы лишней хрупкой деталью, а
HTML умеет то, чего Markdown не умеет: цветовую шкалу риска и скриншоты.

PDF печатается тем же Chromium, который нужен краулеру. Отдельная библиотека
для печати не нужна; если браузера нет, PDF просто не собирается.

Использование:
    python3 scripts/render.py --findings findings.json --out-dir report/
    python3 scripts/render.py --findings findings.json --out-dir report/ --format md,html,pdf
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# «Требует проверки» читалось так, будто проверка ещё идёт. Формулировка должна
# сразу говорить, что без действий человека вывод не получить.
STATUS_RU = {"FAIL": "НАРУШЕНО", "WARN": "НУЖНА РУЧНАЯ ПРОВЕРКА", "PASS": "СОБЛЮДЕНО",
             "NA": "НЕ ПРИМЕНИМО", "UNKNOWN": "НЕ УДАЛОСЬ ПРОВЕРИТЬ"}


def status_label(finding: dict[str, Any]) -> str:
    """«Не удалось» и «ещё не сделано» — разные вещи, и читатель вправе их
    различать. Правило, по которому скрипт собрал всё нужное, но вывод даёт
    смысловой анализ, не проверено не потому, что данных не хватило."""
    if finding["status"] == "UNKNOWN" and finding.get("needs_llm"):
        return "ТРЕБУЕТ АНАЛИЗА"
    return STATUS_RU.get(finding["status"], finding["status"])
STATUS_ORDER = {"FAIL": 0, "WARN": 1, "UNKNOWN": 2, "PASS": 3, "NA": 4}
SEVERITY_RU = {"critical": "критический", "high": "высокий", "medium": "средний",
               "low": "низкий", "info": "справочно"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
GROUP_RU = {"auth": "Авторизация пользователей",
            "disclaim": "Дисклеймеры и символика",
            "pdn": "Персональные данные (152-ФЗ)",
            "cookie": "Cookie и трекеры",
            "infra": "Инфраструктура",
            "org": "Реквизиты оператора",
            "internal": "Служебное"}

# Кто сделал проверку. Записку пересылают дальше, и через месяц никто не
# вспомнит, чем она сделана и куда писать, если что-то в ней спорно.
SKILL_NAME = "pepper-ru-web-compliance"
SKILL_AUTHOR = "Максим Никитин, ITSalt"
SKILL_REPO = "https://github.com/ITSalt/PepperSkills"
SKILL_CHANNEL = "https://t.me/itpepper"
SKILL_EMAIL = "mnikitin@itsalt.ru"


def colophon_lines(data: dict[str, Any]) -> list[str]:
    return [
        f"Проверка выполнена скиллом **{SKILL_NAME}** — открытый набор правил "
        f"и скриптов проверки сайта на соответствие требованиям РФ.",
        "",
        f"- Автор: {SKILL_AUTHOR}",
        f"- Исходники и обновления правил: {SKILL_REPO}",
        f"- Канал автора: {SKILL_CHANNEL}",
        f"- Вопросы и замечания по проверке: {SKILL_EMAIL}",
        "",
        "Нормы и суммы санкций в документе актуальны на дату проверки "
        f"({data['generated_at'][:10]}). Законодательство меняется — перед "
        "использованием записки в переписке или в суде сверьтесь с актуальной "
        "редакцией.",
    ]


DISCLAIMER = (
    "Настоящий документ — результат технической проверки сайта, а не юридическое "
    "заключение. Статусы и суммы санкций носят справочный характер; окончательную "
    "правовую квалификацию даёт юрист. Проверка охватывает только сам сайт и не "
    "распространяется на внутренние процессы оператора, договоры с подрядчиками и "
    "содержимое внешних площадок.")


# --- Разбор сумм -------------------------------------------------------------


def max_fine(finding: dict[str, Any]) -> int:
    """Верхняя граница санкции для юрлица — для оценки риска в рублях.

    Берётся максимум из строки вида «300 000 – 700 000 ₽». Оборотные штрафы
    («1–3% выручки») в рублях не выражаются и в сумму не попадают: подменять
    их придуманной цифрой значило бы занижать риск молча.
    """
    text = finding.get("liability") or ""
    numbers = [int(n.replace(" ", "").replace(" ", ""))
               for n in re.findall(r"\d[\d\s ]{4,}", text)]
    return max(numbers) if numbers else 0


NBSP = "\u00a0"


def nbsp_numbers(text: str) -> str:
    """Неразрывный пробел внутри разрядов и перед знаком рубля.

    «150 000 – 300 000 ₽» в узкой колонке переносится как «150 000 –» / «300»
    / «000 ₽»: сумма разваливается на куски, и колонка читается как мусор.
    Разряды одного числа должны держаться вместе всегда."""
    text = re.sub(r"(?<=\d) (?=\d{3}\b)", NBSP, text)
    return re.sub(r" (₽|руб\.?)", NBSP + r"\1", text)


def money(value: int) -> str:
    return nbsp_numbers(f"{value:,}".replace(",", " ") + " ₽")


def fine_display(finding: dict[str, Any]) -> str:
    """Вилка штрафа для юрлиц без санкции за повторное нарушение.

    Повторность применима не всегда и в обзорной таблице завышала бы картину:
    читатель видит «до 18 млн» там, где за первое нарушение грозит 6 млн.
    """
    value = finding.get("fine_legal") or ""
    value = re.split(r",?\s*(?:при повтор|повторно)", value)[0].strip(" ,;")
    return nbsp_numbers(value) or "—"


def fine_amount(finding: dict[str, Any]) -> str:
    """То же, но без знака рубля: в таблице он вынесен в заголовок колонки.

    Повторять «₽» в каждой строке — значит тратить ширину колонки на символ,
    который читатель уже прочитал в шапке."""
    value = fine_display(finding)
    if value == "—":
        return value
    trimmed = re.sub(r"\s*₽", "", value).strip()
    return trimmed or "—"


def anchor(rule_id: str) -> str:
    return "rule-" + rule_id.lower().replace(".", "-")


def sentence(text: str) -> str:
    """Завершает фразу точкой. Сводки детекторов её не содержат, и без этого
    соседние предложения слипаются в нечитаемое «юрисдикции: US Риск до…»."""
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?:" else text + "."


# --- Аналитическая записка ---------------------------------------------------


def coverage_alert(data: dict[str, Any]) -> str | None:
    """Предупреждение о том, что проверка не состоялась.

    Записка, где «нарушений: 0» стоит рядом с нулём открытых страниц, читается
    как «всё в порядке» — и это ровно тот тихий отказ, ради недопущения
    которого написан скилл. Если смотреть было не на что, это должно стоять
    выше цифр, а не под ними.
    """
    analysed = data.get("pages_analysed", 0)
    if analysed:
        if data.get("thin_coverage"):
            return ("**Охват неполный.** Обход открыл всего "
                    f"{analysed} страниц(ы), непосещённых ссылок — "
                    f"{data.get('unvisited_links', 0)}. Выводы об отсутствии чего-либо "
                    "(упоминаний, баннера, трекеров) действительны только для "
                    "проверенных страниц.")
        return None
    why = ("сайт заблокировал обход: страницы отвечают отказом на автоматические "
           "запросы" if data.get("blocked") else "ни одна страница не открылась")
    return ("**Проверка не состоялась.** Ни одна страница сайта не собрана — "
            f"{why}. Ни один вывод ниже не подтверждён наблюдениями: статус "
            "«соблюдено» в этом документе не выставлен ни одному пункту, а "
            "«нарушений: 0» означает, что нарушений не наблюдалось, а не что их "
            "нет. Чтобы получить результат, нужно собрать страницы иначе: "
            "запустить сбор из авторизованной сессии браузера, с другого адреса "
            "или передать исходники сайта.")


def summarise(data: dict[str, Any]) -> dict[str, Any]:
    findings = data["findings"]
    fails = [f for f in findings if f["status"] == "FAIL"]
    warns = [f for f in findings if f["status"] == "WARN"]
    unknowns = [f for f in findings if f["status"] == "UNKNOWN"]
    exposure = sum(max_fine(f) for f in fails)
    turnover = [f for f in fails
                if "выручки" in (f.get("liability") or "")
                or f.get("severity") == "critical"]
    return {"fails": fails, "warns": warns, "unknowns": unknowns,
            "exposure": exposure, "turnover_risk": turnover,
            "passes": [f for f in findings if f["status"] == "PASS"],
            "nas": [f for f in findings if f["status"] == "NA"]}


def manual_blocks_html(text: str) -> str:
    """Инструкция ручной проверки в HTML: абзацы и команды.

    Строки с отступом — это команда, которую копируют целиком; ломать её
    переносами по ширине абзаца нельзя, иначе скопированное не заработает.
    """
    out: list[str] = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        if chunk.startswith("    "):
            body = "\n".join(line[4:] if line.startswith("    ") else line
                              for line in chunk.splitlines())
            out.append(f"<pre class=cmd>{esc(body)}</pre>")
        else:
            out.append(f"<p>{linkify(' '.join(chunk.split()))}</p>")
    return "".join(out)


def manual_hint(finding: dict[str, Any]) -> str:
    """Что человеку сделать, чтобы закрыть непроверенный пункт.

    Важно, что это не `fix_hint`: совет «вынести плашку в начало материала» под
    пунктом, про который сказано «не проверено», требует исправить то, чего,
    возможно, и нет. Инструкция по проверке и инструкция по исправлению — разные
    тексты, и путать их нельзя.
    """
    if finding.get("manual_check"):
        return finding["manual_check"]
    evidence = (finding.get("rule_evidence") or [])
    if evidence:
        return "Проверить вручную: " + "; ".join(evidence[:2]).lower()
    return ("Проверить пункт вручную по описанию правила в "
            "`references/checklist.md`")


def sort_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda f: (STATUS_ORDER.get(f["status"], 9),
                                        SEVERITY_ORDER.get(f["severity"], 9),
                                        f["rule_id"]))


def site_name(data: dict[str, Any]) -> str:
    """Домен проверяемого сайта — он должен стоять в заголовке.

    Отчёт живёт дольше разговора: его пересылают, распечатывают, кладут в папку
    к трём таким же. Заголовок без адреса заставляет читателя искать, о каком
    сайте документ."""
    target = data.get("target") or ""
    host = urllib.parse.urlparse(target).hostname or target
    return host.removeprefix("www.") or "сайта"


def report_md(data: dict[str, Any]) -> str:
    s = summarise(data)
    out: list[str] = []
    add = out.append

    add(f"# Часть I. Аналитическая записка — {site_name(data)}")
    add("")
    add(f"**Проверенный ресурс:** {data['target']}  ")
    add(f"**Дата проверки:** {data['generated_at'][:10]}  ")
    add(f"**Страниц проанализировано:** {data.get('pages_analysed', 0)}")
    add("")
    add("> " + DISCLAIMER)
    add("")

    alert = coverage_alert(data)
    if alert:
        add("> [!WARNING]")
        add("> " + alert)
        add("")

    add("## Резюме")
    add("")
    # Пунктов больше, чем правил: у DISC-003 две строки — по перечню Минюста и
    # по списку ФСБ. Называть это «правилами» значит завышать охват.
    awaiting = [f for f in s["unknowns"] if f.get("needs_llm")]
    add(f"Проверено пунктов: {len(data['findings'])}. "
        f"Нарушений: **{len(s['fails'])}**. "
        f"Нужна ручная проверка: {len(s['warns'])}. "
        f"Без вывода: {len(s['unknowns'])}"
        + (f", из них {len(awaiting)} ждут смыслового анализа документов."
           if awaiting else "."))
    add("")
    if s["exposure"]:
        add(f"Суммарная верхняя граница санкций по выявленным нарушениям — "
            f"**{money(s['exposure'])}**. Оценка приблизительная: она складывается из "
            f"максимумов по каждому составу и не учитывает оборотные штрафы, "
            f"которые в рублях заранее не выражаются.")
        add("")
    if data.get("degraded"):
        add(f"⚠️ Сбор данных шёл в ограниченном режиме "
            f"({data.get('degraded_reason') or 'без рендера страниц'}). "
            f"Часть правил проверить не удалось — см. раздел «Что проверить вручную».")
        add("")

    if s["fails"]:
        add("### Требует внимания в первую очередь")
        add("")
        for f in sort_findings(s["fails"])[:5]:
            fine = max_fine(f)
            add(f"- **{f['title']}** ({f['rule_id']}) — {sentence(f['summary'])}"
                + (f" Риск до {money(fine)}." if fine else ""))
        add("")

    # --- Таблица по группам ---
    detail_ids = {f["rule_id"] for f in data["findings"]
                  if f["status"] in ("FAIL", "WARN", "UNKNOWN")}
    add("## Чек-лист")
    add("")
    add("Идентификатор правила — ссылка на расшифровку ниже, если по пункту "
        "есть что разбирать.")
    add("")
    for group, title in GROUP_RU.items():
        items = [f for f in data["findings"] if f["group"] == group]
        if not items:
            continue
        add(f"### {title}")
        add("")
        add("| Правило | Норма | Статус | Штраф юрлицу, ₽ | Что обнаружено |")
        add("|---------|-------|--------|-----------------|----------------|")
        for f in sort_findings(items):
            rid = (f"[`{f['rule_id']}`](#{anchor(f['rule_id'])})"
                   if f["rule_id"] in detail_ids else f"`{f['rule_id']}`")
            add(f"| {rid} {f['title']} | {f.get('norm') or '—'} "
                f"| **{status_label(f)}** "
                f"| {fine_amount(f)} | {f['summary']} |")
        add("")

    # --- Подробности по нарушениям ---
    detailed = sort_findings(s["fails"] + s["warns"])
    if detailed:
        add("## Подробно по каждому нарушению")
        add("")
        for f in detailed:
            add(f'<a id="{anchor(f["rule_id"])}"></a>')
            add("")
            add(f"### `{f['rule_id']}` {f['title']}")
            add("")
            add(f"**Статус:** {status_label(f)} · "
                f"**риск:** {SEVERITY_RU.get(f['severity'], '')} · "
                f"**штраф юрлицу:** {fine_display(f)}")
            add("")
            if f.get("norm"):
                add(f"**Норма.** {f['norm']}")
                add("")
            if f.get("liability"):
                add(f"**Ответственность.** {f['liability']}")
                add("")
            add(f"**Обнаружено.** {sentence(f['summary'])}")
            add("")
            if f.get("evidence"):
                add("**Доказательства.**")
                add("")
                for e in f["evidence"]:
                    line = f"- {e['detail']}"
                    if e.get("url"):
                        line += f" — `{e['url']}`"
                    if e.get("selector"):
                        line += f" (страница `{e['selector']}`)"
                    add(line)
                    if e.get("snippet"):
                        add(f"  > {e['snippet'][:300]}")
                add("")
            if f.get("source_note"):
                add(f"**Источник данных.** {f['source_note']}")
                add("")
            if f.get("fix_hint"):
                add(f"**Как устранить.** {f['fix_hint']}")
                add("")

    # --- Что осталось проверить руками ---
    if s["unknowns"]:
        add("## Что проверить вручную")
        add("")
        add("По этим пунктам вывода нет. Отсутствие вывода — не отсутствие "
            "нарушения: это значит, что автоматическая проверка их не закрывает. "
            "Ниже — не что исправлять, а что открыть и на что посмотреть, чтобы "
            "получить статус.")
        add("")
        for f in sort_findings(s["unknowns"]):
            add(f'<a id="{anchor(f["rule_id"])}"></a>')
            add("")
            add(f"### `{f['rule_id']}` {f['title']}")
            add("")
            add(f"**Почему нет вывода.** {sentence(f['summary'])}")
            add("")
            add("**Как проверить.**")
            add("")
            add(manual_hint(f))
            add("")

    # --- Источники данных ---
    if data.get("registry_status"):
        add("## Источники данных о реестрах")
        add("")
        add("| Реестр | Откуда | Записей | Возраст |")
        add("|--------|--------|---------|---------|")
        for key, st in data["registry_status"].items():
            trust = {"official": "официальный источник", "attested": "зеркало с "
                     "подтверждённым происхождением", "mirror": "неофициальное зеркало"}.get(
                         st.get("trust"), st.get("trust") or "—")
            age = f"{st['stale_days']:.1f} д" if st.get("stale_days") is not None else "—"
            add(f"| {key} | {trust} | {st.get('entries', 0)} | {age} |")
        add("")

    if s["passes"]:
        add("## Соблюдается")
        add("")
        add(", ".join(f"`{f['rule_id']}` {f['title']}" for f in s["passes"]))
        add("")
    return "\n".join(out) + "\n"


# --- План устранения ---------------------------------------------------------

# Порядок работ: сперва дорогое и простое. Разработчик, начавший с дешёвого,
# оставляет клиента под самым крупным риском дольше, чем нужно.
PRIORITY_BUCKETS = [
    ("P0", "Критический риск, устраняется быстро", lambda f, e: f["severity"] == "critical"),
    ("P1", "Высокий риск", lambda f, e: f["severity"] == "high"),
    ("P2", "Средний риск", lambda f, e: f["severity"] == "medium"),
    ("P3", "Низкий риск и косметика", lambda f, e: True),
]

# Задачи, которые разработчик не может закрыть один: нужен юридический текст
# или решение владельца. Помечаются явно, иначе агент напишет политику сам.
NEEDS_LEGAL_INPUT = {"PDN-003", "PDN-008", "PDN-012", "PDN-013", "DISC-002",
                     "DISC-008", "DISC-009", "PDN-009", "CK-007"}


PLAN_COLOPHON = (
    "Сформировано скиллом `{name}` ({repo}). Автор: {author}, {email}.")


def plan_md(data: dict[str, Any]) -> str:
    s = summarise(data)
    actionable = sort_findings(s["fails"] + s["warns"])
    out: list[str] = []
    add = out.append

    add(f"# Часть II. План устранения — {site_name(data)}")
    add("")
    add(f"**Сайт:** {data['target']}  ")
    add(f"**Основание:** часть I настоящего документа от {data['generated_at'][:10]}  ")
    add(f"**Задач:** {len(actionable)}")
    add("")
    add("Документ предназначен для исполнения агентом-разработчиком. Каждая "
        "задача содержит место изменения, требуемое действие и критерий приёмки. "
        "Задачи, помеченные «нужен вход от заказчика», без юридического текста "
        "закрывать нельзя — писать его самостоятельно недопустимо.")
    add("")
    add("## Порядок работ")
    add("")
    add("Задачи отсортированы по убыванию риска. Не переставлять: начав с "
        "простого, вы оставите заказчика под самым крупным штрафом дольше, чем нужно.")
    add("")

    counter = 0
    assigned: set[str] = set()
    for code, title, predicate in PRIORITY_BUCKETS:
        bucket = [f for f in actionable
                  if f["rule_id"] not in assigned and predicate(f, None)]
        if not bucket:
            continue
        add(f"## {code}. {title}")
        add("")
        for f in bucket:
            assigned.add(f["rule_id"])
            counter += 1
            needs_legal = f["rule_id"] in NEEDS_LEGAL_INPUT
            add(f"### {code}-{counter:02d}. {f['title']}")
            add("")
            add(f"**Правило:** [`{f['rule_id']}`](#{anchor(f['rule_id'])}) · "
                f"**пункт записки:** «{f['title']}»")
            if needs_legal:
                add("")
                add("**⚠️ Нужен вход от заказчика.** Задача требует юридического "
                    "текста или решения владельца. Разработчик реализует форму и "
                    "размещение, но не сочиняет содержание.")
            add("")
            add(f"**Что обнаружено.** {f['summary']}")
            add("")
            where = describe_locations(f)
            if where:
                add("**Где менять.**")
                add("")
                for w in where:
                    add(f"- {w}")
                add("")
            if f.get("fix_hint"):
                add(f"**Что сделать.** {f['fix_hint']}")
                add("")
            add(f"**Критерий приёмки.** {acceptance(f)}")
            add("")
    add("---")
    add("")
    add(PLAN_COLOPHON.format(name=SKILL_NAME, repo=SKILL_REPO,
                             author=SKILL_AUTHOR, email=SKILL_EMAIL))
    add("")
    return "\n".join(out) + "\n"


def describe_locations(finding: dict[str, Any]) -> list[str]:
    """Места изменения в терминах, пригодных для исполнения."""
    out: list[str] = []
    for e in finding.get("evidence", [])[:8]:
        if e.get("selector") and e.get("url"):
            out.append(f"страница `{e['url']}`, элемент `{e['selector']}`")
        elif e.get("url"):
            out.append(f"`{e['url']}` — {e['detail']}")
        elif e.get("selector"):
            out.append(f"страница `{e['selector']}` — {e['detail']}")
        else:
            out.append(e["detail"])
    return list(dict.fromkeys(out))


def acceptance(finding: dict[str, Any]) -> str:
    """Критерий приёмки формулируется как проверяемый факт, а не как намерение.

    «Исправить политику» — не критерий. «Повторный прогон detect.py даёт по
    правилу статус PASS» — критерий, и его может проверить сам агент.
    """
    rule = finding["rule_id"]
    script_checked = finding.get("check") in (None, "script", "hybrid")
    # Правило, которое скрипт не закрывает, прогоном не примешь: detect.py по
    # нему никогда не выставит PASS, и такой критерий отправляет разработчика
    # добиваться недостижимого. Для них критерий — проверяемое утверждение о
    # самом документе.
    base = ((f"Повторный прогон `scripts/detect.py` по правилу `{rule}` "
             f"возвращает статус PASS") if script_checked
            else (f"Проверяющий подтверждает по тексту документа: "
                  f"{(finding.get('pass_criterion') or 'требование выполнено')[0].lower()}"
                  f"{(finding.get('pass_criterion') or 'требование выполнено')[1:]}"))
    specific = {
        "PDN-004": "в каждой форме сбора персональных данных присутствует "
                   "отдельный непредотмеченный чекбокс согласия",
        "PDN-005": "ни один чекбокс согласия не имеет атрибута checked ни в "
                   "разметке, ни в начальном состоянии компонента",
        "PDN-006": "подпись каждого чекбокса содержит рабочую ссылку на политику",
        "CK-001": "баннер согласия отображается до загрузки аналитики",
        "CK-002": "в баннере есть кнопка отказа, визуально равнозначная кнопке согласия",
        "CK-003": "в сетевом логе до нажатия кнопки согласия нет запросов к "
                  "аналитическим и рекламным доменам",
        "CK-005": "иностранные аналитические и рекламные трекеры отсутствуют "
                  "либо заменены российскими аналогами",
        "AUTH-001": "кнопки и SDK иностранных провайдеров входа удалены, "
                    "вход работает через разрешённый способ",
        "AUTH-002": "виджет входа через Telegram удалён",
        "AUTH-003": "аутентификация не использует иностранные сервисы идентификации",
        "DISC-004": "при каждом упоминании Instagram, Facebook или Meta присутствует "
                    "указание на запрет деятельности",
        "DISC-005": "иконки и логотипы Instagram и Facebook удалены со всех страниц",
        "ORG-001": "ИНН и ОГРН опубликованы и проходят проверку контрольной суммы",
        "INF-001": "запрос по http:// возвращает редирект на https://",
        # Хостинг в РФ детектор подтвердить не может: принадлежность провайдера
        # реестру РКН проверяется по самому реестру, а не по геоданным IP.
        "INF-002": "хостинг-провайдер найден в реестре РКН (rkn.gov.ru, реестр "
                   "провайдеров хостинга) либо сайт перенесён к провайдеру из реестра",
    }
    if rule == "INF-002":
        return (specific["INF-002"][0].upper() + specific["INF-002"][1:] + ".")
    extra = specific.get(rule)
    if not extra:
        return base + "."
    return f"{extra[0].upper()}{extra[1:]}; {base[0].lower()}{base[1:]}."


def combined_md(data: dict[str, Any]) -> str:
    """Записка и план в одном документе двумя частями.

    Разведены они по-прежнему жёстко: у частей разные читатели и разные задачи.
    Но живут в одном файле — иначе при передаче теряется половина, а ссылки из
    плана на пункты записки перестают работать.
    """
    head = [
        f"# {site_name(data)} — проверка на соответствие требованиям РФ",
        "",
        f"**Ресурс:** {data['target']}  ",
        f"**Дата:** {data['generated_at'][:10]}",
        "",
        "Документ состоит из двух частей. **Часть I** — аналитическая записка "
        "для владельца сайта и юриста: что обнаружено, какой нормой это "
        "регулируется и чем подтверждается. **Часть II** — план устранения для "
        "разработчика: что именно сделать и как проверить результат.",
        "",
        "---",
        "",
    ]
    colophon = "\n".join(["", "---", "", "## О проверке", ""]
                         + colophon_lines(data) + [""])
    return ("\n".join(head) + report_md(data) + "\n---\n\n" + plan_md(data)
            + colophon)


# --- HTML --------------------------------------------------------------------

CSS = """
:root { --fail:#b3261e; --warn:#8a5a00; --pass:#1b5e20; --unknown:#5f6368; --na:#9aa0a6;
        --bg:#ffffff; --fg:#1f1f1f; --muted:#5f6368; --line:#e3e3e3; --card:#f7f7f7; }
* { box-sizing:border-box; }
body { margin:0; padding:0 0 4rem; background:var(--bg); color:var(--fg);
       font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:60rem; margin:0 auto; padding:2rem 1.25rem; }
h1 { font-size:1.9rem; line-height:1.25; margin:0 0 .5rem; }
h2 { font-size:1.35rem; margin:2.5rem 0 .75rem; padding-bottom:.35rem;
     border-bottom:2px solid var(--line); }
h3 { font-size:1.05rem; margin:1.75rem 0 .5rem; }
.meta { color:var(--muted); margin-bottom:1.5rem; }
.disclaimer { background:var(--card); border-left:4px solid var(--muted);
              padding:.9rem 1.1rem; margin:1.5rem 0; color:var(--muted); font-size:.92rem; }
.kpis { display:flex; flex-wrap:wrap; gap:.75rem; margin:1.5rem 0; }
.kpi { flex:1 1 9rem; background:var(--card); border-radius:.5rem; padding:.9rem 1rem; }
.kpi .n { font-size:1.6rem; font-weight:700; line-height:1.1; }
.kpi .l { color:var(--muted); font-size:.82rem; }
.kpi.fail .n { color:var(--fail); } .kpi.warn .n { color:var(--warn); }
.kpi.unknown .n { color:var(--unknown); } .kpi.pass .n { color:var(--pass); }
table { width:100%; border-collapse:collapse; margin:1rem 0; font-size:.92rem; }
th,td { text-align:left; padding:.55rem .6rem; border-bottom:1px solid var(--line);
        vertical-align:top; }
th { background:var(--card); font-weight:600; }
.badge { display:inline-block; padding:.1rem .5rem; border-radius:.25rem;
         font-size:.78rem; font-weight:600; white-space:nowrap; color:#fff; }
.badge.FAIL{background:var(--fail);} .badge.WARN{background:var(--warn);}
.badge.PASS{background:var(--pass);} .badge.UNKNOWN{background:var(--unknown);}
.badge.NA{background:var(--na);}
.finding { border:1px solid var(--line); border-radius:.5rem; padding:1rem 1.15rem;
           margin:1rem 0; }
.finding.FAIL { border-left:4px solid var(--fail); }
.finding.WARN { border-left:4px solid var(--warn); }
.ev { background:var(--card); border-radius:.4rem; padding:.6rem .8rem; margin:.5rem 0;
      font-size:.88rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
      word-break:break-all; }
.ev q { display:block; font-family:inherit; color:var(--muted); margin-top:.35rem; }
code { background:var(--card); padding:.1rem .3rem; border-radius:.2rem; font-size:.9em; }
.rule-id { color:var(--muted); font-weight:400; }
.hint { color:var(--muted); font-size:.85rem; margin:.25rem 0 .75rem; }
td.norm { font-size:.82rem; color:var(--muted); }
td.fine { font-size:.85rem; }
/* Ширины колонок заданы явно: без этого «Правило» сжимается в столбик по
   одному слову, а редкая длинная санкция растягивает свою колонку на треть
   страницы. В PDF колонки не переверстать, поэтому раскладка фиксированная. */
table.checklist { table-layout:fixed; }
table.checklist td, table.checklist th { overflow-wrap:break-word; hyphens:auto; }
table.checklist col.c-rule { width:25%; }
table.checklist col.c-norm { width:13%; }
table.checklist col.c-status { width:15%; }
table.checklist col.c-fine { width:18%; }
table.checklist col.c-found { width:29%; }
/* Внутри чек-листа плашка статуса переносится: «НУЖНА РУЧНАЯ ПРОВЕРКА» одной
   строкой шире своей колонки и наезжает на соседнюю. */
table.checklist .badge { white-space:normal; overflow-wrap:normal; hyphens:none; }
table.manual { table-layout:fixed; }
table.manual td { overflow-wrap:break-word; hyphens:auto; }
table.manual col.m-rule { width:26%; }
table.manual col.m-why { width:30%; }
table.manual col.m-how { width:44%; }
/* Раскладка «stacked»: норма и штраф уходят под основное поле мелким шрифтом,
   и ни одна колонка не остаётся уже своего содержимого. */
table.checklist col.s-rule { width:38%; }
table.checklist col.s-status { width:22%; }
table.checklist col.s-found { width:40%; }
table.checklist .sub { color:var(--muted); font-size:.8rem; margin-top:.25rem;
                       line-height:1.35; }
/* Раскладка «twoline»: шапка пункта отдельной строкой, подробности — второй. */
table.checklist col.t-rule { width:58%; }
table.checklist col.t-status { width:22%; }
table.checklist col.t-fine { width:20%; }
table.checklist tr.head td { border-bottom:none; padding-bottom:.2rem; }
table.checklist tr.body td { padding-top:0; color:var(--fg); font-size:.88rem; }
table.checklist tr.body .sub { color:var(--muted); font-size:.8rem; }
table.checklist tr.head, table.checklist tr.body { page-break-inside:avoid; }
.manualitem { border:1px solid var(--line); border-left:4px solid var(--unknown);
              border-radius:.5rem; padding:.9rem 1.15rem; margin:1rem 0; }
.manualitem h3 { margin:0 0 .5rem; }
pre.cmd { background:var(--card); border-radius:.4rem; padding:.7rem .8rem;
          font-size:.82rem; overflow-x:auto; white-space:pre-wrap;
          word-break:break-all; margin:.5rem 0; }
.colophon { background:var(--card); border-radius:.5rem; padding:1rem 1.15rem;
            margin:1rem 0; font-size:.92rem; color:var(--muted); }
.colophon ul { margin:.5rem 0; padding-left:1.2rem; }
.colophon a { color:inherit; }
.alert { background:#fdf1ef; border-left:4px solid var(--fail); color:var(--fg);
         padding:.9rem 1.1rem; margin:1.5rem 0; font-size:.95rem; }
.warnbox { background:var(--card); border-left:4px solid var(--warn);
           padding:.7rem .9rem; margin:.6rem 0; font-size:.9rem; }
.parttitle { margin-top:2.5rem; }
.partbreak { page-break-before:always; height:0; }
a { color:inherit; }
@media print { body{font-size:11pt;} .wrap{max-width:none;padding:0;} h2{page-break-after:avoid;}
               .finding{page-break-inside:avoid;} }
@media (prefers-color-scheme: dark) {
  :root { --bg:#1b1b1b; --fg:#e8e8e8; --muted:#a8abb0; --line:#3a3a3a; --card:#252525;
          --fail:#f2b8b5; --warn:#f0c26b; --pass:#a6d4a8; }
}
"""


def esc(text: Any) -> str:
    # Ноль — значимое значение: «страниц: 0» и «страниц: » читаются по-разному,
    # а второе выглядит как сбой вёрстки, а не как факт.
    return "" if text is None else html.escape(str(text))


URL_RE = re.compile(r"https?://[^\s<>()\[\]«»\"']+")


def linkify(text: str) -> str:
    """Экранирует текст и делает ссылки кликабельными.

    Адрес формы РКН, набранный руками с бумаги, — это лишняя минута и опечатка.
    В записке, которую откроют в браузере, ссылка должна быть ссылкой.
    """
    out = esc(text)
    return URL_RE.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', out)


def md_inline(text: str) -> str:
    """Экранирует текст и оставляет работать только **жирный** — больше в
    коротких врезках ничего и не нужно."""
    out = esc(text)
    while out.count("**") >= 2:
        out = out.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
    return out


def rule_cell(finding: dict[str, Any], detail_ids: set[str]) -> str:
    rid = esc(finding["rule_id"])
    marked = (f"<a href='#{anchor(finding['rule_id'])}'><span class=rule-id>{rid}</span></a>"
              if finding["rule_id"] in detail_ids
              else f"<span class=rule-id>{rid}</span>")
    return f"{marked} {esc(finding['title'])}"


def checklist_table_html(items: list[dict[str, Any]], detail_ids: set[str],
                         layout: str) -> str:
    """Чек-лист одной группы. Три раскладки под разную ширину строки.

    Пять колонок дают самую плотную таблицу, но на A4 «Норма» шириной в 13%
    рассыпает «ст. 9 Закона РФ от 07.02.1992 № 2300-1» в десяток строк, и
    таблица читается хуже, чем список. Поэтому раскладка выбирается, а не
    зашита: узкие второстепенные поля можно убрать под основное или вынести
    во вторую строку.
    """
    out: list[str] = []
    add = out.append
    if layout == "stacked":
        add("<table class='checklist stacked'><colgroup><col class=s-rule>"
            "<col class=s-status><col class=s-found></colgroup>"
            "<tr><th>Правило и норма</th><th>Статус и штраф юрлицу, ₽</th>"
            "<th>Что обнаружено</th></tr>")
        for f in items:
            add(f"<tr><td>{rule_cell(f, detail_ids)}"
                f"<div class=sub>{esc(f.get('norm') or '—')}</div></td>"
                f"<td><span class='badge {esc(f['status'])}'>{esc(status_label(f))}</span>"
                + (f"<div class=sub>{esc(fine_amount(f))}</div>"
                   if fine_amount(f) != "—" else "")
                + "</td>"
                f"<td>{esc(f['summary'])}</td></tr>")
        add("</table>")
    elif layout == "twoline":
        add("<table class='checklist twoline'><colgroup><col class=t-rule>"
            "<col class=t-status><col class=t-fine></colgroup>"
            "<tr><th>Правило</th><th>Статус</th><th>Штраф юрлицу, ₽</th></tr>")
        for f in items:
            add(f"<tr class=head><td>{rule_cell(f, detail_ids)}</td>"
                f"<td><span class='badge {esc(f['status'])}'>{esc(status_label(f))}</span></td>"
                f"<td class=fine>{esc(fine_amount(f))}</td></tr>")
            add(f"<tr class=body><td colspan=3>"
                f"<span class=sub>{esc(f.get('norm') or '—')}</span> · "
                f"{esc(f['summary'])}</td></tr>")
        add("</table>")
    else:
        add("<table class=checklist><colgroup><col class=c-rule><col class=c-norm>"
            "<col class=c-status><col class=c-fine><col class=c-found></colgroup>"
            "<tr><th>Правило</th><th>Норма</th><th>Статус</th>"
            "<th>Штраф юрлицу, ₽</th><th>Что обнаружено</th></tr>")
        for f in items:
            add(f"<tr><td>{rule_cell(f, detail_ids)}</td>"
                f"<td class=norm>{esc(f.get('norm') or '—')}</td>"
                f"<td><span class='badge {esc(f['status'])}'>{esc(status_label(f))}</span></td>"
                f"<td class=fine>{esc(fine_amount(f))}</td>"
                f"<td>{esc(f['summary'])}</td></tr>")
        add("</table>")
    return "".join(out)


def report_html(data: dict[str, Any], layout: str = "stacked") -> str:
    s = summarise(data)
    p: list[str] = []
    add = p.append
    add("<!doctype html><html lang=ru><head><meta charset=utf-8>")
    add('<meta name=viewport content="width=device-width,initial-scale=1">')
    add(f"<title>{esc(site_name(data))} — проверка на соответствие требованиям РФ</title>")
    add(f"<style>{CSS}</style></head><body><div class=wrap>")
    add(f"<h1>{esc(site_name(data))} — проверка на соответствие требованиям РФ</h1>")
    add("<p>Документ состоит из двух частей. <b>Часть I</b> — аналитическая "
        "записка для владельца сайта и юриста. <b>Часть II</b> — план устранения "
        "для разработчика.</p>")
    add(f"<h1 class=parttitle>Часть I. Аналитическая записка — "
        f"{esc(site_name(data))}</h1>")
    add(f"<div class=meta>{esc(data['target'])} · проверено {esc(data['generated_at'][:10])} · "
        f"страниц: {esc(data.get('pages_analysed', 0))}</div>")
    add(f"<div class=disclaimer>{esc(DISCLAIMER)}</div>")

    alert = coverage_alert(data)
    if alert:
        add(f"<div class=alert>{md_inline(alert)}</div>")

    add("<div class=kpis>")
    for cls, label, value in (("fail", "нарушений", len(s["fails"])),
                              ("warn", "нужна ручная проверка", len(s["warns"])),
                              ("unknown", "не проверено", len(s["unknowns"])),
                              ("pass", "соблюдается", len(s["passes"]))):
        add(f"<div class='kpi {cls}'><div class=n>{value}</div><div class=l>{label}</div></div>")
    if s["exposure"]:
        add(f"<div class='kpi fail'><div class=n>{esc(money(s['exposure']))}</div>"
            f"<div class=l>верхняя граница санкций</div></div>")
    add("</div>")

    if data.get("degraded"):
        add(f"<div class=disclaimer>⚠️ Сбор шёл в ограниченном режиме: "
            f"{esc(data.get('degraded_reason') or 'без рендера страниц')}. "
            f"Часть правил не проверена.</div>")

    detail_ids = {f["rule_id"] for f in data["findings"]
                  if f["status"] in ("FAIL", "WARN", "UNKNOWN")}
    add("<h2>Чек-лист</h2>")
    add("<p class=hint>Идентификатор правила — ссылка на расшифровку ниже.</p>")
    for group, title in GROUP_RU.items():
        items = [f for f in data["findings"] if f["group"] == group]
        if not items:
            continue
        add(f"<h3>{esc(title)}</h3>")
        add(checklist_table_html(sort_findings(items), detail_ids, layout))

    detailed = sort_findings(s["fails"] + s["warns"])
    if detailed:
        add("<h2>Подробно по каждому нарушению</h2>")
        for f in detailed:
            add(f"<div class='finding {esc(f['status'])}' id='{anchor(f['rule_id'])}'>")
            add(f"<h3><span class=rule-id>{esc(f['rule_id'])}</span> {esc(f['title'])} "
                f"<span class='badge {esc(f['status'])}'>{esc(status_label(f))}</span></h3>")
            add(f"<p class=hint>Штраф юрлицу: {esc(fine_display(f))}</p>")
            if f.get("norm"):
                add(f"<p><b>Норма.</b> {esc(f['norm'])}</p>")
            if f.get("liability"):
                add(f"<p><b>Ответственность.</b> {esc(f['liability'])}</p>")
            add(f"<p><b>Обнаружено.</b> {esc(f['summary'])}</p>")
            for e in f.get("evidence", []):
                bits = esc(e["detail"])
                if e.get("url"):
                    bits += f" — {esc(e['url'])}"
                if e.get("selector"):
                    bits += f" (страница {esc(e['selector'])})"
                snippet = f"<q>{esc(e['snippet'][:300])}</q>" if e.get("snippet") else ""
                add(f"<div class=ev>{bits}{snippet}</div>")
            if f.get("source_note"):
                add(f"<p><b>Источник данных.</b> {esc(f['source_note'])}</p>")
            if f.get("fix_hint"):
                add(f"<p><b>Как устранить.</b> {esc(f['fix_hint'])}</p>")
            add("</div>")

    if s["unknowns"]:
        add("<h2>Что проверить вручную</h2>")
        add("<p>По этим пунктам вывода нет. Отсутствие вывода — не отсутствие "
            "нарушения: автоматическая проверка их не закрывает. Ниже — не что "
            "исправлять, а что открыть и на что посмотреть, чтобы получить "
            "статус.</p>")
        for f in sort_findings(s["unknowns"]):
            add(f"<div class=manualitem id='{anchor(f['rule_id'])}'>")
            add(f"<h3><span class=rule-id>{esc(f['rule_id'])}</span> {esc(f['title'])}</h3>")
            add(f"<p><b>Почему нет вывода.</b> {esc(sentence(f['summary']))}</p>")
            add("<p><b>Как проверить.</b></p>")
            add(manual_blocks_html(manual_hint(f)))
            add("</div>")

    add(plan_html(data))
    add("<h2>О проверке</h2>")
    add("<div class=colophon>")
    add(f"<p>Проверка выполнена скиллом <b>{esc(SKILL_NAME)}</b> — открытый "
        f"набор правил и скриптов проверки сайта на соответствие требованиям "
        f"РФ.</p>")
    add("<ul>"
        f"<li>Автор: {esc(SKILL_AUTHOR)}</li>"
        f"<li>Исходники и обновления правил: <a href='{SKILL_REPO}'>{esc(SKILL_REPO)}</a></li>"
        f"<li>Канал автора: <a href='{SKILL_CHANNEL}'>{esc(SKILL_CHANNEL)}</a></li>"
        f"<li>Вопросы и замечания по проверке: "
        f"<a href='mailto:{SKILL_EMAIL}'>{esc(SKILL_EMAIL)}</a></li>"
        "</ul>")
    add(f"<p>Нормы и суммы санкций актуальны на дату проверки "
        f"({esc(data['generated_at'][:10])}). Законодательство меняется — перед "
        f"использованием записки в переписке или в суде сверьтесь с актуальной "
        f"редакцией.</p>")
    add("</div>")
    add("</div></body></html>")
    return "".join(p)


def plan_html(data: dict[str, Any]) -> str:
    s = summarise(data)
    actionable = sort_findings(s["fails"] + s["warns"])
    p: list[str] = []
    add = p.append
    add("<div class=partbreak></div>")
    add("<h1>Часть II. План устранения</h1>")
    add(f"<div class=meta>Задач: {len(actionable)} · основание — часть I</div>")
    add("<p>Документ предназначен для исполнения агентом-разработчиком. Задачи "
        "отсортированы по убыванию риска; порядок не переставлять.</p>")

    counter = 0
    assigned: set[str] = set()
    for code, title, predicate in PRIORITY_BUCKETS:
        bucket = [f for f in actionable
                  if f["rule_id"] not in assigned and predicate(f, None)]
        if not bucket:
            continue
        add(f"<h2>{esc(code)}. {esc(title)}</h2>")
        for f in bucket:
            assigned.add(f["rule_id"])
            counter += 1
            add(f"<div class='finding {esc(f['status'])}'>")
            add(f"<h3>{esc(code)}-{counter:02d}. {esc(f['title'])}</h3>")
            add(f"<p class=hint>Правило "
                f"<a href='#{anchor(f['rule_id'])}'>{esc(f['rule_id'])}</a> · "
                f"пункт части I</p>")
            if f["rule_id"] in NEEDS_LEGAL_INPUT:
                add("<div class=warnbox>⚠️ <b>Нужен вход от заказчика.</b> Задача "
                    "требует юридического текста или решения владельца. Разработчик "
                    "реализует форму и размещение, но не сочиняет содержание.</div>")
            add(f"<p><b>Что обнаружено.</b> {esc(sentence(f['summary']))}</p>")
            where = describe_locations(f)
            if where:
                add("<p><b>Где менять.</b></p><ul>")
                for w in where:
                    add(f"<li>{esc(w)}</li>")
                add("</ul>")
            if f.get("fix_hint"):
                add(f"<p><b>Что сделать.</b> {esc(f['fix_hint'])}</p>")
            add(f"<p><b>Критерий приёмки.</b> {esc(acceptance(f))}</p>")
            add("</div>")
    return "".join(p)


RUNNING_DISCLAIMER = (
    "Техническая проверка, не юридическое заключение. Ответственность за "
    "решения, принятые по этому документу, несёт его получатель.")


def pdf_header(data: dict[str, Any]) -> str:
    """Колонтитул страницы: чем сделана проверка и чей это сайт.

    Записку печатают, пересылают и подшивают — страницы живут отдельно от
    титульной. Колонтитул нужен тихий: серый, мелкий, одной строкой, чтобы
    отвечать на вопрос «что это за лист» и не лезть в глаза при чтении."""
    return (
        '<div style="width:100%;font-size:7pt;color:#8a8a8a;'
        'font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'padding:0 14mm;display:flex;justify-content:space-between;">'
        f'<span>{esc(site_name(data))} · проверка на соответствие требованиям РФ</span>'
        f'<span>{esc(SKILL_NAME)} · {esc(SKILL_CHANNEL.replace("https://", ""))}</span>'
        "</div>")


def pdf_footer() -> str:
    return (
        '<div style="width:100%;font-size:7pt;color:#8a8a8a;'
        'font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'padding:0 14mm;display:flex;justify-content:space-between;">'
        f'<span>{esc(RUNNING_DISCLAIMER)}</span>'
        '<span class="pageNumber"></span>'
        "</div>")


def html_to_pdf(html_path: Path, pdf_path: Path,
                data: dict[str, Any] | None = None) -> bool:
    """Печать через Chromium, который уже нужен краулеру."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.pdf(path=str(pdf_path), format="A4", print_background=True,
                     display_header_footer=True,
                     header_template=pdf_header(data or {"target": ""}),
                     footer_template=pdf_footer(),
                     margin={"top": "20mm", "bottom": "20mm",
                             "left": "14mm", "right": "14mm"})
            browser.close()
        return True
    except Exception as exc:
        print(f"  PDF не собран: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Сборка записки и плана из findings.json")
    ap.add_argument("--findings", default="findings.json")
    ap.add_argument("--out-dir", default="report")
    ap.add_argument("--format", default="md,html",
                    help="список через запятую: md, html, pdf")
    ap.add_argument("--layout", default="stacked",
                    choices=("stacked", "twoline", "wide"),
                    help="раскладка чек-листа в HTML и PDF")
    args = ap.parse_args()

    data = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    written: list[Path] = []

    if formats:
        p = out / "compliance-report.md"
        p.write_text(combined_md(data), encoding="utf-8"); written.append(p)
        # План отдельным файлом остаётся: его скармливают агенту-разработчику,
        # и подавать туда весь документ с нормами КоАП незачем.
        p = out / "remediation-plan.md"
        p.write_text(plan_md(data), encoding="utf-8"); written.append(p)

    html_path = out / "compliance-report.html"
    if "html" in formats or "pdf" in formats:
        html_path.write_text(report_html(data, args.layout), encoding="utf-8")
        written.append(html_path)

    if "pdf" in formats:
        pdf_path = out / "compliance-report.pdf"
        if html_to_pdf(html_path, pdf_path, data):
            written.append(pdf_path)
        else:
            print("  PDF пропущен: нет Playwright с Chromium "
                  "(pip install playwright && python -m playwright install chromium)",
                  file=sys.stderr)

    s = summarise(data)
    print(f"Нарушений: {len(s['fails'])} · требуют проверки: {len(s['warns'])} · "
          f"не проверено: {len(s['unknowns'])}", file=sys.stderr)
    if s["exposure"]:
        print(f"Верхняя граница санкций: {money(s['exposure'])}", file=sys.stderr)
    for p in written:
        print(f"  {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
