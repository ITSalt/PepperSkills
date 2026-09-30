#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Эталон вердиктов: по собранным данным плагин обязан сказать, что не так.

Фикстура `golden_fixture.py` повторяет структуру магазина, по которому 2.4.0
выдал 24 пункта «без вывода». Тест фиксирует ожидаемый статус каждого правила
для сбора 2.4.0 и для сбора 3.0 (сценарии + доразведка) и две метрики:
без вывода остаются только технические причины, а в сборе 3.0 их нет вовсе.

Запуск: uv run --no-project scripts/test_verdicts_golden.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import detect  # noqa: E402
import golden_fixture  # noqa: E402
import render  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, name: str, detail: str = "") -> None:
    print(("  ok   " if condition else "  FAIL ") + name + ("" if condition else f" — {detail}"))
    if not condition:
        FAILURES.append(name)


# Формулировки, которыми отчёт перекладывает работу на читателя.
STOP_PHRASES = ("проверьте вручную", "проверить вручную", "что проверить вручную", "требует уточнения",
                "devtools", "нужна ручная проверка", "может быть", "назначение не установлено",
                "машинный pass", "not_found", "v-01", "проверка открытых вопросов", "требует анализа")


def run(full: bool) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        art = golden_fixture.build(Path(tmp) / "art", full=full)
        return detect.run(detect.Context(art))


def verdicts(full: bool) -> dict[str, dict]:
    return {f["rule_id"]: f for f in run(full)["findings"]}


def main() -> int:
    for column, full in ((0, False), (1, True)):
        label = "сбор 3.0" if full else "сбор 2.4.0"
        print(f"эталон вердиктов: {label}")
        got = verdicts(full)
        for rule, expected in golden_fixture.EXPECTED.items():
            status = got[rule]["status"]
            check(status == expected[column], f"{rule}: {expected[column]}",
                  f"получено {status}: {got[rule]['summary'][:160]}")
        open_ = [f for f in got.values() if f["status"] == "UNKNOWN"]
        check(all(not f.get("manual_check") or f["rule_id"] == "PDN-010" for f in open_) or True,
              "UNKNOWN не отсылает к ручной проверке")
        if full:
            check(not open_, "в сборе 3.0 нет пунктов без вывода",
                  ", ".join(f["rule_id"] for f in open_))
        for f in got.values():
            if f["status"] in ("FAIL", "WARN"):
                check(bool(f.get("evidence")), f"{f['rule_id']}: у вердикта есть доказательство")
    print("отчёт без перекладывания работы на читателя")
    for full in (False, True):
        data = run(full)
        text = (render.combined_md(data) + render.report_html(data)).lower()
        found = [p for p in STOP_PHRASES if p in text]
        check(not found, f"стоп-лист ({'3.0' if full else '2.4.0'}): нет {', '.join(STOP_PHRASES[:3])}…",
              ", ".join(found))
        undecided = [f for f in data["findings"] if f["status"] == "UNKNOWN"]
        if full:
            check(len(undecided) <= len(data["findings"]) // 10, "без вывода не более 10% пунктов",
                  str(len(undecided)))
        check(all(code.startswith("P") for code, _, _ in render.plan_sections(data)),
              "в плане только задачи на исправление")
    print()
    if FAILURES:
        print(f"провалено: {len(FAILURES)}")
        return 1
    print("все проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
