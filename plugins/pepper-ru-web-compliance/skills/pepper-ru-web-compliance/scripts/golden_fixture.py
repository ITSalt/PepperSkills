"""Эталонный интернет-магазин для регрессии вердиктов.

Построен по мотивам реального отчёта 2.4.0 о крупном магазине посуды: из 41
пункта 24 остались «без вывода», хотя собранных данных хватало на ответ.
Домен, реквизиты и тексты заменены вымышленными; сохранена структура,
из-за которой прежние детекторы отступали: вход в модальном окне, форма заказа
после корзины, баннера нет, аналитика с первого визита, общий абзац о cookie,
Instagram только в JSON-LD, хостинг за DDoS-прокси.

`build(root, full=False)` — артефакты сборщика 2.4.0 (без сценариев и
доразведки). `full=True` — то же с активными сценариями и доразведкой 3.0.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

TARGET = "https://shop.example.ru"
INN = "7707083893"
OGRN = "1027700132195"

POLICY = """Политика в отношении обработки персональных данных
1. Общие положения
1.1. Настоящая политика определяет порядок обработки персональных данных ООО «Посуда Дом» (ИНН 7707083893, ОГРН 1027700132195), адрес: г. Москва, ул. Примерная, д. 1.
2. Цели обработки
2.1. Оператор обрабатывает персональные данные в целях исполнения договора купли-продажи, доставки заказов и информирования о статусе заказа.
3. Правовые основания обработки
3.1. Правовым основанием обработки является договор с субъектом и согласие субъекта.
4. Перечень персональных данных
4.1. Оператор обрабатывает следующие персональные данные: фамилия, имя, номер телефона, адрес электронной почты, адрес доставки.
4.2. Категории субъектов: покупатели и пользователи сайта.
5. Порядок обработки
5.1. Обработка включает сбор, запись, систематизацию, накопление, хранение, уточнение, использование, передачу, удаление.
5.2. Оператор осуществляет смешанную обработку персональных данных.
5.3. Персональные данные хранятся в течение 3 лет после исполнения договора.
5.4. Оператор вправе поручить обработку третьим лицам — службам доставки.
5.5. Оператор принимает правовые, организационные и технические меры защиты персональных данных.
6. Права субъекта
6.1. Субъект имеет право получать сведения об обработке и требовать уточнения данных.
6.2. Субъект вправе отозвать согласие, направив заявление оператору.
7. Ответственный
7.3. В Обществе назначено лицо, ответственное за организацию обработки персональных данных.
8. Файлы cookie
8.1. Сайт использует файлы cookie. Технические cookie нужны для работы сайта, аналитические — для статистики посещений, в том числе PHPSESSID.
8.2. Для сбора статистики используется сервис Яндекс.Метрика.
9. Заключительные положения
9.1. Оператор вправе изменять политику. Новая редакция вступает в силу с момента публикации на сайте и действует бессрочно до замены новой редакцией, если иное не предусмотрено новой редакцией политики. Все изменения публикуются на этой странице, и пользователь самостоятельно отслеживает их; предыдущие редакции хранятся у оператора.
9.5. Со всеми предложениями и вопросами по настоящей Политике следует обращаться в службу поддержки по адресу support@example.ru.
"""

CONSENT = """Согласие на получение рекламной рассылки
Я даю согласие ООО «Посуда Дом», адрес: г. Москва, ул. Примерная, д. 1, на обработку адреса электронной почты в целях получения рекламной рассылки.
Согласие действует до его отзыва. Отозвать согласие можно по ссылке в любом письме.
"""

AGREEMENT = "Пользовательское соглашение. Регулирует использование сайта shop.example.ru."

CONTACTS = f"Контакты. ООО «Посуда Дом». ИНН {INN}, ОГРН {OGRN}. Телефон +7 495 000-00-00."

JSONLD = ('<script type="application/ld+json">{"@type":"Organization","name":"Посуда Дом",'
          '"sameAs":["https://www.instagram.com/posuda_dom","https://vk.com/posuda_dom"]}</script>')

HEADER = ('<header><a href="/lichnyj-kabinet/" class="areal-link">Личный кабинет</a>'
          '<a href="/korzina/">Корзина</a><a href="/catalog/">Каталог</a></header>')
FOOTER = ('<footer><a href="https://t.me/posuda_dom">Telegram</a><a href="https://vk.com/posuda_dom">VK</a>'
          '<a href="/documents/privacy-policy">Политика конфиденциальности</a>'
          '<div class="layout-footer__subscribe-app-form"><input type="email" name="email">'
          '<label><input type="checkbox">Подписаться на рассылку <a href="/documents/personal-agree">согласие</a></label>'
          '<label><input type="checkbox">Принимаю <a href="/documents/privacy-policy">политику</a></label>'
          '<button>Подписаться</button></div></footer>')

SUBSCRIBE_FORM = {
    "selector": "div.layout-footer__subscribe-app-form", "action": "",
    "fields": [
        {"type": "email", "name": "email", "placeholder": "E-mail"},
        {"type": "checkbox", "checked": False, "label_text": "Подписаться на рассылку",
         "label_links": ["/documents/personal-agree"]},
        {"type": "checkbox", "checked": False,
         "label_text": "Принимаю политику конфиденциальности и пользовательское соглашение",
         "label_links": ["/documents/privacy-policy", "/documents/user-agreement"]},
    ]}

COOKIES = ["__ddg1_", "__ddg8_", "__ddg9_", "__ddg10_", "SITE_LANGUAGE_ID", "current_city", "userGUID",
           "i18n_locale", "PHPSESSID", "_ym_uid", "_ym_d", "_ym_isad", "_ym_visorc", "tmr_lvid",
           "tmr_lvidTS", "tmr_detect", "mindboxDeviceUUID", "directCrm-session", "adrcid", "adrdel",
           "BITRIX_SM_GUEST_ID", "BITRIX_SM_LAST_VISIT", "BITRIX_CONVERSION_CONTEXT_s1", "BX_USER_ID",
           "_ga_like_local", "cart_id", "compare", "favorites", "last_seen", "utm_source", "utm_medium",
           "utm_campaign", "city_confirmed", "promo_shown"]

TRACKERS = ["https://mc.yandex.ru/metrika/tag.js", "https://top-fwz1.mail.ru/js/code.js",
            "https://api.s.mindbox.ru/scripts/v1/tracker.js", "https://content.adriver.ru/AdRiverFPS.js",
            "https://store-b2b.ru/tag.js",
            "https://rap.skcrtxr.com/pub/pg/00000000-0000-0000-0000-000000000000/run-rap.js"]


def request(url, phase, page=TARGET + "/", method="GET"):
    return {"url": url, "method": method, "phase": phase, "page": page, "frame": page,
            "resource_type": "script", "initiator": {"type": "parser"}, "content_type": "",
            "observation_version": 2}


def page(slug, path, text, dom, forms=(), final=None, **extra):
    url = TARGET + path
    return {"url": url, "final_url": final or url, "status": 200, "slug": slug, "title": slug,
            "forms": list(forms), "links": [TARGET + "/lichnyj-kabinet/", TARGET + "/korzina/",
                                            TARGET + "/documents/privacy-policy"],
            "has_policy_link": True, "policy_link_hrefs": ["/documents/privacy-policy"],
            "text_chars": len(text), "_text": text, "_dom": dom, **extra}


def write(root: Path, rel: str, value) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build(root: Path, full: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    shell = lambda body: f"<html><head>{JSONLD}</head><body>{HEADER}{body}{FOOTER}</body></html>"
    pages = [
        page("index", "/", "Посуда Дом — посуда для кухни. Каталог. Личный кабинет. Корзина.",
             shell("<main><a href='/catalog/pan-1/'>Сковорода</a></main>"), [SUBSCRIBE_FORM]),
        page("blog", "/blog/", "Блог о кухне: как выбрать сковороду.", shell("<main>Блог</main>"), [SUBSCRIBE_FORM]),
        page("shops", "/shops/", "Магазины в Москве.", shell("<main>Магазины</main>"), [SUBSCRIBE_FORM]),
        page("kontakty", "/kontakty/", CONTACTS, shell(f"<main>{CONTACTS}</main>"), [SUBSCRIBE_FORM]),
        page("korzina", "/korzina/", "Корзина пуста.", shell("<main>Корзина пуста</main>"), [SUBSCRIBE_FORM]),
        page("lichnyj-kabinet", "/lichnyj-kabinet/", "Посуда Дом — посуда для кухни.",
             shell("<main></main>"), [SUBSCRIBE_FORM], final=TARGET + "/?redirectUrl=/lichnyj-kabinet/"),
        page("documents_privacy-policy", "/documents/privacy-policy", POLICY, shell(f"<main>{POLICY}</main>")),
        page("documents_personal-agree", "/documents/personal-agree", CONSENT, shell(f"<main>{CONSENT}</main>")),
        page("documents_user-agreement", "/documents/user-agreement", AGREEMENT, shell(f"<main>{AGREEMENT}</main>")),
    ]
    network_rows = {
        "before_consent": [request(u, "before_consent") for u in TRACKERS]
        + [request(TARGET + "/img/sprites/logo.svg", "before_consent")],
        "walk": [request(TARGET + "/img/sprites/logo.svg", "walk", p["url"]) for p in pages]
        + [request(u, "walk", TARGET + "/blog/") for u in TRACKERS],
        "before_reject": [request(u, "before_reject") for u in TRACKERS[:2]],
    }
    manifest = {
        "schema_version": 1, "target": TARGET,
        "collector": {"name": "pepper-ru-web-compliance", "version": "3.0.0" if full else "2.4.0",
                      "observation_version": 2},
        "started_at": "2026-09-29T20:49:12+00:00", "finished_at": "2026-09-29T20:53:18+00:00",
        "network": {"mode": "managed", "complete": True, "started_at": "2026-09-29T20:49:12+00:00",
                    "finished_at": "2026-09-29T20:53:18+00:00",
                    "egress": {"ip": "77.247.243.9", "country": "RU"}},
        "degraded": False, "blocked": False, "visual_complete": True, "partial_pages": False,
        "banner": {"found": False, "candidates": []},
        "refusal": {"click_status": "not_found", "revisit_completed": False},
        "infra": {"host": "shop.example.ru",
                  "http": {"redirects_to_https": True, "final_url": TARGET + "/"},
                  "tls": {"protocol": "TLSv1.3"},
                  "geo": [{"ip": "95.129.233.81", "country": "RU", "org": "DDOS-GUARD LTD",
                           "asn": "AS57724"}]},
        "documents": [], "notes": [],
    }
    if full:
        auth_form = {"selector": "div.modal-auth form", "action": "",
                     "fields": [{"type": "tel", "name": "phone", "placeholder": "Телефон"}]}
        checkout_form = {"selector": "form#order", "action": "/order/",
                         "fields": [{"type": "text", "name": "name", "placeholder": "Имя"},
                                    {"type": "tel", "name": "phone", "placeholder": "Телефон"},
                                    {"type": "email", "name": "email", "placeholder": "E-mail"},
                                    {"type": "text", "name": "address", "placeholder": "Адрес доставки"},
                                    {"type": "checkbox", "checked": False,
                                     "label_text": "Согласен с политикой обработки персональных данных",
                                     "label_links": ["/documents/privacy-policy"]}]}
        pages += [
            page("scenario_auth_1", "/?redirectUrl=/lichnyj-kabinet/", "Вход по номеру телефона. Получить код.",
                 shell("<div class='modal-auth' role='dialog'><form><input type='tel' name='phone'>"
                       "<button>Получить код</button></form></div>"), [auth_form], scenario="auth", modal=True),
            page("scenario_checkout_1", "/order/", "Оформление заказа. Имя, телефон, e-mail, адрес доставки.",
                 shell("<form id='order'></form>"), [checkout_form], scenario="checkout", modal=False),
        ]
        manifest["scenarios"] = [
            {"name": "auth", "status": "reached", "trigger": {"text": "Личный кабинет", "selector": "a.areal-link",
                                                              "href": "/lichnyj-kabinet/"},
             "url": TARGET + "/?redirectUrl=/lichnyj-kabinet/", "slugs": ["scenario_auth_1"], "attempts": 1,
             "error": None, "notes": []},
            {"name": "checkout", "status": "reached", "trigger": {"text": "В корзину", "selector": "button.buy",
                                                                  "href": None},
             "url": TARGET + "/order/", "slugs": ["scenario_checkout_1"], "attempts": 1, "error": None,
             "notes": []},
            {"name": "forms", "status": "not_present", "trigger": None, "url": TARGET + "/", "slugs": [],
             "attempts": 1, "error": None, "notes": []},
        ]
        network_rows["scenario"] = [request("https://mc.yandex.ru/watch/1", "scenario_auth")]
        hosts = {h: {"ips": ["1.1.1.1"], "country": "RU", "asn": "AS13238", "org": "YANDEX LLC",
                     "vendor": None, "vendor_source": None}
                 for h in ("mc.yandex.ru", "top-fwz1.mail.ru", "api.s.mindbox.ru", "content.adriver.ru")}
        hosts["store-b2b.ru"] = {"ips": ["2.2.2.2"], "country": "RU", "asn": "AS197695", "org": "REG.RU",
                                 "vendor": None, "vendor_source": None}
        hosts["rap.skcrtxr.com"] = {"ips": ["3.3.3.3"], "country": "RU", "asn": "AS49505", "org": "Selectel",
                                    "vendor": None, "vendor_source": None}
        write(root, "enrich/hosts.json", {"fetched_at": "2026-09-29T20:53:30+00:00", "hosts": hosts,
                                          "site": {"ips": ["95.129.233.81"], "country": "RU", "asn": "AS57724",
                                                   "org": "DDOS-GUARD LTD"}})
        write(root, "enrich/reachability.json", {"fetched_at": "2026-09-29T20:53:30+00:00", "ru_exit": True,
                                                 "home_status": 200, "final_url": TARGET + "/",
                                                 "block_stub": False, "matched_marker": None})
        write(root, "enrich/links.json", {"fetched_at": "2026-09-29T20:53:30+00:00", "links": [
            {"url": "https://t.me/posuda_dom", "host": "t.me", "platform": "telegram", "pages": ["index"],
             "visible": True, "in_jsonld": False, "status": 200, "title": "Посуда Дом", "brand_match": True,
             "brand_evidence": "og:title «Посуда Дом»"},
            {"url": "https://www.instagram.com/posuda_dom", "host": "www.instagram.com",
             "platform": "instagram", "pages": ["index"], "visible": False, "in_jsonld": True,
             "status": None, "title": None, "brand_match": None, "brand_evidence": None}]})
        write(root, "registries/rkn_hosting_providers.json", {
            "schema_version": 1, "registry": "rkn_hosting_providers", "title": "Реестр провайдеров хостинга",
            "fetched_at": "2026-09-29T20:53:00+00:00", "source_trust": "official", "origin": "live",
            "entries": [{"id": "1", "kind": "org", "name": "ООО «ДДОС-ГАРД»", "aliases": [], "inn": "6150061512"},
                        {"id": "2", "kind": "org", "name": "ООО «Регистратор доменных имён РЕГ.РУ»",
                         "aliases": []}]})
    for p in pages:
        slug = p["slug"]
        write(root, f"pages/{slug}/text.txt", p.pop("_text"))
        write(root, f"pages/{slug}/dom.html", p.pop("_dom"))
    manifest["pages"] = pages
    write(root, "manifest.json", manifest)
    for phase, rows in network_rows.items():
        write(root, f"network/{phase}.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    cookies = [{"name": n, "domain": ".shop.example.ru" if n.startswith("__ddg") else "shop.example.ru"}
               for n in COOKIES]
    write(root, "cookies/before_consent.json", cookies)
    write(root, "cookies/after_consent.json", cookies)
    for key in ("minjust_extremist_materials", "minjust_extremist_orgs", "fsb_terrorist_orgs",
                "minjust_foreign_agents", "minjust_undesirable_orgs"):
        write(root, f"registries/{key}.json", {
            "schema_version": 1, "registry": key, "title": key, "fetched_at": "2026-09-29T20:53:00+00:00",
            "source_trust": "official", "origin": "live",
            "entries": [{"id": "1", "kind": "org", "name": "Организация «Несуществующий Пример Семнадцать»",
                         "aliases": []}]})
    html = "<table><tr><td>77-25-000001</td><td>ООО «Посуда Дом»</td><td>7707083893</td></tr></table>"
    write(root, "registries/operators.json", {"inn": INN, "fetched_at": "2026-09-29T20:53:00+00:00",
                                              "source_trust": "official",
                                              "body_base64": base64.b64encode(html.encode()).decode()})
    return root


# Ожидаемые машинные вердикты. Левая колонка — сбор 2.4.0 без сценариев и
# доразведки: то, что закрывается уже по собранным данным. Правая — сбор 3.0.
# Записи вида ("UNKNOWN", ...) допустимы только с технической причиной.
EXPECTED = {
    #  rule        2.4-сбор     3.0-сбор
    "AUTH-001": ("UNKNOWN", "PASS"),
    "AUTH-002": ("UNKNOWN", "PASS"),
    "AUTH-003": ("UNKNOWN", "PASS"),
    "AUTH-004": ("UNKNOWN", "PASS"),
    "AUTH-005": ("PASS", "PASS"),
    "DISC-005": ("WARN", "WARN"),
    "DISC-008": ("PASS", "PASS"),
    "DISC-009": ("PASS", "PASS"),
    "PDN-003": ("FAIL", "FAIL"),
    "PDN-004": ("UNKNOWN", "PASS"),
    "PDN-005": ("UNKNOWN", "PASS"),
    "PDN-006": ("UNKNOWN", "PASS"),
    "PDN-008": ("FAIL", "FAIL"),
    "PDN-009": ("UNKNOWN", "PASS"),
    "PDN-010": ("PASS", "PASS"),
    "PDN-011": ("EXTERNAL", "EXTERNAL"),
    "PDN-012": ("FAIL", "FAIL"),
    "PDN-013": ("PASS", "PASS"),
    "CK-001": ("FAIL", "FAIL"),
    "CK-002": ("NA", "NA"),
    "CK-003": ("FAIL", "FAIL"),
    "CK-004": ("WARN", "WARN"),
    "CK-005": ("PASS", "PASS"),
    "CK-006": ("PASS", "PASS"),
    "CK-007": ("NA", "NA"),
    "LI-001": ("NA", "NA"),
    "INF-001": ("PASS", "PASS"),
    "INF-002": ("UNKNOWN", "PASS"),
    "INF-003": ("UNKNOWN", "PASS"),
    "INF-004": ("PASS", "PASS"),
    "ORG-001": ("PASS", "PASS"),
    "ORG-002": ("PASS", "PASS"),
    "ORG-003": ("FAIL", "FAIL"),
}
