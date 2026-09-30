#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
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
    uv run --no-project scripts/render.py --findings findings.json --out-dir report/
    uv run --no-project --with playwright scripts/render.py --findings findings.json --out-dir report/ --format md,html,pdf
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import copy
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from report_provenance import collection_issues, collection_warnings, consistency_issues, provenance_issues, provenance_line
from network_evidence import safe_url
import report_evidence
from review_contract import valid_action_review

SCHEMA_VERSION = 1

# Статус называет, что делать владельцу: исправить, решить по риску, ответить
# на вопрос или ничего. «Нужна ручная проверка» из отчёта убрано: плагин сам
# добывает факты, а без вывода остаются только технические сбои сбора.
STATUS_RU = {"FAIL": "НАРУШЕНИЕ", "WARN": "РИСК", "PASS": "ОК",
             "NA": "НЕ ПРИМЕНИМО", "UNKNOWN": "НЕ ПРОВЕРЕНО", "EXTERNAL": "ВОПРОС ВЛАДЕЛЬЦУ"}


def network_summary(network):
    egress = network.get("egress", {})
    state = "завершён" if network.get("complete") else "НЕПОЛОН — зависимые выводы UNKNOWN"
    reason = (network.get("transport_error") or network.get("coverage_reason") or
              "причина не установлена")
    detail = f"Причина ограничения: {reason}. " if not network.get("complete") else ""
    return (f"Сетевой этап: {state}. Транспорт: {network.get('mode', 'UNKNOWN')}; "
            f"выход: {egress.get('ip', 'UNKNOWN')} ({egress.get('country', 'UNKNOWN')}); "
            f"период: {network.get('started_at', '?')} — {network.get('finished_at', '?')}. "
            + detail +
            "QUIC и непроксируемый WebRTC отключены; эта конфигурация может отличаться от обычного браузера.")


def visible_nonrequest_evidence(finding, owners, limit=5):
    """Show representative direct evidence once, while reserving all rows for the register."""
    unseen = []
    for entry in finding.get('evidence', []):
        if entry.get('kind') == 'request':
            continue
        key = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        if key not in owners:
            owners[key] = finding['rule_id']
            unseen.append(entry)
    return unseen[:limit], max(0, len(unseen) - limit)


def report_status(finding: dict[str, Any]) -> str:
    """Use the review attached by detect; never overwrite its machine observation.

    detect accepts reviews only for the current artifact fingerprint and checks
    service/purpose coverage. Rendering an old findings file remains a snapshot,
    not a new validation of the website or its legal basis.
    """
    review = finding.get("semantic_review") or {}
    return review.get("status", finding["status"])



def report_summary(f):
    if f.get("members"):
        return f["summary"]
    review = f.get("semantic_review") or {}
    if review:
        return review.get("summary") or ("Итог проверяющего: " + STATUS_RU.get(review.get("status"), "не установлен")
            + ". Основания: " + "; ".join(str(x) for x in review.get("evidence", [])))
    return f["summary"]


def public_data(data):
    data = copy.deepcopy(data)
    if collection_issues(data):
        for f in data.get('findings', []):
            f['status'] = 'UNKNOWN'
            f['semantic_review'] = None
            f['summary'] = 'Сбор не подтверждён: ' + f.get('summary', '')
    for f in data.get("findings", []):
        for e in f.get("evidence", []) + f.get("basis_evidence", []):
            if e.get("kind") == "request":
                e["url"] = safe_url(e.get("url"))
                for key in ("detail", "snippet"):
                    if e.get(key):
                        e[key] = re.sub(r"https?://[^\s<>`]+", lambda m: safe_url(m[0]), e[key])
    return data


def review_action(f):
    review = f.get("semantic_review") or {}
    return review.get("action") if valid_action_review(review) else None


def action_kind(f):
    """fix — у пункта есть правка; для нарушения и риска она есть всегда."""
    if f.get("members"):
        return f["action_kind"]
    action = review_action(f)
    if action:
        return action["kind"]
    return "fix" if report_status(f) in ("FAIL", "WARN") else "none"


def status_label(finding: dict[str, Any]) -> str:
    return STATUS_RU.get(report_status(finding), report_status(finding))


STATUS_ORDER = {"FAIL": 0, "WARN": 1, "EXTERNAL": 2, "UNKNOWN": 3, "PASS": 4, "NA": 5}


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
        "Нормы и санкции взяты из указанной версии правил; дата обхода не подтверждает их актуальность.",
    ]


DISCLAIMER = (
    "Техническая проверка сайта, не юридическое заключение. Правовую квалификацию "
    "подтверждает юрист; внутренние процессы, договоры и внешние площадки не проверялись.")


# --- Разбор сумм -------------------------------------------------------------




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
    by = lambda st: [f for f in findings if report_status(f) == st]
    fails = by("FAIL")
    return {"fails": fails, "warns": by("WARN"), "unknowns": by("UNKNOWN"),
            "externals": by("EXTERNAL"),
            "turnover_risk": [f for f in fails if "выручки" in (f.get("liability") or "")
                              or f.get("severity") == "critical"],
            "passes": by("PASS"), "nas": by("NA")}


def semantic_pending(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Пункты, которые смысловой слой обязан подтвердить, но не подтвердил.

    Машинная сверка текста политики с перечнем сведений даёт вердикт, но
    синоним или нестандартная формулировка могут его исказить. Отчёт без
    подтверждения этих пунктов — черновик, и об этом сказано на первой странице.
    """
    return [f for f in data["findings"]
            if f.get("needs_llm") and not f.get("semantic_review")
            and f.get("status") in ("FAIL", "WARN", "PASS")]


def page_urls(data: dict[str, Any]) -> dict[str, str]:
    return {p.get("slug"): p.get("url") for p in data.get("pages") or [] if p.get("slug")}


def locations(f: dict[str, Any], data: dict[str, Any], limit: int = 3) -> list[str]:
    """Где находка: адрес страницы или запроса, селектор. Без внутренних ID."""
    urls = page_urls(data)
    out: list[str] = []
    review = review_action(f)
    for loc in (review or {}).get("locations") or []:
        out.append(str(loc))
    for e in f.get("evidence") or []:
        slug = (e.get("selector") or "").split(" ")[0]
        where = e.get("url") or urls.get(slug)
        if not where and slug and slug not in urls:
            where = None
        if where:
            sel = " ".join((e.get("selector") or "").split(" ")[1:])
            out.append(where + (f" ({sel})" if sel else ""))
    unique = list(dict.fromkeys(out))
    if len(unique) > limit:
        return unique[:limit] + [f"ещё {len(unique) - limit} — evidence.html"]
    return unique


def remediation(f):
    """Что сделать: правка проверяющего, правка находки, правка правила."""
    action = review_action(f)
    if action:
        return action["text"]
    return f.get("fix_hint") or ""


def position_of(f, rules):
    rule = rules.get(f["rule_id"].rstrip("b")) or {}
    return rule.get("position") or {}


def load_rules() -> dict[str, dict[str, Any]]:
    path = Path(__file__).resolve().parent / "rules.json"
    return {r["id"]: r for r in json.loads(path.read_text(encoding="utf-8"))["rules"]}


def evidence_lines(f: dict[str, Any], data: dict[str, Any], limit: int = 6) -> tuple[list[tuple[str, str]], int]:
    """Строки доказательств: (текст, цитата). Сетевые — по получателю, без ID групп."""
    urls = page_urls(data)
    rows: list[tuple[str, str]] = []
    evidence = f.get("evidence") or []
    # У нарушения по перечню важно отсутствующее; найденное — в реестре.
    if any((e.get("detail") or "").startswith("отсутствует: ") for e in evidence):
        evidence = [e for e in evidence if not (e.get("detail") or "").startswith("есть: ")]
    for e in evidence:
        slug = (e.get("selector") or "").split(" ")[0]
        where = e.get("url") or urls.get(slug) or ""
        text = e.get("detail") or ""
        if where and where not in text:
            text += " — " + where
        rows.append((text, e.get("snippet") or ""))
    review = f.get("semantic_review") or {}
    for item in review.get("evidence") or []:
        rows.append(("Проверяющий: " + str(item), ""))
    unique = list(dict.fromkeys(rows))
    return unique[:limit], max(0, len(unique) - limit)


def machine_note(f: dict[str, Any]) -> str | None:
    review = f.get("semantic_review")
    if not review:
        return None
    return (f"Смысловая проверка: {STATUS_RU.get(review['status'], review['status'])}; "
            f"{review['reviewer']}, {review['reviewed_at']}. "
            f"Машинное наблюдение: {f['status']} — {f['summary']}")


def sort_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda f: (STATUS_ORDER.get(report_status(f), 9),
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


def basis_lines(f):
    lines = []
    review = f.get("semantic_review") or {}
    reviewed = {(a['service'], a['purpose']): a.get('verified_basis')
                for a in review.get('activities', [])}
    if f.get("processing_basis"):
        lines.append(f"Автоматически распознанное основание: {f['processing_basis']}; "
                     f"статус распознавания: {f.get('basis_status', 'UNKNOWN')}.")
    for a in f.get("processing_activities") or []:
        verified = reviewed.get((a['service'], a['purpose'])) or a.get('verified_basis') or 'UNKNOWN'
        lines.append(f"{a['service']} / {a['purpose']}: заявлено {a['declared_basis']}; "
                     f"проверенное основание: {verified}.")
    for e in f.get("basis_evidence") or []:
        lines.append(" — ".join(str(e[k]) for k in ("detail", "url", "selector", "snippet") if e.get(k)))
    if f.get("semantic_review"):
        review = f["semantic_review"]
        lines.append(f"Смысловая проверка: {review['status']}; "
                     f"{review['reviewer']}, {review['reviewed_at']}. "
                     f"Машинное наблюдение: {f['status']} — {f['summary']}")
        for a in review.get("activities", []):
            # Keep activity-specific proof, not only the rule's general evidence.
            lines.extend(f"{a['service']} / {a['purpose']}: {e}" for e in a.get('evidence', []))
        lines.extend(str(e) for e in review["evidence"])
    return list(dict.fromkeys(lines))



def basis_groups(data):
    groups = {}
    for finding in data['findings']:
        lines = tuple(basis_lines(finding))
        if lines:
            groups.setdefault(lines, []).append(finding)
    return [(members, lines) for lines, members in groups.items()]


def grouped_actions(items):
    """Одна правка — одна задача: баннер и запуск тегов чинятся вместе."""
    groups = {}
    mapping = {"CK-001": "consent", "CK-003": "consent", "LI-001": "consent", "CK-002": "consent",
               "CK-007": "consent", "CK-005": "foreign", "PDN-009": "foreign", "PDN-011": "foreign"}
    titles = {"consent": "Баннер согласия и запуск аналитики до выбора",
              "foreign": "Иностранные получатели данных"}
    for f in items:
        key = (mapping.get(f["rule_id"], f["rule_id"]), action_kind(f))
        groups.setdefault(key, []).append(f)
    result = []
    for key, members in groups.items():
        f = dict(members[0])
        f["members"] = members
        f["action_kind"] = key[1]
        f["title"] = titles.get(key[0], f["title"]) if len(members) > 1 else f["title"]
        f["summary"] = " ".join(dict.fromkeys(sentence(report_summary(m)) for m in members))
        f["evidence"] = [e for m in members for e in m.get("evidence", [])]
        f["basis_evidence"] = [e for m in members for e in m.get("basis_evidence", [])]
        f["fix_hint"] = " ".join(dict.fromkeys(remediation(m) for m in members if remediation(m)))
        f["status"] = min((m["status"] for m in members), key=lambda s: STATUS_ORDER.get(s, 9))
        worst = min(members, key=lambda m: (STATUS_ORDER.get(report_status(m), 9),
                                            SEVERITY_ORDER.get(m["severity"], 9)))
        f["severity"] = worst["severity"]
        f["semantic_review"] = worst.get("semantic_review") if len(members) == 1 else None
        f["_report_status"] = report_status(worst)
        result.append(f)
    return result


def checklist_items(f: dict[str, Any]) -> list[str]:
    """Перечень к задаче: что именно дописать или убрать — поимённо."""
    out = []
    for m in f.get("members", [f]):
        for e in m.get("evidence") or []:
            detail = e.get("detail") or ""
            if e.get("kind") == "cookie" and detail.startswith("не описаны"):
                out.append(detail)
            elif detail.startswith("отсутствует: "):
                out.append(detail[len("отсутствует: "):])
    return list(dict.fromkeys(out))


def action_rules(f):
    return ", ".join(m["rule_id"] for m in f.get("members", [f]))


def headline(data: dict[str, Any], s: dict[str, Any]) -> str:
    fails, warns = len(s["fails"]), len(s["warns"])
    if not data.get("pages_analysed"):
        return "Проверка не состоялась: ни одна страница сайта не собрана."
    if not fails and not warns:
        return "Нарушений и рисков не найдено."
    def gist(f):
        text = re.split(r";|\. ", report_summary(f))[0].strip().rstrip(".")
        return text if len(text) <= 90 else text[:87].rsplit(" ", 1)[0] + "…"
    top = [f"{f['rule_id']} — {gist(f)}" for f in sort_findings(s["fails"])[:3]]
    return (f"Нарушений: {fails}, рисков: {warns}."
            + (" Крупнейшие: " + "; ".join(top) + "." if top else ""))


def coverage_line(data: dict[str, Any], s: dict[str, Any]) -> str:
    total = len(data["findings"])
    decided = total - len(s["unknowns"])
    return (f"Вердикт вынесен по {decided} из {total} пунктов"
            + (f"; не проверено из-за сбоя сбора: {len(s['unknowns'])}" if s["unknowns"] else "")
            + (f"; вопросов владельцу: {len(s['externals'])}" if s["externals"] else "") + ".")


def limits_line(data: dict[str, Any]) -> str | None:
    """Ограничения снимка одной строкой: читателю нужно знать, но не три баннера."""
    parts = [w.rstrip(".") for w in collection_warnings(data)]
    return ("Ограничения сбора: " + "; ".join(parts) + ".") if parts else None


def report_md(data: dict[str, Any]) -> str:
    data = public_data(data)
    s = summarise(data)
    rules = load_rules()
    out: list[str] = []
    add = out.append

    add(f"# Часть I. Результаты проверки — {site_name(data)}")
    add("")
    add(f"**Ресурс:** {data['target']} · **дата:** {data['generated_at'][:10]} · "
        f"**страниц:** {data.get('pages_analysed', 0)}")
    add("")
    for issue in provenance_issues(data):
        add("> **Несовместимые входные данные.** " + issue)
    for issue in collection_issues(data):
        add("> **Ограниченный снимок.** " + issue)
    for issue in consistency_issues(data):
        add("> **Противоречивые выводы.** " + issue)
    pending = semantic_pending(data)
    if pending:
        add("> **Черновик.** Смысловая проверка не выполнена по пунктам "
            + ", ".join(f["rule_id"] for f in pending)
            + ": их вердикты машинные, до подтверждения документ не передавать.")
    alert = coverage_alert(data)
    if alert:
        add("> [!WARNING]")
        add("> " + alert)
    add("")
    add(f"**{headline(data, s)}** {coverage_line(data, s)}")
    add("")
    limits = limits_line(data)
    if limits:
        add(limits)
        add("")

    if s["fails"]:
        add("## Нарушения — исправить")
        add("")
        add("| Правило | Что не так | Где | Что сделать | Штраф юрлицу, ₽ |")
        add("|---|---|---|---|---|")
        for f in sort_findings(s["fails"]):
            where = "<br>".join(locations(f, data)) or "—"
            add(f"| [`{f['rule_id']}`](#{anchor(f['rule_id'])}) {f['title']} | {report_summary(f)} "
                f"| {where} | {remediation(f) or '—'} | {fine_amount(f)} |")
        add("")
        add("Суммы по правилам не складываются: несколько находок могут относиться к одному эпизоду.")
        add("")

    if s["warns"]:
        add("## Риски — решить")
        add("")
        for f in sort_findings(s["warns"]):
            pos = position_of(f, rules)
            add(f"- **[`{f['rule_id']}`](#{anchor(f['rule_id'])}) {f['title']}.** {sentence(report_summary(f))}"
                + (f" Позиция: {sentence(pos['verdict'])}" if pos.get("verdict") else "")
                + (f" Что сделать: {sentence(remediation(f))}" if remediation(f) else "")
                + (f" Снимается: {sentence(pos['lifted_by'])}" if pos.get("lifted_by") else ""))
        add("")

    if s["externals"]:
        add("## Вопросы владельцу")
        add("")
        add("Снаружи сайта это не видно. Ответ владельца закрывает пункт.")
        add("")
        for f in s["externals"]:
            add(f"- **`{f['rule_id']}` {f['title']}.** {sentence(report_summary(f))}")
        add("")

    if s["unknowns"]:
        add("## Не проверено из-за сбоя сбора")
        add("")
        add("Причина техническая; повторный запуск её устраняет.")
        add("")
        for f in sort_findings(s["unknowns"]):
            add(f"- `{f['rule_id']}` {f['title']} — {report_summary(f)}")
        add("")

    detailed = sort_findings(s["fails"] + s["warns"] + s["externals"])
    if detailed:
        add("## Доказательства и нормы")
        add("")
        add("Полный реестр наблюдений: [evidence.html](evidence.html) / [evidence.json](evidence.json).")
        add("")
        for f in detailed:
            add(f'<a id="{anchor(f["rule_id"])}"></a>')
            add("")
            add(f"### `{f['rule_id']}` {f['title']} — {status_label(f)}")
            add("")
            if f.get("norm"):
                add(f"**Норма.** {f['norm']}" + (f" **Ответственность.** {f['liability']}" if f.get("liability") else ""))
                add("")
            add(f"**Обнаружено.** {sentence(report_summary(f))}")
            add("")
            note = machine_note(f)
            if note:
                add(note)
                add("")
            rows, hidden = evidence_lines(f, data)
            for text, snippet in rows:
                add(f"- {text}")
                if snippet:
                    add(f"  > {snippet}")
            if hidden:
                add(f"- Ещё {hidden}: evidence.html / evidence.json.")
            if rows:
                add("")
            if f.get("source_note"):
                add(f"**Источник данных.** {f['source_note']}")
                add("")

    add("## Приложение. Все пункты")
    add("")
    add("| Правило | Норма | Статус | Штраф юрлицу, ₽ | Итог |")
    add("|---|---|---|---|---|")
    for group, title in GROUP_RU.items():
        items = [f for f in data["findings"] if f["group"] == group]
        for f in sort_findings(items):
            add(f"| `{f['rule_id']}` {f['title']} | {f.get('norm') or '—'} | **{status_label(f)}** "
                f"| {fine_amount(f)} | {report_summary(f)} |")
    add("")

    if data.get("registry_status"):
        trust_ru = {"official": "официальный", "attested": "зеркало с подтверждением",
                    "mirror": "неофициальное зеркало"}
        add("**Источники реестров:** " + "; ".join(
            f"{key}: {trust_ru.get(st.get('trust'), st.get('trust') or '—')}, записей {st.get('entries', 0)}"
            for key, st in data["registry_status"].items()) + ".")
        add("")
    add(provenance_line(data))
    add("")
    add(DISCLAIMER)
    add("")
    return "\n".join(out) + "\n"


# --- План устранения ---------------------------------------------------------

# Сначала нарушения, потом риски; внутри — по тяжести нормы.
PRIORITY_BUCKETS = [
    ("P0", "Нарушения с крупными штрафами", lambda f: f["_report_status"] == "FAIL"
     and f["severity"] in ("critical", "high")),
    ("P1", "Остальные нарушения", lambda f: f["_report_status"] == "FAIL"),
    ("P2", "Риски с крупными штрафами", lambda f: f["severity"] in ("critical", "high")),
    ("P3", "Остальные риски", lambda f: True),
]

# Правки, для которых владелец или юрист утверждает текст: разработчик не
# сочиняет политику сам, но задача от этого не перестаёт быть задачей.
NEEDS_LEGAL_INPUT = {"PDN-003", "PDN-008", "PDN-012", "PDN-013", "DISC-002", "ORG-003",
                     "DISC-008", "DISC-009", "PDN-009", "PDN-011", "CK-004", "LI-001"}


PLAN_COLOPHON = (
    "Сформировано скиллом `{name}` ({repo}). Автор: {author}, {email}.")


def plan_sections(data):
    data = public_data(data)
    s = summarise(data)
    actions = grouped_actions(sort_findings(s["fails"] + s["warns"]))
    sections, assigned = [], set()
    for code, title, predicate in PRIORITY_BUCKETS:
        bucket = [f for f in actions if id(f) not in assigned and predicate(f)]
        if bucket:
            sections.append((code, title, bucket))
            assigned.update(id(f) for f in bucket)
    return sections


def describe_locations(finding, data=None):
    """Confirmed change targets from the reviewer, else the observed places."""
    members = finding.get("members", [finding])
    out = []
    for m in members:
        action = review_action(m)
        out.extend((action or {}).get("locations") or [])
        if data is not None:
            out.extend(locations(m, data, limit=4))
    unique = [x for x in dict.fromkeys(out) if not x.startswith("ещё ")]
    return unique[:6] + ([f"ещё {len(unique) - 6} — evidence.html"] if len(unique) > 6 else [])


def plan_md(data: dict[str, Any]) -> str:
    sections = plan_sections(data)
    pub = public_data(data)
    out = [f"# Часть II. План исправлений — {site_name(data)}", "",
           f"**Сайт:** {data['target']}", "",
           f"**Задач:** {sum(len(rows) for _, _, rows in sections)}", "",
           "P0–P1 — нарушения, P2–P3 — риски. Каждая задача: что сделать, где и как принять.", ""]
    for code, title, rows in sections:
        out += [f"## {code}. {title}", ""]
        for i, f in enumerate(rows, 1):
            out += [f"### {code}-{i:02d}. {f['title']}", "", f"**Правила:** {action_rules(f)}", "",
                    f"**Что обнаружено.** {f['summary']}", ""]
            if any(m['rule_id'] in NEEDS_LEGAL_INPUT for m in f['members']):
                out += ["**Текст правки утверждает:** владелец или юрист.", ""]
            where = describe_locations(f, pub)
            if where:
                out += ["**Где.**", ""] + ['- ' + x for x in where] + [""]
            items = checklist_items(f)
            if items:
                out += ["**Перечень.**", ""] + ['- ' + x for x in items] + [""]
            out += [f"**Что сделать.** {f['fix_hint'] or 'Устранить обнаруженное по доказательствам части I.'}", "",
                    f"**Критерий приёмки.** {acceptance(f)}", ""]
    out += ['---', '', PLAN_COLOPHON.format(name=SKILL_NAME, repo=SKILL_REPO,
                                            author=SKILL_AUTHOR, email=SKILL_EMAIL), '']
    return '\n'.join(out)


def acceptance(finding: dict[str, Any]) -> str:
    """Проверяемый факт после правки, а не намерение."""
    if finding.get("members"):
        criteria = {}
        for member in finding["members"]:
            criteria.setdefault(acceptance(member), []).append(member["rule_id"])
        return " ".join(f"{', '.join(rules)}: {criterion}" for criterion, rules in criteria.items())
    rule = finding["rule_id"]
    action = review_action(finding)
    if action:
        return action["acceptance"]
    specific = {
        "CK-001": "при первом визите в чистом браузере показан запрос согласия, до выбора запросов к "
                  "сервисам аналитики и рекламы нет",
        "CK-002": "в баннере есть кнопка отказа; после отказа и повторного визита теги не загружаются",
        "CK-003": "журнал первого визита до выбора не содержит запросов к перечисленным сервисам",
        "CK-004": "каждое перечисленное имя cookie есть в политике с назначением и сроком",
        "CK-005": "иностранные трекеры удалены либо трансграничная передача описана в политике и "
                  "уведомление РКН подано",
        "CK-007": "кнопки «Принять» и «Отклонить» на первом экране баннера",
        "LI-001": "после нажатия «Отказаться» и повторного визита теги аналитики не загружаются",
        "PDN-003": "каждый перечисленный раздел есть в тексте политики",
        "PDN-004": "в каждой форме сбора персональных данных есть чекбокс согласия",
        "PDN-005": "ни один чекбокс согласия не отмечен по умолчанию",
        "PDN-006": "подпись каждого чекбокса содержит рабочую ссылку на политику",
        "PDN-008": "текст согласия содержит все перечисленные элементы, подпись чекбокса ведёт на него",
        "PDN-009": "запросов к иностранным получателям нет либо передача описана и уведомление подано",
        "PDN-012": "каждый перечисленный сервис и вид данных назван в политике",
        "PDN-013": "перечисленных лишних полей в формах нет",
        "AUTH-001": "кнопок и SDK иностранных провайдеров входа нет, вход работает через разрешённый способ",
        "AUTH-002": "виджета входа через Telegram нет",
        "AUTH-003": "аутентификация не использует иностранные сервисы идентификации",
        "DISC-004": "при каждом упоминании Instagram, Facebook или Meta есть указание на запрет",
        "DISC-005": "адресов и иконок Instagram и Facebook нет ни в видимой разметке, ни в JSON-LD",
        "DISC-008": "ссылок на заблокированные площадки на сайте нет",
        "DISC-009": "рекламы VPN на сайте нет",
        "ORG-001": "ИНН и ОГРН опубликованы и проходят проверку контрольной суммы",
        "ORG-003": "рядом с упоминанием ответственного указаны ФИО или должность и почта или телефон",
        "INF-001": "запрос по http:// возвращает редирект на https://",
        "INF-002": "организация сети сайта есть в реестре провайдеров хостинга РКН",
    }.get(rule)
    rerun = f"повторный аудит даёт по `{rule}` статус ОК"
    return (specific[0].upper() + specific[1:] + "; " + rerun + ".") if specific else rerun[0].upper() + rerun[1:] + "."


def combined_md(data: dict[str, Any]) -> str:
    head = [f"# {site_name(data)} — проверка на соответствие требованиям РФ", "",
            "**Часть I** — что нарушено, где и чем подтверждается. **Часть II** — план исправлений "
            "для разработчика.", "", "---", ""]
    colophon = "\n".join(["", "---", "", "## О проверке", ""] + colophon_lines(data) + [""])
    return "\n".join(head) + report_md(data) + "\n---\n\n" + plan_md(data) + colophon


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
.badge.NA{background:var(--na);} .badge.EXTERNAL{background:#3b5b8c;}
.lead { font-size:1.05rem; margin:1rem 0; }
.alert.draft { background:#fff6e0; border-left-color:var(--warn); }
table.violations { table-layout:fixed; }
table.violations td { overflow-wrap:anywhere; }
table.violations col.v-rule { width:20%; } table.violations col.v-what { width:26%; }
table.violations col.v-where { width:20%; } table.violations col.v-fix { width:22%; }
table.violations col.v-fine { width:12%; }
td.where { font-size:.82rem; }
.finding { border:1px solid var(--line); border-radius:.5rem; padding:1rem 1.15rem;
           margin:1rem 0; }
.finding h3 { margin:0 0 .5rem; }
.finding, .meta { overflow-wrap:anywhere; }
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
/* Внутри чек-листа плашка статуса переносится: «ВОПРОС ВЛАДЕЛЬЦУ» одной
   строкой шире своей колонки и наезжает на соседнюю. */
table.checklist .badge { white-space:normal; overflow-wrap:normal; hyphens:none; }
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
@media print {
  html { font-size:12px; }
  body { font:9.5pt/1.4 Arial,sans-serif; padding:0; }
  .wrap { max-width:none; padding:0; }
  h1 { font-size:18pt; } h2 { font-size:13pt; margin-top:1.5rem; }
  h3 { font-size:10.5pt; }
  h2,h3,thead { break-after:avoid; }
  tr,.finding { break-inside:avoid; }
  .finding p { margin:.5rem 0; }
  .finding { padding:.8rem; }
  .badge { white-space:normal; }
}
@media (prefers-color-scheme: dark) {
  :root { --bg:#1b1b1b; --fg:#e8e8e8; --muted:#a8abb0; --line:#3a3a3a; --card:#252525;
          --fail:#f2b8b5; --warn:#f0c26b; --pass:#a6d4a8; }
}
"""


def esc(text: Any) -> str:
    # Ноль — значимое значение: «страниц: 0» и «страниц: » читаются по-разному,
    # а второе выглядит как сбой вёрстки, а не как факт.
    return "" if text is None else html.escape(str(text))


def evidence_refs_md(line: str) -> str:
    parts = re.split(r'(G-[0-9a-f]{12}|evidence\.html|evidence\.json)', line)
    return ''.join(f'[{part}](evidence.html#{part})' if re.fullmatch(r'G-[0-9a-f]{12}', part)
                   else f'[{part}]({part})' if part in ('evidence.html', 'evidence.json')
                   else part for part in parts)


def evidence_refs_html(line: str) -> str:
    """Keep the printed group ID and make its register entry reachable in HTML."""
    parts = re.split(r'(G-[0-9a-f]{12}|evidence\.html|evidence\.json)', line)
    out = []
    for part in parts:
        if re.fullmatch(r'G-[0-9a-f]{12}', part):
            out.append(f'<a href="evidence.html#{part}">{part}</a>')
        elif part in ('evidence.html', 'evidence.json'):
            out.append(f'<a href="{part}">{part}</a>')
        else:
            out.append(esc(part))
    return ''.join(out)


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
                f"<td><span class='badge {esc(report_status(f))}'>{esc(status_label(f))}</span>"
                + (f"<div class=sub>{esc(fine_amount(f))}</div>"
                   if fine_amount(f) != "—" else "")
                + "</td>"
                f"<td>{esc(report_summary(f))}</td></tr>")
        add("</table>")
    elif layout == "twoline":
        add("<table class='checklist twoline'><colgroup><col class=t-rule>"
            "<col class=t-status><col class=t-fine></colgroup>"
            "<tr><th>Правило</th><th>Статус</th><th>Штраф юрлицу, ₽</th></tr>")
        for f in items:
            add(f"<tr class=head><td>{rule_cell(f, detail_ids)}</td>"
                f"<td><span class='badge {esc(report_status(f))}'>{esc(status_label(f))}</span></td>"
                f"<td class=fine>{esc(fine_amount(f))}</td></tr>")
            add(f"<tr class=body><td colspan=3>"
                f"<span class=sub>{esc(f.get('norm') or '—')}</span> · "
                f"{esc(report_summary(f))}</td></tr>")
        add("</table>")
    else:
        add("<table class=checklist><colgroup><col class=c-rule><col class=c-norm>"
            "<col class=c-status><col class=c-fine><col class=c-found></colgroup>"
            "<tr><th>Правило</th><th>Норма</th><th>Статус</th>"
            "<th>Штраф юрлицу, ₽</th><th>Что обнаружено</th></tr>")
        for f in items:
            add(f"<tr><td>{rule_cell(f, detail_ids)}</td>"
                f"<td class=norm>{esc(f.get('norm') or '—')}</td>"
                f"<td><span class='badge {esc(report_status(f))}'>{esc(status_label(f))}</span></td>"
                f"<td class=fine>{esc(fine_amount(f))}</td>"
                f"<td>{esc(report_summary(f))}</td></tr>")
        add("</table>")
    return "".join(out)


def report_html(data: dict[str, Any], layout: str = "stacked") -> str:
    data = public_data(data)
    s = summarise(data)
    rules = load_rules()
    p: list[str] = []
    add = p.append
    add("<!doctype html><html lang=ru><head><meta charset=utf-8>")
    add('<meta name=viewport content="width=device-width,initial-scale=1">')
    add(f"<title>{esc(site_name(data))} — проверка на соответствие требованиям РФ</title>")
    add(f"<style>{CSS}</style></head><body><div class=wrap>")
    add(f"<h1>{esc(site_name(data))} — проверка на соответствие требованиям РФ</h1>")
    add(f"<div class=meta>{esc(data['target'])} · проверено {esc(data['generated_at'][:10])} · "
        f"страниц: {esc(data.get('pages_analysed', 0))}</div>")
    for issue in provenance_issues(data):
        add(f"<div class=alert>Несовместимые входные данные. {esc(issue)}</div>")
    for issue in collection_issues(data):
        add(f"<div class=alert>Ограниченный снимок. {esc(issue)}</div>")
    for issue in consistency_issues(data):
        add(f"<div class=alert>Противоречивые выводы. {esc(issue)}</div>")
    pending = semantic_pending(data)
    if pending:
        add("<div class='alert draft'><b>Черновик.</b> Смысловая проверка не выполнена по пунктам "
            + esc(", ".join(f["rule_id"] for f in pending))
            + ": их вердикты машинные, до подтверждения документ не передавать.</div>")
    alert = coverage_alert(data)
    if alert:
        add(f"<div class=alert>{md_inline(alert)}</div>")

    add(f"<p class=lead><b>{esc(headline(data, s))}</b> {esc(coverage_line(data, s))}</p>")
    add("<div class=kpis>")
    for cls, label, value in (("fail", "нарушений", len(s["fails"])),
                              ("warn", "рисков", len(s["warns"])),
                              ("pass", "в порядке", len(s["passes"])),
                              ("unknown", "не проверено", len(s["unknowns"]))):
        add(f"<div class='kpi {cls}'><div class=n>{value}</div><div class=l>{label}</div></div>")
    add("</div>")
    limits = limits_line(data)
    if limits:
        add(f"<p class=hint>{esc(limits)}</p>")

    if s["fails"]:
        add("<h2>Нарушения — исправить</h2>")
        add("<table class=violations><colgroup><col class=v-rule><col class=v-what><col class=v-where>"
            "<col class=v-fix><col class=v-fine></colgroup>"
            "<tr><th>Правило</th><th>Что не так</th><th>Где</th><th>Что сделать</th>"
            "<th>Штраф юрлицу, ₽</th></tr>")
        for f in sort_findings(s["fails"]):
            where = "<br>".join(linkify(x) for x in locations(f, data)) or "—"
            add(f"<tr><td><a href='#{anchor(f['rule_id'])}'><span class=rule-id>{esc(f['rule_id'])}</span></a> "
                f"{esc(f['title'])}</td><td>{esc(report_summary(f))}</td><td class=where>{where}</td>"
                f"<td>{esc(remediation(f) or '—')}</td><td class=fine>{esc(fine_amount(f))}</td></tr>")
        add("</table>")
        add("<p class=hint>Суммы по правилам не складываются: находки могут относиться к одному эпизоду.</p>")

    if s["warns"]:
        add("<h2>Риски — решить</h2>")
        for f in sort_findings(s["warns"]):
            pos = position_of(f, rules)
            add("<div class='finding WARN'>")
            add(f"<h3><a href='#{anchor(f['rule_id'])}'><span class=rule-id>{esc(f['rule_id'])}</span></a> "
                f"{esc(f['title'])}</h3><p>{esc(sentence(report_summary(f)))}</p>")
            if pos.get("verdict"):
                add(f"<p><b>Позиция.</b> {esc(sentence(pos['verdict']))}</p>")
            if remediation(f):
                add(f"<p><b>Что сделать.</b> {esc(sentence(remediation(f)))}</p>")
            if pos.get("lifted_by"):
                add(f"<p class=hint>Снимается: {esc(sentence(pos['lifted_by']))}</p>")
            add("</div>")

    if s["externals"]:
        add("<h2>Вопросы владельцу</h2><p class=hint>Снаружи сайта это не видно. Ответ владельца закрывает пункт.</p><ul>")
        for f in s["externals"]:
            add(f"<li><b><span class=rule-id>{esc(f['rule_id'])}</span> {esc(f['title'])}.</b> "
                f"{esc(sentence(report_summary(f)))}</li>")
        add("</ul>")

    if s["unknowns"]:
        add("<h2>Не проверено из-за сбоя сбора</h2><p class=hint>Причина техническая; повторный запуск её устраняет.</p><ul>")
        for f in sort_findings(s["unknowns"]):
            add(f"<li><span class=rule-id>{esc(f['rule_id'])}</span> {esc(f['title'])} — "
                f"{esc(report_summary(f))}</li>")
        add("</ul>")

    detailed = sort_findings(s["fails"] + s["warns"] + s["externals"])
    if detailed:
        add("<h2>Доказательства и нормы</h2>")
        add(f"<p class=hint>Полный реестр наблюдений: {evidence_refs_html('evidence.html / evidence.json')}.</p>")
        for f in detailed:
            add(f"<div class='finding {esc(report_status(f))}' id='{anchor(f['rule_id'])}'>")
            add(f"<h3><span class=rule-id>{esc(f['rule_id'])}</span> {esc(f['title'])} "
                f"<span class='badge {esc(report_status(f))}'>{esc(status_label(f))}</span></h3>")
            if f.get("norm"):
                add(f"<p class=hint>{esc(f['norm'])}" + (f" · {esc(f['liability'])}" if f.get("liability") else "") + "</p>")
            add(f"<p><b>Обнаружено.</b> {esc(sentence(report_summary(f)))}</p>")
            note = machine_note(f)
            if note:
                add(f"<p class=hint>{esc(note)}</p>")
            rows, hidden = evidence_lines(f, data)
            for text, snippet in rows:
                add(f"<div class=ev>{linkify(text)}" + (f"<q>{esc(snippet)}</q>" if snippet else "") + "</div>")
            if hidden:
                add(f"<p class=hint>Ещё {hidden}: {evidence_refs_html('evidence.html / evidence.json')}.</p>")
            if f.get("source_note"):
                add(f"<p class=hint>Источник данных: {esc(f['source_note'])}</p>")
            add("</div>")

    add("<h2>Приложение. Все пункты</h2>")
    for group, title in GROUP_RU.items():
        items = [f for f in data["findings"] if f["group"] == group]
        if items:
            add(f"<h3>{esc(title)}</h3>")
            add(checklist_table_html(sort_findings(items), {f["rule_id"] for f in detailed}, layout))

    add(plan_html(data))
    add("<h2>О проверке</h2><div class=colophon>")
    add(f"<p>{esc(provenance_line(data))}</p><p>{esc(DISCLAIMER)}</p>")
    add(f"<p>Проверка выполнена скиллом <b>{esc(SKILL_NAME)}</b> — открытый "
        f"набор правил и скриптов проверки сайта на соответствие требованиям РФ.</p>")
    add("<ul>"
        f"<li>Автор: {esc(SKILL_AUTHOR)}</li>"
        f"<li>Исходники и обновления правил: <a href='{SKILL_REPO}'>{esc(SKILL_REPO)}</a></li>"
        f"<li>Канал автора: <a href='{SKILL_CHANNEL}'>{esc(SKILL_CHANNEL)}</a></li>"
        f"<li>Вопросы и замечания по проверке: <a href='mailto:{SKILL_EMAIL}'>{esc(SKILL_EMAIL)}</a></li>"
        "</ul>")
    add("<p>Нормы и санкции взяты из указанной версии правил; дата обхода не подтверждает их актуальность.</p>")
    add("</div></div></body></html>")
    return "".join(p)


def plan_html(data: dict[str, Any]) -> str:
    sections = plan_sections(data)
    pub = public_data(data)
    out = ["<div class=partbreak></div><h1>Часть II. План исправлений</h1>",
           f"<div class=meta>Задач: {sum(len(rows) for _, _, rows in sections)} · основание — часть I</div>",
           "<p>P0–P1 — нарушения, P2–P3 — риски. Каждая задача: что сделать, где и как принять.</p>"]
    for code, title, rows in sections:
        out.append(f"<h2>{esc(code)}. {esc(title)}</h2>")
        for i, f in enumerate(rows, 1):
            out += [f"<div class='finding {esc(f['_report_status'])}'>",
                    f"<h3>{esc(code)}-{i:02d}. {esc(f['title'])}</h3>",
                    f"<p class=hint>Правила {esc(action_rules(f))}</p>",
                    f"<p><b>Что обнаружено.</b> {esc(f['summary'])}</p>"]
            if any(m['rule_id'] in NEEDS_LEGAL_INPUT for m in f['members']):
                out.append("<p class=hint>Текст правки утверждает владелец или юрист.</p>")
            where = describe_locations(f, pub)
            if where:
                out.append("<p><b>Где.</b></p><ul>" + "".join(f"<li>{linkify(x)}</li>" for x in where) + "</ul>")
            items = checklist_items(f)
            if items:
                out.append("<p><b>Перечень.</b></p><ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>")
            out += [f"<p><b>Что сделать.</b> {esc(f['fix_hint'] or 'Устранить обнаруженное по доказательствам части I.')}</p>",
                    f"<p><b>Критерий приёмки.</b> {esc(acceptance(f))}</p>", "</div>"]
    return "".join(out)


RUNNING_DISCLAIMER = (
    "Техническая проверка, не юридическое заключение.")


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
    ap.add_argument("--artifacts", default="artifacts", help="исходные артефакты для ссылок реестра")
    ap.add_argument("--format", default="md,html",
                    help="список через запятую: md, html, pdf")
    ap.add_argument("--allow-legacy", action="store_true",
                    help="просмотр старых findings с предупреждением о несовместимости")
    ap.add_argument("--layout", default="stacked",
                    choices=("stacked", "twoline", "wide"),
                    help="раскладка чек-листа в HTML и PDF")
    args = ap.parse_args()

    data = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    issues = provenance_issues(data) + consistency_issues(data)
    if issues and not args.allow_legacy:
        print("\n".join(issues), file=sys.stderr)
        print("Повторите detect текущей версией. Для просмотра старого снимка: --allow-legacy.", file=sys.stderr)
        return 2
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.format.split(",") if f.strip()}
    written: list[Path] = []

    registry = report_evidence.index(data)
    p = out / "evidence.json"
    p.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"); written.append(p)
    p = out / "evidence.html"
    artifact_href = os.path.relpath(Path(args.artifacts).resolve(), out.resolve())
    p.write_text(report_evidence.html_page(registry, data['target'], artifact_href), encoding="utf-8"); written.append(p)

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
                  "(uv run --no-project --with playwright python -m playwright install chromium)",
                  file=sys.stderr)

    s = summarise(data)
    print(f"Нарушений: {len(s['fails'])} · рисков: {len(s['warns'])} · вопросов владельцу: "
          f"{len(s['externals'])} · не проверено: {len(s['unknowns'])}"
          + (f" · ЧЕРНОВИК: без смысловой проверки {len(semantic_pending(data))}" if semantic_pending(data) else ""),
          file=sys.stderr)
    for p in written:
        print(f"  {p}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
