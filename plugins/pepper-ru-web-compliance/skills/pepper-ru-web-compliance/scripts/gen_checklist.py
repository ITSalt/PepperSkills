#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6,<7"]
# ///
"""Генерирует references/checklist.md из scripts/rules.yaml.

rules.yaml — единственный источник правды. Чек-лист, детекторы и шаблоны
отчётов производны от него, поэтому руками checklist.md править нельзя:
изменения вносятся в rules.yaml и файл перегенерируется. Так человекочитаемая
версия и версия, по которой работают скрипты, не могут разойтись.

Использование:
    python3 scripts/gen_checklist.py           # записать references/checklist.md
    python3 scripts/gen_checklist.py --check   # проверить, что файл актуален (для CI)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "scripts" / "rules.yaml"
OUT = ROOT / "references" / "checklist.md"

GROUP_TITLES = {
    "auth": "A. Авторизация пользователей",
    "disclaim": "B. Дисклеймеры и символика",
    "pdn": "C. Персональные данные (152-ФЗ)",
    "cookie": "D. Cookie и трекеры",
    "infra": "E. Инфраструктура",
    "org": "F. Реквизиты оператора",
}

CHECK_LABELS = {
    "script": "скрипт",
    "llm": "LLM",
    "hybrid": "скрипт + LLM",
    "info_only": "справочно",
}

SEVERITY_LABELS = {
    "critical": "критический",
    "high": "высокий",
    "medium": "средний",
    "low": "низкий",
    "info": "справочно",
}


def fine_summary(rule: dict) -> str:
    """Короткая сводка санкции для обзорной таблицы — по юрлицу как верхней границе."""
    liability = rule.get("liability") or {}
    fines = liability.get("fines") or {}
    value = fines.get("legal_entity")
    if not value:
        return liability.get("risk", "—")
    return str(value)


def render(data: dict) -> str:
    rules = data["rules"]
    meta = data["meta"]
    lines: list[str] = []
    add = lines.append

    add("<!-- СГЕНЕРИРОВАНО scripts/gen_checklist.py — не редактировать вручную. -->")
    add("<!-- Источник правды: scripts/rules.yaml -->")
    add("")
    add("# Чек-лист проверки сайта на соответствие требованиям РФ")
    add("")
    add(f"Состояние норм на {meta['as_of']}. Всего правил: {len(rules)}.")
    add("")
    add("> " + " ".join(meta["disclaimer"].split()))
    add("")

    # Обзорная таблица по группам.
    for group, title in GROUP_TITLES.items():
        group_rules = [r for r in rules if r["group"] == group]
        if not group_rules:
            continue
        add(f"## {title}")
        add("")
        add("| ID | Требование | Норма | Проверка | Риск | Штраф юрлицу |")
        add("|----|-----------|-------|----------|------|--------------|")
        for r in group_rules:
            norm = (r.get("norm") or {}).get("act", "—")
            add(
                "| `{id}` | {title} | {norm} | {check} | {sev} | {fine} |".format(
                    id=r["id"],
                    title=r["title"],
                    norm=norm,
                    check=CHECK_LABELS.get(r.get("check"), r.get("check", "—")),
                    sev=SEVERITY_LABELS.get(r.get("severity"), "—"),
                    fine=fine_summary(r),
                )
            )
        add("")

    # Подробные карточки.
    add("---")
    add("")
    add("# Карточки правил")
    add("")
    for group, title in GROUP_TITLES.items():
        group_rules = [r for r in rules if r["group"] == group]
        if not group_rules:
            continue
        add(f"## {title}")
        add("")
        for r in group_rules:
            add(f"### `{r['id']}` — {r['title']}")
            add("")
            add("**Требование.** " + " ".join(r["requirement"].split()))
            add("")

            norm = r.get("norm") or {}
            if norm:
                parts = [f"**Норма.** {norm.get('act', '—')}"]
                if norm.get("introduced_by"):
                    parts.append(f"Введена: {norm['introduced_by']}.")
                if norm.get("in_force"):
                    parts.append(f"В силе с: {norm['in_force']}.")
                if norm.get("form"):
                    parts.append(f"Форма: {norm['form']}.")
                if norm.get("scope_change"):
                    parts.append(" ".join(norm["scope_change"].split()))
                add(" ".join(parts))
                add("")

            liability = r.get("liability") or {}
            if liability:
                add(f"**Ответственность.** {liability.get('article', '—')}")
                fines = liability.get("fines") or {}
                if fines:
                    add("")
                    for who, amount in fines.items():
                        label = {
                            "citizen": "граждане",
                            "official": "должностные лица",
                            "entrepreneur": "ИП",
                            "legal_entity": "юридические лица",
                        }.get(who, who)
                        add(f"- {label}: {amount}")
                for key, prefix in (("extra", "Дополнительно"), ("note", "Примечание"),
                                    ("risk", "Риск"), ("authority", "Орган")):
                    if liability.get(key):
                        add("")
                        add(f"{prefix}: {liability[key]}")
                repeat = liability.get("repeat_offence")
                if isinstance(repeat, dict):
                    add("")
                    add(f"Повторное нарушение — {repeat.get('article', '')}: "
                        + ", ".join(f"{k} {v}" for k, v in repeat.items() if k != "article"))
                elif repeat == "none":
                    add("")
                    add("Повышенная ответственность за повторность не предусмотрена.")
                if liability.get("also"):
                    add("")
                    add("Смежные составы:")
                    for item in liability["also"]:
                        add(f"- {item}")
                add("")

            add(f"**Способ проверки.** {CHECK_LABELS.get(r.get('check'), '—')}"
                + (f", детектор `{r['detector']}`" if r.get("detector") else "")
                + (f", реестр `{r['registry']}`" if r.get("registry") else ""))
            add("")

            if r.get("evidence"):
                add("**Доказательство.**")
                add("")
                for item in r["evidence"]:
                    add(f"- {item}")
                add("")

            if r.get("status_logic"):
                add("**Статусы.**")
                add("")
                for status, condition in r["status_logic"].items():
                    add(f"- `{status}` — {condition}")
                add("")

            if r.get("fix_hint"):
                add("**Как чинить.** " + " ".join(r["fix_hint"].split()))
                add("")
            if r.get("cross_ref"):
                add("**Связанные правила.** " + ", ".join(f"`{x}`" for x in r["cross_ref"]))
                add("")
            if r.get("note"):
                add("**Примечание.** " + " ".join(r["note"].split()))
                add("")
            if r.get("sources"):
                add("**Источники.** " + " · ".join(r["sources"]))
                add("")
            add(f"*Сверено: {r.get('verified_at', '—')}*")
            add("")

    return "\n".join(lines) + "\n"


def emit_json_twins() -> None:
    """Собирает JSON-двойники rules.yaml и signatures.yaml.

    Детекторы читают их стандартной библиотекой, если на машине нет PyYAML.
    YAML остаётся источником правды и форматом для человека — правила это
    юридический текст, который правят руками, — а JSON пересобирается отсюда,
    поэтому разойтись они не могут.
    """
    import json
    for name in ("rules.yaml", "signatures.yaml"):
        src = ROOT / "scripts" / name
        if not src.exists():
            continue
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        dst = src.with_suffix(".json")
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"записано: scripts/{dst.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="не писать файл, а проверить его актуальность")
    args = parser.parse_args()

    data = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    rendered = render(data)

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != rendered:
            print("checklist.md устарел: перегенерируйте через gen_checklist.py",
                  file=sys.stderr)
            return 1
        print("checklist.md актуален")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    emit_json_twins()
    print(f"записано: {OUT.relative_to(ROOT)} ({len(rendered.splitlines())} строк, "
          f"{len(data['rules'])} правил)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
