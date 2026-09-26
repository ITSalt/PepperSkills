#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Регрессионные проверки скрипов скилла — без сети и без обхода сайтов.

Каждый тест здесь появился из ошибки на живом сайте. Название реестровой
записи, совпавшее с обычным словом; слово «вход» внутри «входные файлы»,
объявившее авторизацию там, где её нет; правило, исчезнувшее из отчёта, потому
что детектор промолчал. Такие ошибки дороже обычных: они не ломают прогон, а
тихо меняют вывод, и заметить их можно только повторной проверкой.

Запуск: uv run --no-project scripts/selftest.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import detect  # noqa: E402
import registries as reg  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, name: str, detail: str = "") -> None:
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))
        FAILURES.append(name)


def matcher_for(entries: list[dict]) -> reg.RegistryMatcher:
    return reg.RegistryMatcher(reg.RegistryData(
        registry="test", title="тестовый реестр", source_trust="official",
        entries=entries))


def test_registry_matching() -> None:
    print("совпадения по реестру")
    m = matcher_for([
        {"id": "1", "kind": "org", "name": 'Проект «ВОТ ТАК»', "aliases": ["ВОТ ТАК"]},
        {"id": "2", "kind": "org", "name": 'Центр «Действие»', "aliases": ["Действие"]},
        {"id": "3", "kind": "org", "name": 'Общественная организация «СИЧ-С14»',
         "aliases": ["СИЧ-С14"]},
        {"id": "4", "kind": "org", "name": 'Движение «Славянский союз»',
         "aliases": ["Славянский союз"]},
        {"id": "5", "kind": "org", "name": 'Фонд «Наследие»', "aliases": ["Наследие"],
         "excluded_at": "2024-01-01"},
    ])

    def ids(text: str) -> set[str]:
        return {hit.entry_id for hit in m.find(text)}

    # Фраза из обиходных слов не должна ловиться в обычном предложении.
    check("1" not in ids("первая генерация ретуши дала вот такой результат"),
          "«вот так» не срабатывает на «вот такой результат»")
    check("1" in ids('материал телеканала «Вот Так» об этом'),
          "«Вот Так» в кавычках находится")
    check("1" in ids('по данным издания Вот Так стало известно'),
          "«Вот Так» после слова «издание» находится")

    # Однословный псевдоним — только в кавычках или при слове-роде.
    check("2" not in ids("пользователь совершает действия на сайте"),
          "«Действие» не срабатывает на «действия»")
    check("2" in ids('центр «Действие» провёл встречу'),
          "«Действие» в кавычках находится")

    # Короткое, но не обиходное название обязано находиться и без подпорок.
    check("3" in ids("мы сотрудничали с СИЧ-С14 в прошлом году"),
          "«СИЧ-С14» находится без кавычек")
    check("4" in ids("митинг организовал славянский союз"),
          "многословное название находится в тексте")

    # Исключённая из реестра запись обязанности не порождает.
    check("5" not in ids('фонд «Наследие» выступил партнёром'),
          "исключённая запись не даёт совпадения")

    check(reg.weak_phrase("Вот так") and not reg.weak_phrase("Ак-Дян"),
          "weak_phrase отличает обиходную фразу от короткого названия")


def test_login_heuristics() -> None:
    print("признаки авторизации")
    check(not detect.word_in("сохраняйте входные файлы", "вход"),
          "«вход» не находится внутри «входные»")
    check(detect.word_in("кнопка вход в правом углу", "вход"),
          "«вход» находится отдельным словом")
    labels = detect.clickable_labels(
        '<nav><a href="/x">Тарифы</a><a href="/login">Войти</a></nav>'
        '<p>вход в тему занимает время</p>')
    check("войти" in labels and "тарифы" in labels,
          "подписи ссылок извлекаются из разметки")
    check(not any("вход в тему" in l for l in labels),
          "текст абзаца не попадает в подписи ссылок")


def artifacts_fixture(tmp: Path, *, text: str, dom: str, url: str) -> Path:
    art = tmp / "art"
    (art / "pages" / "index").mkdir(parents=True)
    (art / "pages" / "index" / "text.txt").write_text(text, encoding="utf-8")
    (art / "pages" / "index" / "dom.html").write_text(dom, encoding="utf-8")
    (art / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "target": url, "degraded": False, "blocked": False,
        "banner": {"found": False}, "infra": {"host": "example.ru"},
        "pages": [{"url": url, "final_url": url, "status": 200, "slug": "index",
                   "forms": [], "links": [], "has_policy_link": False}],
    }, ensure_ascii=False), encoding="utf-8")
    return art


def test_report_completeness() -> None:
    print("полнота отчёта")
    # Реестры в тесте не грузим: проверяется полнота отчёта, а не доступность
    # госсайтов. Пустой реестр — штатная ветка, она даёт UNKNOWN.
    detect.Context.registry = lambda self, key: reg.RegistryData(  # type: ignore[method-assign]
        registry=key, error="реестр в самопроверке не загружается")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        art = artifacts_fixture(
            tmp,
            text="сохраняйте входные файлы и настройки. вход в тему занимает время",
            dom="<html><body><a href='/cases'>Кейсы</a></body></html>",
            url="https://example.ru/")
        ctx = detect.Context(art)
        result = detect.run(ctx)
        findings = {f["rule_id"]: f for f in result["findings"]}

        missing = [rid for rid in ctx.rules if rid not in findings]
        check(not missing, "статус есть у каждого правила", f"нет: {missing}")

        statuses = {"PASS", "FAIL", "WARN", "NA", "UNKNOWN"}
        bad = [f["rule_id"] for f in result["findings"] if f["status"] not in statuses]
        check(not bad, "все статусы из допустимого набора", f"чужие: {bad}")

        check(findings["AUTH-004"]["status"] == "NA",
              "без признаков входа AUTH-004 — не применимо",
              findings["AUTH-004"]["status"])


def test_login_page_changes_auth_status() -> None:
    print("авторизация без страницы входа")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        art = artifacts_fixture(
            tmp, text="тарифы вопросы войти начать",
            dom="<html><body><a href='/app'>Войти</a></body></html>",
            url="https://example.ru/")
        findings = {f["rule_id"]: f for f in detect.run(detect.Context(art))["findings"]}
        check(findings["AUTH-004"]["status"] == "UNKNOWN",
              "ссылка «Войти» без страницы входа даёт UNKNOWN, а не нарушение",
              findings["AUTH-004"]["status"])


def test_same_site() -> None:
    print("границы сайта")
    import collect
    check(collect.same_host("https://app.family-cinema.ru/auth", "family-cinema.ru"),
          "поддомен считается тем же сайтом")
    check(not collect.same_host("https://evil-family-cinema.ru/", "family-cinema.ru"),
          "похожий чужой домен не считается тем же сайтом")
    check(collect.registrable_domain("a.b.com.ru") == "b.com.ru",
          "составной суффикс разбирается правильно")
    check(detect.first_party("https://cdn.example.ru/x", "https://example.ru"),
          "поддомен — не сторонний приёмник данных")


def test_policy_link_scope() -> None:
    print("доступ к политике")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        art = artifacts_fixture(
            tmp, text="политика обработки персональных данных",
            dom="<html><body><p>политика</p></body></html>",
            url="https://example.ru/privacy")
        manifest = json.loads((art / "manifest.json").read_text(encoding="utf-8"))
        manifest["pages"][0].update({"url": "https://example.ru/privacy",
                                     "final_url": "https://example.ru/privacy",
                                     "has_policy_link": False})
        (art / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                           encoding="utf-8")
        findings = {f["rule_id"]: f for f in detect.run(detect.Context(art))["findings"]}
        check(findings["PDN-002"]["status"] != "FAIL",
              "страница политики не нарушает требование ссылкой на саму себя",
              findings["PDN-002"]["status"])


def test_disclaimer_form_scope() -> None:
    print("форма плашки иноагента")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        art = artifacts_fixture(tmp, text="обычный текст без упоминаний",
                                dom="<html><body>текст</body></html>",
                                url="https://example.ru/")
        findings = {f["rule_id"]: f for f in detect.run(detect.Context(art))["findings"]}
        check(findings["DISC-002"]["status"] == "UNKNOWN",
              "без загруженного реестра форма плашки остаётся без вывода",
              findings["DISC-002"]["status"])
        check(bool(findings["INF-004"].get("manual_check")),
              "у INF-004 есть инструкция ручной проверки")


def test_report_colophon_and_links() -> None:
    print("подвал и ссылки отчёта")
    import render
    data = {"target": "https://example.ru/", "generated_at": "2026-09-18T00:00:00+00:00",
            "pages_analysed": 3, "findings": [
                {"rule_id": "INF-004", "group": "infra", "title": "Правило",
                 "status": "UNKNOWN", "severity": "high", "summary": "нет вывода",
                 "evidence": [], "manual_check": "Открыть https://eais.rkn.gov.ru/ и ввести домен"}]}
    md = render.combined_md(data)
    html = render.report_html(data)
    for needle, name in ((render.SKILL_NAME, "название скилла"),
                         (render.SKILL_AUTHOR, "автор"),
                         (render.SKILL_REPO, "репозиторий"),
                         (render.SKILL_CHANNEL, "канал"),
                         (render.SKILL_EMAIL, "почта")):
        check(needle in md and needle in html, f"{name} есть в записке")
    check('<a href="https://eais.rkn.gov.ru/">' in html,
          "ссылка из инструкции кликабельна в HTML")
    check("zapret-info" not in md and "zapret-info" not in html,
          "служебное обоснование не попадает в отчёт")


def test_money_typography() -> None:
    print("типографика сумм")
    import render
    check("\u00a0" in render.nbsp_numbers("150 000 – 300 000 ₽"),
          "разряды числа склеены неразрывным пробелом")
    check("₽" not in render.fine_amount({"fine_legal": "5 000 – 10 000 ₽"}),
          "в строке таблицы знака рубля нет — он в заголовке колонки")
    for layout in ("wide", "stacked", "twoline"):
        html = render.checklist_table_html(
            [{"rule_id": "ORG-001", "title": "Правило", "status": "PASS",
              "severity": "low", "summary": "всё хорошо", "norm": "ст. 9 ЗоЗПП",
              "fine_legal": "5 000 – 10 000 ₽", "evidence": []}], set(), layout)
        check("штраф юрлицу, ₽" in html.lower(),
              f"раскладка {layout}: валюта в заголовке")
        check("5\u00a0000" in html, f"раскладка {layout}: сумма не рвётся")


def test_checksums() -> None:
    print("контрольные суммы реквизитов")
    check(detect.valid_inn("7736279160"), "валидный ИНН юрлица принят")
    check(not detect.valid_inn("7736279161"), "испорченный ИНН отклонён")
    check(not detect.valid_inn("84951234567"), "телефон не проходит как ИНН")


def test_data_twins() -> None:
    print("JSON-двойники данных")
    for name in ("rules", "signatures"):
        yaml_path = HERE / f"{name}.yaml"
        json_path = HERE / f"{name}.json"
        if not (yaml_path.exists() and json_path.exists()):
            continue
        from_yaml = detect.load_data(yaml_path)
        from_json = json.loads(json_path.read_text(encoding="utf-8"))
        check(from_yaml == from_json, f"{name}.json совпадает с {name}.yaml",
              "перегенерировать: uv run --no-project scripts/gen_checklist.py --write")


def test_processing_basis() -> None:
    print("основание обработки аналитики")
    class FakeContext:
        pages = [{"status": 200, "final_url": "https://example.ru/privacy", "slug": "privacy"}]
        texts = {"privacy": "Аналитика осуществляется на основании п. 7 ч. 1 ст. 6 ФЗ-152. "
                           "Пользователь может направить возражение против обработки."}
        sig = {"trackers": {"foreign": [], "russian": [{"vendor": "Метрика",
                "kind": "analytics", "host": "mc.yandex.ru"}]}}
        def page_by_slug(self, slug):
            return self.pages[0]
        def all_requests(self):
            return [{"url": "https://mc.yandex.ru/watch/1"}]

    fake = FakeContext()
    basis = detect.basis_kwargs(fake)
    check(basis["processing_basis"] == "legitimate_interest_declared",
          "заявленный законный интерес распознан")
    check(basis["processing_activities"][0]["verification_status"] == "UNKNOWN"
          and basis["processing_activities"][0]["verified_basis"] is None,
          "упоминание возражения не подтверждает основание или работающий отказ")
    check(detect.optional_tracking_observed(fake),
          "аналитический запрос отличён от отсутствия трекеров")


def test_cookie_and_tracker_qualification() -> None:
    print("квалификация cookie и трекеров")
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        art = artifacts_fixture(tmp, text="обычная страница", dom="<html></html>",
                                url="https://example.ru/")
        clean = {f["rule_id"]: f for f in detect.run(detect.Context(art))["findings"]}
        check(clean["CK-001"]["status"] == "NA",
              "техническая страница без аналитики не требует баннер автоматически",
              clean["CK-001"]["status"])
        (art / "network").mkdir(parents=True)
        (art / "network" / "walk.jsonl").write_text(
            json.dumps({"url": "https://www.google-analytics.com/g/collect?v=2"}) + "\n",
            encoding="utf-8")
        tracked = {f["rule_id"]: f for f in detect.run(detect.Context(art))["findings"]}
        check(tracked["CK-001"]["status"] == "WARN",
              "отсутствие баннера при аналитике требует квалификации, а не FAIL",
              tracked["CK-001"]["status"])
        check(tracked["CK-003"]["status"] == "WARN",
              "аналитика без баннера требует проверки основания",
              tracked["CK-003"]["status"])
        check(tracked["CK-005"]["status"] == "WARN" and
              tracked["PDN-009"]["status"] == "WARN",
              "иностранный домен фиксируется как факт для правовой проверки",
              f"CK-005={tracked['CK-005']['status']}, PDN-009={tracked['PDN-009']['status']}")


def main() -> int:
    for test in (test_registry_matching, test_login_heuristics,
                 test_report_completeness, test_login_page_changes_auth_status,
                 test_same_site, test_policy_link_scope, test_disclaimer_form_scope,
                 test_report_colophon_and_links, test_money_typography,
                 test_checksums, test_data_twins, test_processing_basis,
                 test_cookie_and_tracker_qualification):
        test()
    print()
    if FAILURES:
        print(f"провалено проверок: {len(FAILURES)}")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("все проверки пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
