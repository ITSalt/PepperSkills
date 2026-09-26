#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""collect.py — слой сбора данных о сайте.

Скрипт ничего не оценивает и ни о чём не судит: он только фиксирует факты в
воспроизводимом виде. Разделение намеренное — детекторы и смысловой анализ
работают с артефактами, а не с живым сайтом, поэтому проверку можно
перезапустить, перепроверить и предъявить как доказательство.

Ключевая особенность — два прохода по главной странице: до и после согласия с
cookie-баннером. Разница между ними показывает, какие трекеры загружаются без
согласия. Без этих двух проходов правило CK-003 проверить невозможно.

Использование:
    python3 scripts/collect.py https://example.ru --out artifacts/
    python3 scripts/collect.py https://example.ru --out artifacts/ --max-pages 25
    python3 scripts/collect.py https://example.ru --out artifacts/ --no-browser

Требуется playwright с установленным chromium. Без него скрипт переходит в
режим degraded: собирает статический HTML через urllib, но не видит SPA,
поведение баннера и сетевые запросы. Детекторы обязаны учитывать этот флаг и
выставлять UNKNOWN вместо PASS там, где данных не хватает.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Страницы, которые почти всегда несут юридически значимый текст. Пробуем их
# явно, потому что ссылка из футера может быть отрисована скриптом или скрыта.
CANDIDATE_PATHS = [
    "/privacy", "/privacy-policy", "/policy", "/politika", "/personal-data",
    "/personalnye-dannye", "/confidentiality", "/konfidencialnost",
    "/offer", "/oferta", "/terms", "/agreement", "/soglashenie", "/dogovor",
    "/contacts", "/contact", "/kontakty", "/about", "/o-kompanii",
    "/requisites", "/rekvizity",
    "/delivery", "/dostavka", "/payment", "/oplata",
    "/return", "/vozvrat", "/warranty", "/garantiya",
    "/login", "/signin", "/auth", "/vhod", "/register", "/signup", "/registraciya",
    "/cart", "/korzina", "/checkout", "/order", "/zakaz",
    "/cookies", "/cookie-policy",
]

# Текстовые маркеры для распознавания cookie-баннера. Список намеренно широкий:
# лучше найти лишний кандидат и отфильтровать его по кнопкам, чем пропустить
# баннер и получить ложный PASS по CK-001.
BANNER_TEXT_MARKERS = [
    "cookie", "куки", "файлы cookie", "cookies", "метрическ",
    "пользовательск", "согласие на обработку",
]
BANNER_SELECTOR_HINTS = [
    "[id*=cookie i]", "[class*=cookie i]", "[id*=consent i]", "[class*=consent i]",
    "[id*=gdpr i]", "[class*=gdpr i]", "[class*=cc-banner i]", "[class*=cookiebar i]",
    "[data-cookie]", "[aria-label*=cookie i]",
]
ACCEPT_TEXTS = [
    "принять", "принимаю", "согласен", "согласна", "соглашаюсь", "хорошо",
    "понятно", "ок", "ok", "accept", "allow all", "разрешить все",
    "разрешить всё", "принять все", "принять всё", "да",
]
REJECT_TEXTS = [
    "отклонить", "отказаться", "отказ", "только необходимые",
    "необходимые", "reject", "decline", "deny", "настроить",
    "управление", "настройки",
]


# --- Модель артефактов -------------------------------------------------------


@dataclass
class PageArtifact:
    url: str
    final_url: str = ""
    status: int | None = None
    slug: str = ""
    title: str = ""
    error: str | None = None
    forms: list[dict[str, Any]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    has_policy_link: bool = False
    policy_link_hrefs: list[str] = field(default_factory=list)
    text_chars: int = 0


@dataclass
class RunManifest:
    schema_version: int = SCHEMA_VERSION
    # Сайт может отдавать 403 на всё подряд (антибот). Это принципиально иной
    # исход, чем «нарушений не найдено», и детекторы обязаны его различать.
    blocked: bool = False
    target: str = ""
    started_at: str = ""
    finished_at: str = ""
    degraded: bool = False
    degraded_reason: str | None = None
    browser: str | None = None
    pages: list[dict[str, Any]] = field(default_factory=list)
    refusal: dict[str, Any] = field(default_factory=dict)
    banner: dict[str, Any] = field(default_factory=dict)
    infra: dict[str, Any] = field(default_factory=dict)
    source_dir: str | None = None
    # Юридические документы часто лежат PDF-файлами на CDN, а не HTML-страницами.
    # Ссылки на них нужно проверить отдельно: иначе «политика не опубликована»
    # выносится сайту, который её опубликовал, просто в другом формате.
    documents: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --- Вспомогательное ---------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    raw = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw).strip("_")
    return slug[:80] or "index"


# Составные доменные суффиксы: для них регистрируемый домен — три уровня, и
# «последние две метки» дали бы com.ru, под которым лежит пол-рунета.
MULTI_SUFFIXES = (
    "com.ru", "net.ru", "org.ru", "pp.ru", "msk.ru", "spb.ru", "nov.ru",
    "co.uk", "org.uk", "ac.uk", "com.tr", "com.br", "com.ua", "co.il",
    "com.cn", "com.au", "co.jp", "co.kr", "com.kz", "org.kz", "net.kz",
)


def registrable_domain(host: str) -> str:
    """Домен, который регистрируют: family-cinema.ru для app.family-cinema.ru."""
    host = (host or "").lower().strip(".")
    for suffix in MULTI_SUFFIXES:
        if host.endswith("." + suffix):
            return ".".join(host.split(".")[-3:])
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def same_host(url: str, host: str) -> bool:
    """Тот же сайт — значит тот же регистрируемый домен, а не тот же хост.

    Вход, личный кабинет и приложение почти всегда живут на поддомене
    (app.example.ru, lk.example.ru). Ограничение обхода точным хостом означает,
    что скилл не видит ровно те страницы, где собираются персональные данные и
    работает авторизация, — и потом честно пишет «проверить не удалось».
    Оператор при этом один и тот же, и требования к нему тоже одни.
    """
    try:
        found = urllib.parse.urlparse(url).netloc.split(":")[0].lower()
    except ValueError:
        return False
    if not found:
        return False
    return registrable_domain(found) == registrable_domain(host)


def normalize_target(target: str) -> str:
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    return target.rstrip("/")


# --- Инфраструктурная разведка ----------------------------------------------


def probe_http_redirect(host: str) -> dict[str, Any]:
    """Проверяет, уводит ли http:// на https://. Нужно для правила INF-001."""
    result: dict[str, Any] = {"http_reachable": False, "redirects_to_https": None,
                              "chain": []}
    req = urllib.request.Request(f"http://{host}/", headers={"User-Agent": USER_AGENT})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            result["chain"].append({"code": code, "location": newurl})
            if len(result["chain"]) > 5:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=15) as resp:
            result["http_reachable"] = True
            result["final_url"] = resp.geturl()
            result["redirects_to_https"] = resp.geturl().startswith("https://")
    except urllib.error.HTTPError as exc:
        result["http_reachable"] = True
        result["status"] = exc.code
    except Exception as exc:  # сеть, DNS, таймаут
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def probe_documents(urls: list[str], limit: int = 8) -> list[dict[str, Any]]:
    """Проверяет доступность найденных ссылок на юридические документы."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in urls:
        clean = url.split("#")[0]
        if clean in seen or not clean.startswith("http"):
            continue
        seen.add(clean)
        req = urllib.request.Request(clean, headers={"User-Agent": USER_AGENT})
        entry: dict[str, Any] = {"url": clean}
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read(200_000)
                entry.update(status=resp.status,
                             content_type=resp.headers.get("Content-Type", ""),
                             bytes=len(body),
                             final_url=resp.geturl())
        except urllib.error.HTTPError as exc:
            entry.update(status=exc.code, content_type="", bytes=0)
        except Exception as exc:
            entry.update(status=None, error=f"{type(exc).__name__}: {exc}")
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def probe_tls(host: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=15) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                info["protocol"] = tls.version()
                info["issuer"] = dict(x[0] for x in cert.get("issuer", ()))
                info["not_after"] = cert.get("notAfter")
                info["subject"] = dict(x[0] for x in cert.get("subject", ()))
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def resolve_ips(host: str) -> list[str]:
    ips: set[str] = set()
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            for item in socket.getaddrinfo(host, None, family):
                ips.add(item[4][0])
        except OSError:
            continue
    return sorted(ips)


def lookup_ip_geo(ip: str) -> dict[str, Any]:
    """Страна и оператор IP. Определяет применимость PDN-011 и INF-002.

    Источник намеренно один и внешний: заводить собственную базу GeoIP ради
    нескольких адресов дороже, чем принять UNKNOWN при недоступности сервиса.
    """
    url = f"https://ipinfo.io/{ip}/json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"ip": ip, "country": data.get("country"), "org": data.get("org"),
                "hostname": data.get("hostname")}
    except Exception as exc:
        return {"ip": ip, "error": f"{type(exc).__name__}: {exc}"}


def collect_infra(target: str) -> dict[str, Any]:
    host = urllib.parse.urlparse(target).netloc.split(":")[0]
    ips = resolve_ips(host)
    return {
        "host": host,
        "ips": ips,
        "geo": [lookup_ip_geo(ip) for ip in ips[:4]],
        "http": probe_http_redirect(host),
        "tls": probe_tls(host),
    }


# --- Обнаружение страниц -----------------------------------------------------


def fetch_text(url: str, timeout: int = 20) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.status, resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception:
        return None, ""


def discover_from_sitemap(target: str, limit: int = 200) -> list[str]:
    urls: list[str] = []
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/robots.txt"):
        status, body = fetch_text(target + path)
        if status != 200 or not body:
            continue
        if path.endswith("robots.txt"):
            for line in body.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm = line.split(":", 1)[1].strip()
                    st, sm_body = fetch_text(sm)
                    if st == 200:
                        urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm_body)
        else:
            urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        if len(urls) >= limit:
            break
    return urls[:limit]


def score_url(url: str) -> int:
    """Приоритет страницы для обхода. Юридически значимые страницы идут первыми,
    потому что бюджет обхода всегда меньше размера сайта."""
    low = url.lower()
    keywords = [
        ("privacy", 100), ("polic", 100), ("politik", 100), ("personal", 95),
        ("konfidenc", 95), ("oferta", 85), ("offer", 80), ("terms", 80),
        ("soglash", 80), ("contact", 75), ("kontakt", 75), ("rekvizit", 75),
        ("login", 70), ("auth", 70), ("signin", 70), ("registr", 70),
        ("checkout", 65), ("zakaz", 65), ("cart", 60), ("korzin", 60),
        ("dostavk", 55), ("delivery", 55), ("vozvrat", 55), ("return", 55),
        ("oplat", 50), ("payment", 50), ("cookie", 50), ("about", 40),
    ]
    return max((weight for kw, weight in keywords if kw in low), default=10)


def build_page_list(target: str, max_pages: int) -> list[str]:
    host = urllib.parse.urlparse(target).netloc.split(":")[0]
    seen: dict[str, None] = {target + "/": None}
    for path in CANDIDATE_PATHS:
        seen[target + path] = None
    for url in discover_from_sitemap(target):
        if same_host(url, host):
            seen[url] = None
    ordered = sorted(seen, key=lambda u: (-score_url(u), len(u)))
    # Главная всегда первой: с неё берутся футер, баннер и общий контекст.
    home = target + "/"
    ordered = [home] + [u for u in ordered if u != home]
    return ordered[:max_pages]


# --- JS, исполняемый в браузере ---------------------------------------------
# Вынесен отдельной константой, чтобы правки разметки не тонули в питоновском коде.

EXTRACT_JS = r"""
() => {
  const textOf = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');

  const labelFor = (input) => {
    if (input.id) {
      const byFor = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (byFor) return byFor;
    }
    return input.closest('label');
  };

  // На SPA поля ввода сплошь и рядом живут без тега <form>: отправку делает
  // обработчик на кнопке. Считать такую страницу «без форм» — значит не увидеть
  // ни сбора данных, ни отсутствия чекбокса согласия, то есть пропустить ровно
  // то, ради чего проверка и делается. Поэтому поля вне <form> собираются в
  // синтетическую форму по ближайшему общему контейнеру.
  const syntheticForms = (() => {
    const loose = Array.from(document.querySelectorAll('input, textarea, select'))
      .filter((el) => !el.closest('form'))
      .filter((el) => !['hidden', 'submit', 'button', 'image', 'reset']
        .includes((el.getAttribute('type') || '').toLowerCase()));
    if (!loose.length) return [];
    const groups = new Map();
    for (const el of loose) {
      let box = el;
      for (let up = 0; up < 4 && box.parentElement; up += 1) box = box.parentElement;
      if (!groups.has(box)) groups.set(box, []);
      groups.get(box).push(el);
    }
    return Array.from(groups.values());
  })();

  const formLike = Array.from(document.querySelectorAll('form'))
    .map((form) => ({ node: form, fields: Array.from(form.querySelectorAll('input, textarea, select')) }))
    .concat(syntheticForms.map((fields) => ({ node: fields[0].closest('div, section, main') || fields[0], fields, synthetic: true })));

  const forms = formLike.map((entry, idx) => {
    const form = entry.node;
    const fields = entry.fields.map((el) => {
      const label = labelFor(el);
      const linksInLabel = label
        ? Array.from(label.querySelectorAll('a[href]')).map((a) => a.getAttribute('href'))
        : [];
      return {
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || el.tagName.toLowerCase()).toLowerCase(),
        name: el.getAttribute('name'),
        placeholder: el.getAttribute('placeholder'),
        required: el.required === true,
        // Состояние читаем из свойства DOM, а не из атрибута: галочку часто
        // проставляет скрипт уже после загрузки, и в разметке checked не будет.
        checked: el.type === 'checkbox' || el.type === 'radio' ? el.checked : null,
        has_checked_attribute: el.hasAttribute('checked'),
        label_text: textOf(label).slice(0, 400),
        label_links: linksInLabel,
        autocomplete: el.getAttribute('autocomplete'),
      };
    });
    return {
      index: idx,
      selector: form.id ? `#${form.id}` : (entry.synthetic ? `поля без <form> #${idx + 1}` : `form:nth-of-type(${idx + 1})`),
      synthetic: entry.synthetic === true,
      action: entry.synthetic ? null : form.getAttribute('action'),
      method: entry.synthetic ? null : (form.getAttribute('method') || 'get').toLowerCase(),
      fields,
      checkbox_count: fields.filter((f) => f.type === 'checkbox').length,
      text: textOf(form).slice(0, 2000),
    };
  });

  const links = Array.from(document.querySelectorAll('a[href]'))
    .map((a) => a.href)
    .filter((h) => h.startsWith('http'));

  const policyRe = /(privacy|polic|politik|конфиденц|персональн|обработк[аи]\s+данн)/i;
  const policyLinks = Array.from(document.querySelectorAll('a[href]'))
    .filter((a) => policyRe.test(a.textContent || '') || policyRe.test(a.getAttribute('href') || ''))
    .map((a) => a.getAttribute('href'));

  return {
    title: document.title || '',
    forms,
    links: Array.from(new Set(links)).slice(0, 500),
    policy_links: Array.from(new Set(policyLinks)).slice(0, 20),
    text: (document.body ? document.body.innerText : '').slice(0, 400000),
  };
}
"""

FIND_BANNER_JS = r"""
(args) => {
  const { selectorHints, textMarkers, acceptTexts, rejectTexts } = args;
  const candidates = new Set();
  selectorHints.forEach((sel) => {
    try { document.querySelectorAll(sel).forEach((el) => candidates.add(el)); }
    catch (e) { /* невалидный селектор в конкретном браузере — пропускаем */ }
  });

  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 80 && rect.height > 20
      && style.visibility !== 'hidden' && style.display !== 'none'
      && Number(style.opacity) > 0.1;
  };

  const scored = [];
  candidates.forEach((el) => {
    if (!visible(el)) return;
    const text = (el.innerText || '').toLowerCase();
    if (!textMarkers.some((m) => text.includes(m))) return;
    const buttons = Array.from(el.querySelectorAll('button, a, input[type=button], input[type=submit], [role=button]'))
      .map((b) => ({
        text: ((b.innerText || b.value || '')).trim().slice(0, 120),
        tag: b.tagName.toLowerCase(),
      }))
      .filter((b) => b.text);
    if (!buttons.length) return;
    const lower = buttons.map((b) => b.text.toLowerCase());
    scored.push({
      selector: el.id ? `#${el.id}` : (el.className && typeof el.className === 'string'
        ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.')
        : el.tagName.toLowerCase()),
      text: (el.innerText || '').trim().slice(0, 1000),
      buttons,
      has_accept: lower.some((t) => acceptTexts.some((a) => t.includes(a))),
      has_reject: lower.some((t) => rejectTexts.some((r) => t.includes(r))),
      area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
      depth: (() => { let d = 0, n = el; while (n.parentElement) { d++; n = n.parentElement; } return d; })(),
    });
  });

  // Самый мелкий по вложенности из подходящих — это корень баннера, а не кнопка внутри.
  scored.sort((a, b) => a.depth - b.depth || b.area - a.area);
  return scored.slice(0, 3);
}
"""


# --- Сбор через браузер ------------------------------------------------------


class NetworkRecorder:
    """Пишет сетевые запросы в список. Отдельный экземпляр на каждый проход,
    чтобы диф «до и после согласия» строился на непересекающихся наборах."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def attach(self, page, phase: str, page_url: str) -> None:
        def on_request(request):
            try:
                self.requests.append({
                    "phase": phase,
                    "page": page_url,
                    "url": request.url,
                    "host": urllib.parse.urlparse(request.url).netloc,
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "is_navigation": request.is_navigation_request(),
                })
            except Exception:
                pass

        self.page = page
        self.handler = on_request
        page.on("request", on_request)

    def detach(self):
        self.page.remove_listener("request", self.handler)


def browser_collect(target: str, pages: list[str], out: Path,
                    manifest: RunManifest, timeout_ms: int,
                    max_pages: int = 20) -> None:
    from playwright.sync_api import sync_playwright

    host = urllib.parse.urlparse(target).netloc.split(":")[0]
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "network").mkdir(parents=True, exist_ok=True)
    (out / "cookies").mkdir(parents=True, exist_ok=True)
    # A rerun must not reuse successful refusal evidence from a previous run.
    for phase in ("before_consent", "after_consent", "before_reject", "after_reject", "revisit_reject", "walk", "all"):
        (out / "network" / f"{phase}.jsonl").unlink(missing_ok=True)
        (out / "cookies" / f"{phase}.json").unlink(missing_ok=True)
    (out / "refusal-storage-state.json").unlink(missing_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        manifest.browser = f"chromium {browser.version}"

        # --- Проход 1: до согласия. Чистый контекст без cookie. ---
        ctx = browser.new_context(user_agent=USER_AGENT, locale="ru-RU",
                                  timezone_id="Europe/Moscow",
                                  viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        before = NetworkRecorder()
        before.attach(page, "before_consent", target + "/")
        try:
            page.goto(target + "/", wait_until="networkidle", timeout=timeout_ms)
        except Exception as exc:
            manifest.notes.append(f"первый проход: {type(exc).__name__}: {exc}")
        page.wait_for_timeout(2500)

        # Ссылки с главной дополняют список обхода. Угадывание путей
        # (/privacy, /policy, ...) работает на типовых сайтах и промахивается на
        # всех остальных: политика может лежать по любому адресу, а ссылка на
        # неё в футере есть всегда.
        try:
            home_data = page.evaluate(EXTRACT_JS)
            discovered: list[str] = []
            for href in (home_data.get("policy_links") or []):
                discovered.append(urllib.parse.urljoin(target + "/", href))
            # Бюджет обхода существует, чтобы его использовать: раньше фильтр по
            # «юридической значимости» отсекал обычные разделы сайта, и лендинг
            # из четырёх страниц выглядел как одностраничник. Берём все внутренние
            # ссылки, приоритет — по значимости, отсечение — по бюджету.
            internal = sorted(
                {l.split("#")[0].rstrip("/") for l in (home_data.get("links") or [])
                 if same_host(l, host)},
                key=lambda u: (-score_url(u), len(u)))
            discovered.extend(internal)
            known = {u.rstrip("/") for u in pages}
            for url in discovered:
                clean = url.split("#")[0]
                if clean.rstrip("/") not in known and len(pages) < max_pages + 10:
                    pages.append(clean)
                    known.add(clean.rstrip("/"))
            manifest.notes.append(f"добавлено по ссылкам с главной: "
                                  f"{len(pages) - len(known) + len(discovered)}")
        except Exception as exc:
            manifest.notes.append(f"разбор ссылок главной: {type(exc).__name__}")

        banner_candidates = page.evaluate(FIND_BANNER_JS, {
            "selectorHints": BANNER_SELECTOR_HINTS,
            "textMarkers": BANNER_TEXT_MARKERS,
            "acceptTexts": ACCEPT_TEXTS,
            "rejectTexts": REJECT_TEXTS,
        })
        cookies_before = ctx.cookies()
        (out / "cookies" / "before_consent.json").write_text(
            json.dumps(cookies_before, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(out / "pages" / "home_before_consent.png"),
                        full_page=False)

        banner = {
            "found": bool(banner_candidates),
            "candidates": banner_candidates,
            "accepted": False,
            "accept_button": None,
        }

        before.detach()
        after = NetworkRecorder()
        after.attach(page, "after_consent", target + "/")

        # --- Клик по кнопке согласия в том же контексте. ---
        if banner_candidates:
            top = banner_candidates[0]
            for btn in top.get("buttons", []):
                if any(a in btn["text"].lower() for a in ACCEPT_TEXTS):
                    try:
                        page.locator(top["selector"]).first.get_by_text(btn["text"], exact=True).first.click(timeout=5000)
                        banner["accepted"] = True
                        banner["accept_button"] = btn["text"]
                        page.wait_for_timeout(3000)
                    except Exception as exc:
                        banner["click_error"] = f"{type(exc).__name__}: {exc}"
                    break

        try:
            page.reload(wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        cookies_after = ctx.cookies()
        (out / "cookies" / "after_consent.json").write_text(
            json.dumps(cookies_after, ensure_ascii=False, indent=2), encoding="utf-8")
        page.screenshot(path=str(out / "pages" / "home_after_consent.png"),
                        full_page=False)
        manifest.banner = banner

        write_jsonl(out / "network" / "before_consent.jsonl", before.requests)
        write_jsonl(out / "network" / "after_consent.jsonl", after.requests)
        page.close()

        # Refusal starts in a separate clean context, never after acceptance.
        refusal_requests = collect_refusal(browser, target, out, manifest, timeout_ms)

        # --- Обход остальных страниц. Контекст с уже данным согласием: цель —
        # полнота текста и форм, а не повторная проверка гейтинга. ---
        walker = NetworkRecorder()
        for url in pages:
            art = PageArtifact(url=url, slug=slugify(url))
            p = ctx.new_page()
            walker.attach(p, "walk", url)
            try:
                resp = p.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                art.status = resp.status if resp else None
                art.final_url = p.url
                p.wait_for_timeout(1200)
                data = p.evaluate(EXTRACT_JS)
                art.title = data["title"]
                art.forms = data["forms"]
                art.links = [l for l in data["links"] if same_host(l, host)][:200]
                art.policy_link_hrefs = data["policy_links"]
                art.has_policy_link = bool(data["policy_links"])
                art.text_chars = len(data["text"])
                page_dir = out / "pages" / art.slug
                page_dir.mkdir(parents=True, exist_ok=True)
                (page_dir / "dom.html").write_text(p.content(), encoding="utf-8")
                (page_dir / "text.txt").write_text(data["text"], encoding="utf-8")
                try:
                    p.screenshot(path=str(page_dir / "screenshot.png"), full_page=False)
                except Exception:
                    pass
            except Exception as exc:
                art.error = f"{type(exc).__name__}: {exc}"
            finally:
                p.close()
            manifest.pages.append(asdict(art))
            page_dir = out / "pages" / art.slug
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "page.json").write_text(
                json.dumps(asdict(art), ensure_ascii=False, indent=2), encoding="utf-8")

        write_jsonl(out / "network" / "walk.jsonl", walker.requests)
        all_requests = before.requests + after.requests + refusal_requests + walker.requests
        write_jsonl(out / "network" / "all.jsonl", all_requests)
        ctx.close()
        browser.close()


def collect_refusal(browser, target, out, manifest, timeout_ms):
    """Independent refusal plus a new context restored from storage_state."""
    options = dict(user_agent=USER_AGENT, locale="ru-RU", timezone_id="Europe/Moscow",
                   viewport={"width": 1440, "height": 900})
    ctx = browser.new_context(**options)
    page = ctx.new_page()
    result = {"click_status": "not_found", "revisit_completed": False}
    manifest.refusal = result
    rows = []
    recorder = NetworkRecorder()
    recorder.attach(page, "before_reject", target + "/")
    try:
        page.goto(target + "/", wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(2500)
        candidates = page.evaluate(FIND_BANNER_JS, {
            "selectorHints": BANNER_SELECTOR_HINTS, "textMarkers": BANNER_TEXT_MARKERS,
            "acceptTexts": ACCEPT_TEXTS, "rejectTexts": REJECT_TEXTS})
        recorder.detach()
        write_jsonl(out / "network/before_reject.jsonl", recorder.requests)
        rows.extend(recorder.requests)
        (out / "cookies/before_reject.json").write_text(json.dumps(ctx.cookies(), ensure_ascii=False))
        recorder = NetworkRecorder()
        recorder.attach(page, "after_reject", target + "/")
        for candidate in candidates:
            button = next((b for b in candidate.get("buttons", [])
                           if any(r in b["text"].lower() for r in REJECT_TEXTS)), None)
            if not button:
                continue
            result["button"] = button["text"]
            try:
                page.locator(candidate["selector"]).first.get_by_text(
                    button["text"], exact=True).first.click(timeout=5000)
                result["click_status"] = "clicked"
                page.wait_for_timeout(3000)
            except Exception as exc:
                result.update(click_status="failed", error=f"{type(exc).__name__}: {exc}")
            break
        recorder.detach()
        write_jsonl(out / "network/after_reject.jsonl", recorder.requests)
        rows.extend(recorder.requests)
        (out / "cookies/after_reject.json").write_text(json.dumps(ctx.cookies(), ensure_ascii=False))
        page.screenshot(path=str(out / "pages/home_after_reject.png"))
        if result["click_status"] != "clicked":
            return rows
        # JSON state captures cookie + localStorage; no reuse of the accepted context.
        state_path = out / "refusal-storage-state.json"
        ctx.storage_state(path=str(state_path))
        state_path.chmod(0o600)
        result["storage_state"] = state_path.name
        ctx.close()
        ctx = browser.new_context(**options, storage_state=str(state_path))
        page = ctx.new_page()
        recorder = NetworkRecorder()
        recorder.attach(page, "revisit_reject", target + "/")
        page.goto(target + "/", wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(2500)
        recorder.detach()
        write_jsonl(out / "network/revisit_reject.jsonl", recorder.requests)
        rows.extend(recorder.requests)
        (out / "cookies/revisit_reject.json").write_text(json.dumps(ctx.cookies(), ensure_ascii=False))
        page.screenshot(path=str(out / "pages/home_revisit_reject.png"))
        result["revisit_completed"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if result["click_status"] == "not_found":
            result["click_status"] = "not_observed"
    finally:
        ctx.close()
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# --- Сбор без браузера -------------------------------------------------------


def fallback_collect(pages: list[str], out: Path, manifest: RunManifest) -> None:
    """Режим degraded: статический HTML без рендера.

    Формы и текст здесь видны только у серверных страниц, сетевые запросы и
    поведение баннера не видны вовсе. Детекторы обязаны читать manifest.degraded
    и не выдавать PASS по правилам, которые без рендера не проверяются.
    """
    tag_re = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
    for url in pages:
        art = PageArtifact(url=url, slug=slugify(url))
        status, body = fetch_text(url)
        art.status = status
        art.final_url = url
        if body:
            title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            art.title = (title.group(1).strip() if title else "")[:300]
            text = re.sub(r"<[^>]+>", " ", tag_re.sub(" ", body))
            text = re.sub(r"\s+", " ", text).strip()
            art.text_chars = len(text)
            art.policy_link_hrefs = re.findall(
                r'href=["\']([^"\']*(?:privacy|polic|politik|personal)[^"\']*)["\']',
                body, re.I)[:20]
            art.has_policy_link = bool(art.policy_link_hrefs)
            page_dir = out / "pages" / art.slug
            page_dir.mkdir(parents=True, exist_ok=True)
            (page_dir / "dom.html").write_text(body, encoding="utf-8")
            (page_dir / "text.txt").write_text(text, encoding="utf-8")
            (page_dir / "page.json").write_text(
                json.dumps(asdict(art), ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.pages.append(asdict(art))


# --- Точка входа -------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Сбор артефактов сайта для проверки комплаенса")
    parser.add_argument("target", help="URL сайта, например https://example.ru")
    parser.add_argument("--out", default="artifacts", help="каталог для артефактов")
    parser.add_argument("--max-pages", type=int, default=20, help="бюджет обхода")
    parser.add_argument("--timeout", type=int, default=45000, help="таймаут навигации, мс")
    parser.add_argument("--no-browser", action="store_true",
                        help="принудительно режим degraded без playwright")
    parser.add_argument("--source-dir", default=None,
                        help="каталог исходников проекта для white-box режима")
    args = parser.parse_args()

    target = normalize_target(args.target)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    manifest = RunManifest(target=target, started_at=now_iso(),
                           source_dir=args.source_dir)

    print(f"[1/3] Разведка инфраструктуры {target}", file=sys.stderr)
    manifest.infra = collect_infra(target)

    print("[2/3] Построение списка страниц", file=sys.stderr)
    pages = build_page_list(target, args.max_pages)
    print(f"      к обходу: {len(pages)}", file=sys.stderr)

    print("[3/3] Сбор", file=sys.stderr)
    if args.no_browser:
        manifest.degraded = True
        manifest.degraded_reason = "запрошен режим --no-browser"
        fallback_collect(pages, out, manifest)
    else:
        try:
            browser_collect(target, pages, out, manifest, args.timeout, args.max_pages)
        except ImportError as exc:
            manifest.degraded = True
            manifest.degraded_reason = f"playwright недоступен: {exc}"
            print(f"      playwright недоступен, режим degraded: {exc}", file=sys.stderr)
            fallback_collect(pages, out, manifest)

    # Ссылки на юридические документы со всех обойдённых страниц.
    doc_links: list[str] = []
    for page in manifest.pages:
        for href in page.get("policy_link_hrefs") or []:
            doc_links.append(urllib.parse.urljoin(page.get("final_url") or target, href))
    if doc_links:
        manifest.documents = probe_documents(doc_links)
        ok_docs = sum(1 for d in manifest.documents if d.get("status") == 200)
        print(f"  документов по ссылкам: {ok_docs} из {len(manifest.documents)}",
              file=sys.stderr)

    # Антибот-защита: страницы отвечают, но контента нет. Считаем обход
    # заблокированным, если ни одна страница не открылась, а отказы были.
    statuses = [p.get("status") for p in manifest.pages]
    denied = sum(1 for st in statuses if st in (401, 403, 429))
    if not any(st == 200 for st in statuses) and (denied or not statuses):
        manifest.blocked = True
        manifest.notes.append(
            f"обход заблокирован: ни одна страница не открылась "
            f"(отказов {denied} из {len(statuses)})")

    manifest.finished_at = now_iso()
    (out / "manifest.json").write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for p in manifest.pages if p.get("status") == 200)
    forms = sum(len(p.get("forms") or []) for p in manifest.pages)
    print(f"\nГотово: {out}", file=sys.stderr)
    print(f"  страниц собрано: {ok}/{len(manifest.pages)}", file=sys.stderr)
    print(f"  форм найдено: {forms}", file=sys.stderr)
    print(f"  баннер: {'найден' if manifest.banner.get('found') else 'не найден'}"
          f"{', согласие нажато' if manifest.banner.get('accepted') else ''}",
          file=sys.stderr)
    print(f"  режим: {'degraded' if manifest.degraded else 'полный'}", file=sys.stderr)
    if manifest.blocked:
        print("  ВНИМАНИЕ: обход заблокирован сайтом — проверка невозможна",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
