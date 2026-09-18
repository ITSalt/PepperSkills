#!/usr/bin/env python3
"""detect.py — детерминированный слой проверки.

Читает артефакты `collect.py` и выдаёт `findings.json`. Ничего не запрашивает
у сайта повторно: все выводы делаются из зафиксированных данных, поэтому
проверку можно перезапустить и предъявить доказательство по любому пункту.

Три правила, которые здесь важнее удобства:

1. **Статус без доказательства не выставляется.** Каждая находка несёт ссылку
   на конкретный сетевой запрос, селектор или фрагмент текста. Вывод, который
   нечем подтвердить, — это `UNKNOWN`, а не догадка.
2. **Нехватка данных — не `PASS`.** Если краулер работал без рендера, реестр не
   загрузился или страница не открылась, правило отдаёт `UNKNOWN`. Молча
   выданное «нарушений нет» по неполным данным — худший отказ этого скилла:
   владелец сайта ничего не сделает и получит штраф.
3. **Происхождение данных едет вместе с выводом.** Совпадение по зеркалу и по
   официальному реестру — утверждения разной силы, и в findings они различимы.

Использование:
    python3 scripts/detect.py --artifacts artifacts/ --out findings.json
    python3 scripts/detect.py --artifacts artifacts/ --out findings.json --inn 7736207543
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registries as reg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "scripts" / "rules.yaml"
SIGNATURES_PATH = ROOT / "scripts" / "signatures.yaml"


def load_data(yaml_path: Path) -> dict[str, Any]:
    """Читает YAML, если есть PyYAML, иначе — сгенерированный JSON-двойник.

    YAML остаётся форматом для человека: правила — юридический текст, который
    правят руками. Но требовать PyYAML на машине пользователя ради чтения двух
    файлов — плохой размен, поэтому рядом лежит `*.json`, собранный
    `gen_checklist.py`. Если оба на месте, приоритет у YAML: он источник правды.
    """
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except ImportError:
        pass
    twin = yaml_path.with_suffix(".json")
    if not twin.exists():
        raise SystemExit(
            f"нет ни PyYAML, ни {twin.name}. Выполните "
            f"`python3 scripts/gen_checklist.py` на машине с PyYAML "
            f"либо установите PyYAML.")
    return json.loads(twin.read_text(encoding="utf-8"))
SCHEMA_VERSION = 1


# --- Модель вывода -----------------------------------------------------------


@dataclass
class Evidence:
    kind: str                      # request | dom | text | http | registry | infra
    detail: str
    url: str | None = None
    selector: str | None = None
    snippet: str | None = None


@dataclass
class Finding:
    rule_id: str
    group: str
    title: str
    status: str                    # PASS | FAIL | WARN | NA | UNKNOWN
    severity: str
    norm: str | None = None
    liability: str | None = None
    # Вилка штрафа для юрлиц отдельным полем: в записке это колонка таблицы, и
    # выдёргивать её регуляркой из слепленной строки — лишний источник ошибок.
    # Санкции за повторное нарушение сюда не попадают: они применимы не всегда
    # и в обзорной таблице завышали бы картину.
    fine_legal: str | None = None
    summary: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    fix_hint: str | None = None
    # Как проверить пункт руками. Нужна там, где скрипт вывода не даёт:
    # «не проверено» без инструкции — это перекладывание проблемы на читателя.
    manual_check: str | None = None
    # Чем правило проверяется (script | hybrid | llm | info_only) и как звучит
    # условие соблюдения. Нужно плану: критерий приёмки «прогнать detect.py»
    # честен только для правил, которые скрипт действительно умеет закрывать.
    check: str | None = None
    pass_criterion: str | None = None
    # Гибридные правила закрывает смысловой слой: скрипт даёт кандидатов и
    # доказательства, окончательный статус ставит LLM.
    needs_llm: bool = False
    source_trust: str | None = None
    source_note: str | None = None


class Context:
    """Загруженные артефакты одного прогона."""

    def __init__(self, artifacts: Path, inn: str | None = None) -> None:
        self.dir = artifacts
        self.manifest = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))
        self.degraded: bool = self.manifest.get("degraded", False)
        self.blocked: bool = bool(self.manifest.get("blocked"))
        if not self.blocked:
            # Флаг ставит сборщик, но вывод не должен зависеть от того, какой
            # версией он собран: если ни одна страница не открылась, а отказы
            # были, обход заблокирован — что бы ни лежало в манифесте.
            statuses = [p.get("status") for p in self.manifest.get("pages", [])]
            denied = sum(1 for st in statuses if st in (401, 403, 429))
            self.blocked = bool(statuses and denied
                                and not any(st == 200 for st in statuses))
        self.documents: list[dict[str, Any]] = self.manifest.get("documents") or []
        self.target: str = self.manifest.get("target", "")
        self.pages: list[dict[str, Any]] = self.manifest.get("pages", [])
        self.banner: dict[str, Any] = self.manifest.get("banner") or {}
        self.infra: dict[str, Any] = self.manifest.get("infra") or {}
        self.inn = inn
        self.rules = {r["id"]: r for r in load_data(RULES_PATH)["rules"]}
        self.sig = load_data(SIGNATURES_PATH)
        self.net = {phase: self._load_net(phase)
                    for phase in ("before_consent", "after_consent", "walk")}
        self.cookies = {phase: self._load_json(f"cookies/{phase}.json", [])
                        for phase in ("before_consent", "after_consent")}
        self._texts: dict[str, str] | None = None
        self._doms: dict[str, str] | None = None
        self._registries: dict[str, reg.RegistryData] = {}

    def _load_net(self, phase: str) -> list[dict[str, Any]]:
        path = self.dir / "network" / f"{phase}.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _load_json(self, rel: str, default: Any) -> Any:
        path = self.dir / rel
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    @property
    def texts(self) -> dict[str, str]:
        """Текст каждой страницы: slug -> текст."""
        if self._texts is None:
            self._texts = {}
            for page in self.pages:
                path = self.dir / "pages" / page.get("slug", "") / "text.txt"
                if path.exists():
                    self._texts[page["slug"]] = path.read_text(encoding="utf-8",
                                                               errors="replace")
        return self._texts

    @property
    def doms(self) -> dict[str, str]:
        if self._doms is None:
            self._doms = {}
            for page in self.pages:
                path = self.dir / "pages" / page.get("slug", "") / "dom.html"
                if path.exists():
                    self._doms[page["slug"]] = path.read_text(encoding="utf-8",
                                                              errors="replace")
        return self._doms

    def all_requests(self) -> list[dict[str, Any]]:
        return [r for rows in self.net.values() for r in rows]

    def page_by_slug(self, slug: str) -> dict[str, Any]:
        for page in self.pages:
            if page.get("slug") == slug:
                return page
        return {}

    @property
    def analysed(self) -> int:
        return len([p for p in self.pages if p.get("status") == 200])

    @property
    def unvisited_links(self) -> int:
        """Внутренние ссылки, до которых обход не дошёл."""
        crawled = {(p.get("final_url") or p.get("url") or "").split("#")[0].rstrip("/")
                   for p in self.pages}
        found: set[str] = set()
        site = host_of(self.target)
        for page in self.pages:
            for link in page.get("links") or []:
                clean = link.split("#")[0].rstrip("/")
                if clean and first_party(clean, self.target):
                    found.add(clean)
        return len(found - crawled)

    @property
    def thin_coverage(self) -> bool:
        """Охвата не хватает для утверждений об отсутствии.

        Дело не в числе страниц самом по себе: одностраничный лендинг из одной
        страницы обойдён полностью, и оговорка про охват там только зашумляет
        отчёт. Охват недостаточен, когда обход не дошёл до страниц, которые
        видел, — тогда «упоминаний не найдено» действительно ничего не значит.
        """
        return self.analysed < 3 and self.unvisited_links > 2

    def registry(self, key: str) -> reg.RegistryData:
        if key not in self._registries:
            self._registries[key] = reg.load_registry(key)
        return self._registries[key]


# --- Вспомогательное ---------------------------------------------------------


def registrable_domain(host: str) -> str:
    """Домен, который регистрируют: family-cinema.ru для app.family-cinema.ru."""
    host = (host or "").lower().strip(".")
    for suffix in MULTI_SUFFIXES:
        if host.endswith("." + suffix):
            return ".".join(host.split(".")[-3:])
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def first_party(url: str, target: str) -> bool:
    """Свой ли это хост. Поддомен оператора — свой: данные, ушедшие на
    app.example.ru, никуда за пределы оператора не ушли, и называть это
    трансграничной передачей или сторонним приёмником неверно."""
    host = host_of(url)
    return bool(host) and registrable_domain(host) == registrable_domain(host_of(target))


MULTI_SUFFIXES = (
    "com.ru", "net.ru", "org.ru", "pp.ru", "msk.ru", "spb.ru", "nov.ru",
    "co.uk", "org.uk", "ac.uk", "com.tr", "com.br", "com.ua", "co.il",
    "com.cn", "com.au", "co.jp", "co.kr", "com.kz", "org.kz", "net.kz",
)


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.split(":")[0].lower()
    except ValueError:
        return ""


def match_host(host: str, spec: dict[str, Any]) -> bool:
    want = spec.get("host", "")
    if spec.get("match") == "suffix":
        return host == want or host.endswith("." + want)
    return host == want


def match_signature(url: str, group: dict[str, Any]) -> bool:
    """Совпадение URL с блоком сигнатур (hosts / host_suffixes / paths / patterns)."""
    host, path = host_of(url), urllib.parse.urlparse(url).path
    if host in (group.get("hosts") or []):
        paths = group.get("paths")
        return (not paths) or any(p in path for p in paths)
    for suffix in group.get("host_suffixes") or []:
        if host.endswith(suffix):
            return True
    for pattern in group.get("host_patterns") or []:
        if re.search(pattern, host):
            return True
    return False


def mk(ctx: Context, rule_id: str, status: str, summary: str,
       evidence: list[Evidence] | None = None, **extra: Any) -> Finding:
    """Собирает находку, подтягивая норму и санкцию из реестра правил."""
    rule = ctx.rules.get(rule_id, {})
    liability = rule.get("liability") or {}
    fines = liability.get("fines") or {}
    return Finding(
        rule_id=rule_id,
        group=rule.get("group", "?"),
        title=rule.get("title", rule_id),
        status=status,
        severity=rule.get("severity", "medium"),
        norm=(rule.get("norm") or {}).get("act"),
        liability=(f"{liability.get('article')}: юрлица {fines.get('legal_entity')}"
                   if liability.get("article") and fines.get("legal_entity")
                   else liability.get("article")),
        fine_legal=fines.get("legal_entity"),
        summary=summary,
        evidence=[asdict(e) for e in (evidence or [])],
        fix_hint=rule.get("fix_hint"),
        manual_check=extra.pop("manual_check", None) or rule.get("manual_check"),
        check=rule.get("check"),
        pass_criterion=(rule.get("status_logic") or {}).get("PASS"),
        **extra,
    )


CLICKABLE_RE = re.compile(r"<(a|button)\b[^>]*>(.{0,400}?)</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def clickable_labels(dom: str, limit: int = 600) -> list[str]:
    """Тексты ссылок и кнопок страницы.

    Слово «вход» в сплошном тексте — это чаще всего «входные файлы» или «не
    входит в стоимость». Слово «Вход» в подписи ссылки — это вход. Разделить
    их можно только по разметке, поэтому подписи извлекаются отдельно от
    текста страницы.
    """
    out: list[str] = []
    for match in CLICKABLE_RE.finditer(dom):
        label = re.sub(r"\s+", " ", TAG_RE.sub(" ", match.group(2))).strip().lower()
        if label and len(label) <= 40:
            out.append(label)
        if len(out) >= limit:
            break
    return out


def word_in(text: str, phrase: str) -> bool:
    """Вхождение фразы как отдельного слова, а не как части другого.

    «Вход» внутри «входит» — совпадение по подстроке и промах по смыслу;
    именно так страница с расшифровкой вебинара становилась страницей входа.
    """
    return re.search(r"(?<![0-9a-zа-яё])" + re.escape(phrase)
                     + r"(?![0-9a-zа-яё])", text) is not None


def looks_like_login_page(ctx: Context, page: dict[str, Any]) -> bool:
    """Есть ли на странице признаки входа или регистрации.

    Признак должен быть структурным: поле пароля, адрес страницы входа,
    подпись ссылки. Сплошной текст сюда допускается только для формулировок,
    которые в обычной прозе не встречаются, — иначе оферта с разделом
    «Регистрация и аккаунт» объявляет авторизацию на сайте, где её нет, а за
    этим следует нарушение по AUTH-004.
    """
    lc = ctx.sig["auth"]["login_context"]
    url = (page.get("final_url") or page.get("url") or "").lower()
    path = urllib.parse.urlparse(url).path
    segments = {s for s in re.split(r"[^0-9a-z]+", path) if s}
    if segments & set(lc["url_segments"]):
        return True

    dom = ctx.doms.get(page.get("slug", ""), "")
    if 'type="password"' in dom or "type='password'" in dom:
        return True
    for form in page.get("forms") or []:
        if any(f.get("type") == "password" for f in form.get("fields") or []):
            return True
        action = (form.get("action") or "").lower()
        if any(seg in action for seg in lc["action_patterns"]):
            return True

    labels = clickable_labels(dom)
    if any(word_in(label, phrase) for label in labels
           for phrase in lc["anchor_labels"]):
        return True

    text = (ctx.texts.get(page.get("slug", ""), "")[:4000]).lower()
    return any(word_in(text, p) for p in lc["text_patterns"])


# --- Детекторы ---------------------------------------------------------------

DETECTORS: dict[str, Callable[[Context], list[Finding]]] = {}


def detector(name: str):
    def wrap(fn):
        DETECTORS[name] = fn
        return fn
    return wrap


@detector("auth_providers")
def detect_auth(ctx: Context) -> list[Finding]:
    sig = ctx.sig["auth"]
    out: list[Finding] = []
    login_pages = [p for p in ctx.pages if looks_like_login_page(ctx, p)]
    has_auth = bool(login_pages)

    def scan(block: dict[str, Any], rule_id: str) -> list[Evidence]:
        found: list[Evidence] = []
        for vendor, group in block.items():
            for req in ctx.all_requests():
                if match_signature(req["url"], group):
                    found.append(Evidence(
                        kind="request",
                        detail=f"{vendor}: сетевой запрос на странице {req.get('page','')}",
                        url=req["url"][:200]))
                    break
            for slug, dom in ctx.doms.items():
                for marker in group.get("markers") or []:
                    if marker in dom:
                        found.append(Evidence(
                            kind="dom", detail=f"{vendor}: маркер в разметке",
                            selector=slug, snippet=marker))
                        break
        return found

    for rule_id, block_name in (("AUTH-001", "foreign_oauth"),
                                ("AUTH-003", "foreign_idaas")):
        ev = scan(sig[block_name], rule_id)
        if not ev:
            out.append(mk(ctx, rule_id, "PASS", "Маркеров не обнаружено"))
        elif has_auth:
            out.append(mk(ctx, rule_id, "FAIL",
                          f"Найдено признаков: {len(ev)}; на сайте есть авторизация",
                          ev[:6]))
        else:
            out.append(mk(ctx, rule_id, "WARN",
                          "Маркеры найдены, но страница входа не обнаружена — "
                          "возможно, SDK подключён и не используется", ev[:6]))

    # Telegram: отделяем виджет входа от бота и ссылок на канал.
    tg = sig["telegram"] if "telegram" in sig else sig["telegram"]
    tg_ev: list[Evidence] = []
    for req in ctx.all_requests():
        if match_signature(req["url"], tg):
            tg_ev.append(Evidence(kind="request", detail="Telegram Login Widget",
                                  url=req["url"][:200]))
    for slug, dom in ctx.doms.items():
        for marker in tg["markers"]:
            if marker in dom:
                tg_ev.append(Evidence(kind="dom", detail="виджет входа Telegram",
                                      selector=slug, snippet=marker))
                break
    if tg_ev:
        out.append(mk(ctx, "AUTH-002", "FAIL" if has_auth else "WARN",
                      "Обнаружен виджет входа через Telegram", tg_ev[:4]))
    else:
        out.append(mk(ctx, "AUTH-002", "PASS", "Виджет входа Telegram не обнаружен"))

    # Разрешённые способы (AUTH-004, AUTH-006).
    allowed = sig["allowed_ru"]
    allowed_ev: list[Evidence] = []
    for vendor, group in allowed.items():
        if vendor == "phone_field":
            continue
        for req in ctx.all_requests():
            if match_signature(req["url"], group):
                allowed_ev.append(Evidence(kind="request", detail=f"разрешённый провайдер: {vendor}",
                                           url=req["url"][:200]))
                break
    phone = allowed["phone_field"]
    for page in ctx.pages:
        for form in page.get("forms") or []:
            for f in form.get("fields") or []:
                if (f.get("type") in phone["input_types"]
                        or (f.get("autocomplete") or "") in phone["autocomplete"]):
                    allowed_ev.append(Evidence(kind="dom", detail="поле ввода телефона",
                                               selector=f"{page.get('slug')} {form.get('selector')}"))
                    break
    # Вкладки и кнопки на странице входа. Провайдер подгружает свой SDK после
    # клика по вкладке, поэтому в сетевом логе его нет, — а надпись «VK» на
    # форме входа есть, и именно она говорит, что способ предложен.
    labels_cfg = sig.get("allowed_labels") or {}
    seen_vendors = {e.detail for e in allowed_ev}
    for page in login_pages:
        labels = clickable_labels(ctx.doms.get(page.get("slug", ""), ""))
        for vendor, variants in labels_cfg.items():
            if vendor == "own":
                continue
            detail = f"разрешённый способ на форме входа: {vendor}"
            if detail in seen_vendors:
                continue
            if any(word_in(label, v) for label in labels for v in variants):
                seen_vendors.add(detail)
                allowed_ev.append(Evidence(kind="dom", detail=detail,
                                           selector=page.get("slug", "")))

    # Собственная учётная запись сайта — тоже разрешённый способ (пп. 4 п. 10
    # ст. 8 ФЗ-149: иная информационная система российского лица). Пароль для
    # этого не обязателен: вход по коду на почту — та же собственная система.
    own_form = any(any(f.get("type") == "password" for f in (form.get("fields") or []))
                   for p in ctx.pages for form in (p.get("forms") or []))
    if not own_form:
        own_form = any(
            any((f.get("type") or "").lower() in ("email", "tel")
                for f in (form.get("fields") or []))
            for page in login_pages for form in (page.get("forms") or []))

    foreign_ev = [f for f in out
                  if f.rule_id in ("AUTH-001", "AUTH-002", "AUTH-003")
                  and f.status in ("FAIL", "WARN")]

    if not has_auth:
        out.append(mk(ctx, "AUTH-004", "NA", "Признаков авторизации на сайте не найдено"))
    elif allowed_ev or own_form:
        detail = "собственная форма входа" if own_form and not allowed_ev else "разрешённый способ"
        out.append(mk(ctx, "AUTH-004", "PASS", f"Найден {detail}",
                      allowed_ev[:4] or [Evidence(kind="dom", detail="поле пароля в форме входа")]))
    elif foreign_ev:
        out.append(mk(ctx, "AUTH-004", "FAIL",
                      "Авторизация есть, и все обнаруженные способы — иностранные",
                      [Evidence(kind="dom", detail=f.summary, selector=f.rule_id)
                       for f in foreign_ev]))
    else:
        # Ссылка «Войти» есть, а самой страницы входа обход не достиг: какими
        # способами пускают внутрь, неизвестно. Это не нарушение и не
        # соответствие — это непроверенное место, и назвать его надо так.
        out.append(mk(ctx, "AUTH-004", "UNKNOWN",
                      "Авторизация на сайте есть, но страница входа не обойдена — "
                      "способы входа не наблюдались",
                      [Evidence(kind="dom", detail="признак авторизации",
                                selector=p.get("slug", ""))
                       for p in login_pages[:3]],
                      source_note="открыть страницу входа и повторить сбор — "
                                  "без неё способ авторизации не наблюдается"))

    out.append(mk(ctx, "AUTH-006", "PASS" if allowed_ev else "NA",
                  "Используются российские провайдеры" if allowed_ev
                  else "Российские провайдеры не используются", allowed_ev[:4]))
    return out


@detector("trackers_jurisdiction")
def detect_trackers(ctx: Context) -> list[Finding]:
    sig = ctx.sig["trackers"]
    out: list[Finding] = []

    def collect(specs: list[dict[str, Any]]) -> dict[str, Evidence]:
        found: dict[str, Evidence] = {}
        for req in ctx.all_requests():
            host, path = host_of(req["url"]), urllib.parse.urlparse(req["url"]).path
            for spec in specs:
                if not match_host(host, spec):
                    continue
                if spec.get("paths") and not any(p in path for p in spec["paths"]):
                    continue
                key = f"{spec['vendor']}|{host}"
                found.setdefault(key, Evidence(
                    kind="request",
                    detail=f"{spec['vendor']} ({spec['country']}, {spec['kind']}) — {host}",
                    url=req["url"][:200]))
        return found

    foreign = collect(sig["foreign"])
    if ctx.degraded:
        out.append(mk(ctx, "CK-005", "UNKNOWN",
                      "Сбор шёл без рендера — сетевые запросы не наблюдались"))
    elif foreign:
        countries = sorted({e.detail.split("(")[1].split(",")[0] for e in foreign.values()})
        out.append(mk(ctx, "CK-005", "FAIL",
                      f"Иностранных трекеров: {len(foreign)}; юрисдикции: {', '.join(countries)}",
                      list(foreign.values())[:8]))
    else:
        out.append(mk(ctx, "CK-005", "PASS", "Иностранных трекеров не обнаружено"))

    infra = collect(sig["foreign_infra"])
    if ctx.degraded:
        out.append(mk(ctx, "CK-006", "UNKNOWN", "Сбор шёл без рендера"))
    elif infra:
        out.append(mk(ctx, "CK-006", "WARN",
                      f"Иностранные инфраструктурные подключения: {len(infra)}",
                      list(infra.values())[:6]))
    else:
        out.append(mk(ctx, "CK-006", "PASS", "Не обнаружено"))

    russian = collect(sig["russian"])
    if foreign and not ctx.degraded:
        out.append(mk(ctx, "PDN-009", "FAIL",
                      "Данные уходят в иностранную юрисдикцию; требуется отдельное "
                      "согласие на трансграничную передачу и уведомление РКН",
                      list(foreign.values())[:5], needs_llm=True))
    elif ctx.degraded:
        out.append(mk(ctx, "PDN-009", "UNKNOWN", "Сбор шёл без рендера"))
    else:
        out.append(mk(ctx, "PDN-009", "PASS",
                      "Иностранных получателей данных не обнаружено",
                      list(russian.values())[:4]))
    return out


@detector("forms_consent")
def detect_forms(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    forms: list[tuple[dict[str, Any], dict[str, Any]]] = []
    login_forms: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for page in ctx.pages:
        for form in page.get("forms") or []:
            fields = form.get("fields") or []
            # Форма поиска или подписки без ПДн под 152-ФЗ не подпадает.
            collects_pd = any(
                (f.get("type") in ("email", "tel"))
                or (f.get("name") or "").lower() in ("email", "phone", "tel", "name",
                                                     "fio", "surname", "firstname")
                or any(k in (f.get("placeholder") or "").lower()
                       for k in ("имя", "телефон", "e-mail", "email", "почта"))
                for f in fields)
            # Форма входа — не сбор по согласию. Основание обработки здесь
            # исполнение договора (п. 5 ч. 1 ст. 6 ФЗ-152), и требовать в ней
            # чекбокс «согласен на обработку» неверно: такой чекбокс в форме
            # входа не нужен ни по закону, ни по практике.
            if collects_pd and not looks_like_login_page(ctx, page):
                forms.append((page, form))
            elif collects_pd:
                login_forms.append((page, form))

    if ctx.degraded:
        for rid in ("PDN-004", "PDN-005", "PDN-006", "PDN-007"):
            out.append(mk(ctx, rid, "UNKNOWN",
                          "Без рендера состояние чекбоксов недостоверно"))
        return out

    if not forms:
        note = ("Найдены только формы входа и регистрации: там основание обработки — "
                "исполнение договора, а не согласие"
                if login_forms else "Форм сбора персональных данных не обнаружено")
        for rid in ("PDN-004", "PDN-005", "PDN-006", "PDN-007"):
            out.append(mk(ctx, rid, "NA", note))
        return out

    no_cb, prechecked, no_link, single_cb = [], [], [], []
    for page, form in forms:
        where = f"{page.get('slug')} {form.get('selector')}"
        checkboxes = [f for f in form.get("fields") or [] if f.get("type") == "checkbox"]
        if not checkboxes:
            no_cb.append(Evidence(kind="dom", detail="форма без чекбокса согласия",
                                  url=page.get("final_url"), selector=where))
            continue
        for cb in checkboxes:
            if cb.get("checked"):
                prechecked.append(Evidence(
                    kind="dom", detail="чекбокс отмечен по умолчанию", selector=where,
                    snippet=(cb.get("label_text") or "")[:120]))
            if not (cb.get("label_links") or []):
                no_link.append(Evidence(
                    kind="dom", detail="в подписи чекбокса нет ссылки на политику",
                    selector=where, snippet=(cb.get("label_text") or "")[:120]))
        if len(checkboxes) == 1:
            single_cb.append(Evidence(kind="dom", detail="в форме один чекбокс",
                                      selector=where,
                                      snippet=(checkboxes[0].get("label_text") or "")[:160]))

    out.append(mk(ctx, "PDN-004", "FAIL" if no_cb else "PASS",
                  f"Форм без чекбокса согласия: {len(no_cb)} из {len(forms)}"
                  if no_cb else f"Во всех {len(forms)} формах есть чекбокс согласия",
                  no_cb[:6]))
    # Если чекбоксов нет ни в одной форме, правилам о их состоянии проверять
    # нечего. PASS здесь означал бы «требование выполнено», что неверно:
    # нарушение уже зафиксировано правилом PDN-004, а тут просто нет предмета.
    any_checkbox = any(f.get("type") == "checkbox"
                       for _, form in forms for f in form.get("fields") or [])
    if not any_checkbox:
        out.append(mk(ctx, "PDN-005", "NA",
                      "Чекбоксов согласия в формах нет — предмет проверки отсутствует, "
                      "нарушение зафиксировано правилом PDN-004"))
        out.append(mk(ctx, "PDN-006", "NA",
                      "Чекбоксов согласия в формах нет — см. PDN-004"))
    else:
        out.append(mk(ctx, "PDN-005", "FAIL" if prechecked else "PASS",
                      f"Предотмеченных чекбоксов: {len(prechecked)}" if prechecked
                      else "Предотмеченных чекбоксов не найдено", prechecked[:6]))
        out.append(mk(ctx, "PDN-006", "FAIL" if no_link else "PASS",
                      f"Чекбоксов без ссылки на политику: {len(no_link)}" if no_link
                      else "В подписях чекбоксов есть ссылки на политику", no_link[:6]))
    if not any_checkbox:
        out.append(mk(ctx, "PDN-007", "NA", "Чекбоксов согласия нет — см. PDN-004"))
        return out
    out.append(mk(ctx, "PDN-007", "WARN" if single_cb else "PASS",
                  "Согласие одним чекбоксом — требуется проверить, не покрывает ли "
                  "оно заодно рекламную рассылку" if single_cb
                  else "Согласия разделены", single_cb[:6], needs_llm=bool(single_cb)))
    return out


@detector("cookie_banner")
def detect_banner(ctx: Context) -> list[Finding]:
    sig = ctx.sig["cookie_banner"]
    out: list[Finding] = []
    if ctx.degraded:
        return [mk(ctx, rid, "UNKNOWN", "Без рендера баннер не наблюдается")
                for rid in ("CK-001", "CK-002")]

    found = ctx.banner.get("found")
    candidates = ctx.banner.get("candidates") or []
    if not found:
        out.append(mk(ctx, "CK-001", "FAIL",
                      "Баннер согласия на cookie не обнаружен",
                      [Evidence(kind="dom", detail="на главной странице баннер не найден")]))
        out.append(mk(ctx, "CK-002", "NA", "Баннера нет"))
        return out

    top = candidates[0]
    ev = [Evidence(kind="dom", detail="баннер согласия", selector=top.get("selector"),
                   snippet=(top.get("text") or "")[:200])]
    out.append(mk(ctx, "CK-001", "PASS", "Баннер согласия обнаружен", ev))

    buttons = [b.get("text", "").lower() for b in top.get("buttons") or []]
    has_reject = any(any(r in b for r in sig["reject_texts"]) for b in buttons)
    out.append(mk(ctx, "CK-002", "PASS" if has_reject else "FAIL",
                  f"Кнопки баннера: {', '.join(b[:24] for b in buttons[:4])}",
                  ev, needs_llm=not has_reject))
    return out


@detector("consent_gating")
def detect_gating(ctx: Context) -> list[Finding]:
    """Грузятся ли трекеры до согласия — диф сетевых запросов двух проходов."""
    if ctx.degraded:
        return [mk(ctx, "CK-003", "UNKNOWN", "Без рендера диф проходов недоступен")]
    if not ctx.banner.get("found"):
        return [mk(ctx, "CK-003", "NA",
                   "Баннера нет — нарушение фиксируется правилом CK-001")]

    specs = ctx.sig["trackers"]["foreign"] + ctx.sig["trackers"]["russian"]
    before = ctx.net.get("before_consent") or []
    leaked: dict[str, Evidence] = {}
    for req in before:
        host, path = host_of(req["url"]), urllib.parse.urlparse(req["url"]).path
        for spec in specs:
            if spec.get("kind") in ("analytics", "ads", "session_recording") \
                    and match_host(host, spec) \
                    and (not spec.get("paths") or any(p in path for p in spec["paths"])):
                leaked.setdefault(host, Evidence(
                    kind="request",
                    detail=f"{spec['vendor']} загружен до взаимодействия с баннером",
                    url=req["url"][:200]))
    cookies_before = [c.get("name") for c in ctx.cookies.get("before_consent") or []
                      if c.get("name", "").lower() not in
                      ctx.sig["cookie_banner"]["technical_cookie_names"]]

    if leaked:
        ev = list(leaked.values())[:8]
        if cookies_before:
            ev.append(Evidence(kind="dom",
                               detail=f"cookie до согласия: {', '.join(cookies_before[:8])}"))
        return [mk(ctx, "CK-003", "FAIL",
                   f"До согласия загружаются трекеры: {len(leaked)}", ev)]
    return [mk(ctx, "CK-003", "PASS",
               "До согласия аналитические и рекламные трекеры не загружаются")]


# Поля, наличие которых делает форму сбором персональных данных. Поиск по
# сайту и фильтр каталога — тоже формы, но ничего о человеке не собирают.
PD_FIELD_TYPES = {"email", "tel", "password"}
PD_FIELD_HINTS = ("name", "fio", "имя", "фамил", "email", "mail", "почт", "phone",
                  "tel", "телефон", "address", "адрес", "birth", "дата рожд",
                  "passport", "паспорт", "inn", "инн")


def collects_personal_data(page: dict[str, Any]) -> bool:
    for form in page.get("forms") or []:
        for field in form.get("fields") or []:
            if (field.get("type") or "").lower() in PD_FIELD_TYPES:
                return True
            blob = " ".join(str(field.get(k) or "") for k in
                            ("name", "id", "placeholder", "label", "autocomplete")).lower()
            if any(hint in blob for hint in PD_FIELD_HINTS):
                return True
    return False


PRIVACY_URL_HINTS = ("privacy", "polic", "politik", "personal", "konfidenc")


def privacy_pages(ctx: Context) -> list[dict[str, Any]]:
    return [p for p in ctx.pages
            if p.get("status") == 200
            and any(h in (p.get("final_url") or p.get("url") or "").lower()
                    for h in PRIVACY_URL_HINTS)]


def privacy_documents(ctx: Context) -> list[dict[str, Any]]:
    return [d for d in ctx.documents
            if d.get("status") == 200
            and any(h in (d.get("url") or "").lower()
                    for h in PRIVACY_URL_HINTS + ("confidential",))]


@detector("documents")
def detect_documents(ctx: Context) -> list[Finding]:
    docs = ctx.sig["documents"]["privacy"]
    out: list[Finding] = []
    privacy_pages_found = privacy_pages(ctx)
    # Документ может быть не HTML-страницей, а PDF на CDN — на российских
    # корпоративных сайтах это обычное дело. Формат не влияет на исполнение
    # требования ч. 2 ст. 18.1: важно, что документ опубликован и доступен.
    doc_files = privacy_documents(ctx)
    if privacy_pages_found:
        page = privacy_pages_found[0]
        out.append(mk(ctx, "PDN-001", "PASS", "Политика обработки ПДн доступна",
                      [Evidence(kind="http", detail=f"HTTP {page.get('status')}",
                                url=page.get("final_url"))]))
    elif doc_files:
        doc = doc_files[0]
        is_pdf = "pdf" in (doc.get("content_type") or "").lower() or \
                 doc["url"].lower().endswith(".pdf")
        out.append(mk(ctx, "PDN-001", "PASS",
                      "Политика опубликована отдельным файлом"
                      + (" (PDF)" if is_pdf else ""),
                      [Evidence(kind="http",
                                detail=f"HTTP 200, {doc.get('content_type') or 'файл'}",
                                url=doc["url"])],
                      source_note="Содержимое файла не разбиралось: полноту политики "
                                  "(PDN-003) нужно проверить вручную" if is_pdf else None))
    else:
        tried = [p.get("url") for p in ctx.pages
                 if any(x in (p.get("url") or "") for x in docs["paths"])][:6]
        out.append(mk(ctx, "PDN-001", "FAIL",
                      "Страница политики обработки ПДн не найдена",
                      [Evidence(kind="http", detail="проверенные адреса: "
                                                    + ", ".join(t or "" for t in tried))]))

    # Закон требует обеспечить доступ к политике, а не поставить ссылку на
    # каждой странице. Значение имеет страница, где персональные данные
    # собираются: с неё пользователь должен дойти до политики до того, как
    # нажмёт «отправить». Страница без формы ничего не собирает, а сама
    # политика ссылки на себя не требует — считать это нарушением значит
    # выдавать претензию, которой нет в норме.
    checked = [p for p in ctx.pages if p.get("status") == 200]
    policy_slugs = {p.get("slug") for p in privacy_pages(ctx)}
    collecting = [p for p in checked
                  if p.get("slug") not in policy_slugs and collects_personal_data(p)]
    without = [p for p in collecting if not p.get("has_policy_link")]
    if not checked:
        out.append(mk(ctx, "PDN-002", "UNKNOWN", "Ни одна страница не открылась"))
    elif not collecting:
        out.append(mk(ctx, "PDN-002", "NA",
                      "Форм сбора персональных данных на обойдённых страницах нет — "
                      "требование о доступе к политике с таких страниц неприменимо"))
    elif without:
        out.append(mk(ctx, "PDN-002", "FAIL",
                      f"Страниц со сбором персональных данных без доступа к политике: "
                      f"{len(without)} из {len(collecting)}",
                      [Evidence(kind="dom", detail="форма есть, ссылки на политику нет",
                                url=p.get("final_url")) for p in without[:6]]))
    else:
        out.append(mk(ctx, "PDN-002", "PASS",
                      f"На всех {len(collecting)} страницах со сбором данных есть "
                      f"ссылка на политику"))
    return out


POLICY_URL_HINTS = ("privacy", "polic", "politik", "personal", "konfidenc",
                    "soglas", "oferta", "cookie")


def policy_texts(ctx: Context) -> dict[str, str]:
    """Тексты страниц с правовыми документами: slug -> текст.

    Несколько правил сравнивают фактическое поведение сайта с тем, что о нём
    написано. Сравнивать не с чем, если документ не разобран, и тогда вывод —
    UNKNOWN, а не «не описано».
    """
    out: dict[str, str] = {}
    for page in ctx.pages:
        url = (page.get("final_url") or page.get("url") or "").lower()
        slug = page.get("slug", "")
        if page.get("status") == 200 and any(h in url for h in POLICY_URL_HINTS):
            text = ctx.texts.get(slug)
            if text:
                out[slug] = text
    return out


RESPONSIBLE_RE = re.compile(
    r"ответственн\w*\s+(?:лиц\w+\s+)?за\s+(?:организацию\s+)?обработк\w+\s+"
    r"персональн\w+\s+данн\w+", re.I)
EMAIL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
PHONE_RE = re.compile(r"\+7[\s(\-]?\d{3}[\s)\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")


@detector("requisites")
def detect_requisites(ctx: Context) -> list[Finding]:
    sig = ctx.sig["requisites"]
    out: list[Finding] = []
    inns, ogrns, forms_found = [], [], []

    for slug, text in ctx.texts.items():
        low = text.lower()
        for m in re.finditer(sig["inn_pattern"], text):
            window = low[max(0, m.start() - 40):m.start()]
            if any(k in window for k in sig["inn_context"]) and valid_inn(m.group(1)):
                inns.append((slug, m.group(1)))
        for m in re.finditer(sig["ogrn_pattern"], text):
            window = low[max(0, m.start() - 40):m.start()]
            if any(k in window for k in sig["ogrn_context"]) and valid_ogrn(m.group(1)):
                ogrns.append((slug, m.group(1)))
        for lf in sig["legal_forms"]:
            if re.search(rf"\b{lf}\b", text):
                forms_found.append((slug, lf))
                break

    ev = ([Evidence(kind="text", detail=f"ИНН {v} (контрольная сумма верна)", selector=s)
           for s, v in inns[:3]]
          + [Evidence(kind="text", detail=f"ОГРН {v} (контрольная сумма верна)", selector=s)
             for s, v in ogrns[:3]])
    if inns and ogrns:
        out.append(mk(ctx, "ORG-001", "PASS", "ИНН и ОГРН найдены и валидны", ev))
    elif inns or ogrns:
        out.append(mk(ctx, "ORG-001", "WARN",
                      "Найден только один из идентификаторов", ev))
    else:
        out.append(mk(ctx, "ORG-001", "FAIL",
                      "ИНН и ОГРН не найдены либо не проходят проверку контрольной суммы"))

    out.append(mk(ctx, "ORG-002", "PASS" if forms_found else "FAIL",
                  "Организационно-правовая форма указана" if forms_found
                  else "Наименование с организационно-правовой формой не найдено",
                  [Evidence(kind="text", detail=f"форма: {lf}", selector=s)
                   for s, lf in forms_found[:3]]))
    # ORG-003: контакты ответственного за организацию обработки ПДн.
    # Организационно-правовая форма меняет применимость правила, поэтому её
    # приходится определить до вывода.
    sole_trader: list[Evidence] = []
    for slug, text in ctx.texts.items():
        low = text.lower()
        if re.search(r"\bогрнип\b", low) or re.search(
                r"\b(?:ип|индивидуальн\w+ предпринимател\w+)\b[\s,]+[А-ЯЁ]", text):
            sole_trader.append(Evidence(kind="text",
                                        detail="оператор — индивидуальный предприниматель",
                                        selector=slug))
            break
    responsible: list[Evidence] = []
    mentioned = False
    for slug, text in ctx.texts.items():
        for m in RESPONSIBLE_RE.finditer(text):
            mentioned = True
            window = text[m.start():m.end() + 400]
            contact = EMAIL_RE.search(window) or PHONE_RE.search(window)
            if contact:
                responsible.append(Evidence(
                    kind="text", detail=f"контакт рядом с упоминанием: {contact.group(0)}",
                    selector=slug, snippet=re.sub(r"\s+", " ", window[:200])))
    if sole_trader:
        # ст. 22.1 обязывает назначить ответственного оператора-юридическое лицо.
        # У индивидуального предпринимателя такой обязанности нет, и требовать с
        # него ФИО ответственного — придирка, которой нет в норме. Форма
        # оператора решает применимость правила, поэтому проверяется первой.
        out.append(mk(ctx, "ORG-003", "NA",
                      "Оператор — индивидуальный предприниматель: ст. 22.1 ФЗ-152 "
                      "обязывает назначать ответственного оператора-юридическое лицо",
                      sole_trader[:2]))
    elif responsible:
        out.append(mk(ctx, "ORG-003", "PASS",
                      "Указан ответственный за организацию обработки ПДн и его контакт",
                      responsible[:3]))
    elif mentioned:
        out.append(mk(ctx, "ORG-003", "FAIL",
                      "Ответственный за организацию обработки ПДн упомянут, но контакта "
                      "для обращений субъекта рядом нет"))
    elif policy_texts(ctx):
        out.append(mk(ctx, "ORG-003", "FAIL",
                      "В разобранных правовых документах нет ни ответственного за "
                      "организацию обработки ПДн, ни контакта для обращений субъекта"))
    elif not privacy_pages(ctx) and not privacy_documents(ctx):
        out.append(mk(ctx, "ORG-003", "FAIL",
                      "Политики обработки ПДн на сайте нет, контактов ответственного "
                      "за организацию обработки — тоже"))
    else:
        out.append(mk(ctx, "ORG-003", "UNKNOWN",
                      "Правовой документ опубликован файлом и не разобран — "
                      "проверять текст на упоминание ответственного не по чему"))

    ctx.inn = ctx.inn or (inns[0][1] if inns else None)
    return out


@detector("cookie_inventory")
def detect_cookie_inventory(ctx: Context) -> list[Finding]:
    """CK-004: описаны ли в политике те cookie, которые сайт реально ставит."""
    if ctx.degraded:
        return [mk(ctx, "CK-004", "UNKNOWN",
                   "Сбор шёл без рендера: какие cookie ставятся, не наблюдалось")]
    jar = {c.get("name"): c for phase in ("before_consent", "after_consent")
           for c in (ctx.cookies.get(phase) or []) if c.get("name")}
    if not jar:
        return [mk(ctx, "CK-004", "PASS", "Сайт не устанавливает cookie")]

    docs = policy_texts(ctx)
    listed = [Evidence(kind="cookie",
                       detail=f"{name} (домен {c.get('domain') or '—'})")
              for name, c in list(jar.items())[:12]]
    if not docs and not privacy_pages(ctx) and not privacy_documents(ctx):
        # Политики нет вовсе: перечень cookie не описан не «неизвестно где», а
        # нигде. Это вывод, а не пробел.
        return [mk(ctx, "CK-004", "FAIL",
                   f"Сайт ставит cookie ({len(jar)}), а политики, в которой их можно "
                   f"было бы описать, на сайте нет", listed)]
    if not docs:
        return [mk(ctx, "CK-004", "UNKNOWN",
                   f"Сайт ставит cookie ({len(jar)}), но текст политики не разобран "
                   f"(документ опубликован файлом) — сверить перечень не с чем",
                   listed)]

    joined = " ".join(docs.values()).lower()
    if not any(word in joined for word in ("cookie", "куки", "кук")):
        return [mk(ctx, "CK-004", "FAIL",
                   f"Сайт ставит cookie ({len(jar)}), а в правовых документах слово "
                   f"«cookie» не встречается", listed)]

    named = [name for name in jar if name.lower() in joined]
    return [mk(ctx, "CK-004", "UNKNOWN",
               f"Cookie описаны в документах в общем виде: из {len(jar)} фактических "
               f"имён в тексте встречается {len(named)}. Полноту перечня определяет "
               f"смысловой слой", listed, needs_llm=True)]


def valid_inn(value: str) -> bool:
    """Проверка контрольной суммы ИНН: отсекает телефоны и артикулы."""
    digits = [int(c) for c in value]
    if len(digits) == 10:
        w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return digits[9] == sum(a * b for a, b in zip(w, digits)) % 11 % 10
    if len(digits) == 12:
        w1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        return (digits[10] == sum(a * b for a, b in zip(w1, digits)) % 11 % 10
                and digits[11] == sum(a * b for a, b in zip(w2, digits)) % 11 % 10)
    return False


def valid_ogrn(value: str) -> bool:
    if len(value) == 13:
        return int(value[:12]) % 11 % 10 == int(value[12])
    if len(value) == 15:
        return int(value[:14]) % 13 % 10 == int(value[14])
    return False


@detector("rkn_operator_registry")
def detect_rkn_operator(ctx: Context) -> list[Finding]:
    """PDN-010: есть ли оператор в реестре РКН.

    Хост отвечает только с российских адресов. Недоступность — это UNKNOWN и
    указание, что делать, а не молчаливый PASS.
    """
    cfg = ctx.sig["rkn_operators"]
    if not ctx.inn:
        return [mk(ctx, "PDN-010", "UNKNOWN",
                   "ИНН на сайте не найден — проверить оператора в реестре не по чему")]
    url = cfg["search_url"].format(inn=ctx.inn)
    try:
        raw = reg.http_get(url, timeout=40)
    except Exception as exc:
        # Сообщение читает человек, который прокси ещё не настраивал. Название
        # переменной без команды, в которую её подставляют, ему ничего не даёт.
        return [mk(ctx, "PDN-010", "UNKNOWN",
                   f"Реестр операторов не ответил ({type(exc).__name__}): "
                   f"pd.rkn.gov.ru отвечает только с российских адресов",
                   [Evidence(kind="registry", detail="запрос к реестру", url=url)],
                   manual_check=(
                       "Проверить оператора вручную: открыть "
                       "https://pd.rkn.gov.ru/operators-registry/operators-list/ и "
                       f"ввести ИНН {ctx.inn} в поле «ИНН», нажать «Найти». Пустой "
                       "результат означает, что уведомление в РКН не подано.\n\n"
                       "Либо повторить автоматическую проверку через российский "
                       "выход. Прокси задаётся переменной окружения в той же "
                       "команде, отдельной настройки нет:\n\n"
                       "    PEPPER_RU_REGISTRY_PROXY=http://логин:пароль@адрес:порт \\\n"
                       "        python3 scripts/detect.py --artifacts artifacts/ "
                       f"--out findings.json --inn {ctx.inn}\n\n"
                       "Подойдёт любой HTTP-прокси с российским выходом — свой VPS "
                       "или VPN-шлюз. На сам обход сайта эта переменная не влияет: "
                       "она применяется только к запросам к госреестрам."))]
    text = reg.decode_best(raw)
    rows = [tr for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I)
            if re.search(cfg["row_marker_pattern"], reg.clean_html(tr))]
    if rows:
        cells = [reg.clean_html(c) for c in
                 re.findall(r"<td[^>]*>(.*?)</td>", rows[0], re.S | re.I)]
        cells = [c for c in cells if c]
        return [mk(ctx, "PDN-010", "PASS",
                   f"Оператор найден в реестре РКН (рег. номер {cells[0] if cells else '—'})",
                   [Evidence(kind="registry",
                             detail=" | ".join(c[:70] for c in cells[:3]), url=url)])]
    return [mk(ctx, "PDN-010", "FAIL",
               f"Оператор с ИНН {ctx.inn} в реестре РКН не найден",
               [Evidence(kind="registry", detail="поиск по ИНН вернул 0 записей", url=url)])]


@detector("registry_mentions")
def detect_mentions(ctx: Context) -> list[Finding]:
    """Упоминания лиц и организаций из госреестров."""
    # DISC-003 покрывает два реестра, и их результаты нельзя схлопывать в одну
    # строку: недоступность одного не должна маскироваться успехом другого.
    # Поэтому у правила две строки — и обе берут норму, санкцию и заголовок из
    # самого правила, дописывая, по какому списку шла проверка.
    plan = [("DISC-001", "DISC-001", "minjust_foreign_agents",
             "иностранного агента", None),
            ("DISC-003", "DISC-003", "minjust_extremist_orgs",
             "экстремистской организации", "перечень Минюста"),
            ("DISC-003", "DISC-003b", "fsb_terrorist_orgs",
             "террористической организации", "единый федеральный список ФСБ"),
            ("DISC-006", "DISC-006", "minjust_undesirable_orgs",
             "нежелательной организации", None),
            ("DISC-007", "DISC-007", "minjust_extremist_materials",
             "экстремистского материала", None)]
    out: list[Finding] = []
    for target_rule, display_id, key, what, scope in plan:
        produced = len(out)

        data = ctx.registry(key)
        if not data.entries:
            out.append(mk(ctx, target_rule, "UNKNOWN",
                          f"Реестр «{data.title or key}» недоступен: проверить упоминания "
                          f"нечем ({data.error or 'нет данных'})",
                          source_trust=data.source_trust))
            continue
        matcher = reg.RegistryMatcher(data)
        hits: list[Evidence] = []
        for slug, text in ctx.texts.items():
            for m in matcher.find(text)[:20]:
                hits.append(Evidence(
                    kind="text",
                    detail=f"[{m.confidence}] {m.entry_name[:90]}",
                    selector=slug, snippet=m.context[:200]))
        # Официальный источник позволяет утверждать отсутствие упоминаний;
        # зеркало — нет, поэтому чистый результат по нему остаётся WARN.
        trust = data.source_trust
        note = (f"источник: {trust}" + (f"; {data.error}" if data.error else ""))
        if hits:
            strong = [h for h in hits if not h.detail.startswith("[low]")]
            # Слабое совпадение — это чаще всего однословный псевдоним, попавший
            # в обычный текст. Поднимать по нему FAIL значит выдавать нарушение
            # там, где его нет; решение оставляем смысловому слою.
            if not strong:
                status = "WARN"
                text = (f"Найдены только слабые совпадения ({len(hits)}) — вероятны "
                        f"однословные совпадения с обычным текстом")
            elif trust in ("official", "attested"):
                status, text = "FAIL", (
                    f"Найдено упоминаний {what}: {len(strong)} уверенных из {len(hits)}. "
                    f"Требуется проверить наличие обязательной плашки")
            else:
                status, text = "WARN", (
                    f"Найдено упоминаний {what}: {len(strong)}; источник неофициальный")
            out.append(mk(ctx, target_rule, status, text,
                          (strong or hits)[:8],
                          needs_llm=True, source_trust=trust, source_note=note))
        elif trust in ("official", "attested"):
            out.append(mk(ctx, target_rule, "PASS", f"Упоминаний {what} не найдено",
                          source_trust=trust, source_note=note))
        else:
            out.append(mk(ctx, target_rule, "WARN",
                          f"Упоминаний {what} не найдено, но проверка шла по "
                          f"неофициальному источнику — отсутствие не гарантировано",
                          source_trust=trust, source_note=note))

        for finding in out[produced:]:
            finding.rule_id = display_id
            if scope:
                finding.title = f"{finding.title} ({scope})"
        if display_id == "DISC-001":
            out.extend(disclaimer_form_findings(ctx, out[produced:]))
    return out


def disclaimer_form_findings(ctx: Context, mentions: list[Finding]) -> list[Finding]:
    """DISC-002: форма плашки иноагента.

    Проверять форму плашки имеет смысл ровно тогда, когда есть что маркировать.
    Без упоминаний иноагента правило неприменимо — и говорить «не проверено», а
    тем более выдавать разработчику задачу «вынести плашку в начало материала»,
    значит требовать исправить то, чего на сайте нет.
    """
    hit = next((f for f in mentions if f.rule_id == "DISC-001"), None)
    if hit is None:
        return [mk(ctx, "DISC-002", "UNKNOWN",
                   "Упоминания иноагентов не проверялись — форму плашки проверять не по чему")]
    if hit.status in ("PASS", "NA"):
        return [mk(ctx, "DISC-002", "NA",
                   "Упоминаний иностранных агентов не найдено — требование к форме "
                   "плашки неприменимо")]
    if hit.status == "UNKNOWN":
        return [mk(ctx, "DISC-002", "UNKNOWN",
                   f"{hit.summary}. Пока не известно, есть ли упоминания, форму "
                   f"плашки проверять не по чему")]
    # Упоминания найдены: есть ли рядом плашка и той ли она формы — вопрос к
    # смысловому слою, у скрипта для этого нет ни разметки, ни размера шрифта.
    return [mk(ctx, "DISC-002", "UNKNOWN",
               "Упоминания найдены — проверить форму плашки (п. 4–14 Правил ПП 2108: "
               "перед материалом, шрифт вдвое крупнее основного, без сокращений)",
               hit.evidence and [Evidence(**{k: v for k, v in e.items()
                                             if k in ("kind", "detail", "url",
                                                      "selector", "snippet")})
                                 for e in hit.evidence[:3]] or None,
               needs_llm=True)]


@detector("meta_symbols")
def detect_meta(ctx: Context) -> list[Finding]:
    sig = ctx.sig["symbols"]
    out: list[Finding] = []
    sym: list[Evidence] = []
    for slug, dom in ctx.doms.items():
        low = dom.lower()
        for cls in sig["meta"]["css_classes"]:
            if cls in low:
                sym.append(Evidence(kind="dom", detail=f"иконка соцсети: {cls}",
                                    selector=slug))
                break
        for host in sig["meta"]["link_hosts"]:
            if f"//{host}" in low and not any(x in low for x in sig["excluded"]):
                sym.append(Evidence(kind="dom", detail=f"ссылка на {host}", selector=slug))
                break
    out.append(mk(ctx, "DISC-005", "FAIL" if sym else "PASS",
                  f"Признаков символики Meta: {len(sym)}" if sym
                  else "Иконок и ссылок Instagram/Facebook не обнаружено", sym[:6]))

    mentions: list[Evidence] = []
    for slug, text in ctx.texts.items():
        for word in ("Instagram", "Facebook", "Meta Platforms"):
            for m in re.finditer(rf"\b{re.escape(word)}\b", text, re.I):
                ctx_window = text[max(0, m.start() - 200): m.end() + 200]
                marked = re.search(r"экстремист|запрещен|запрещён", ctx_window, re.I)
                if not marked:
                    mentions.append(Evidence(
                        kind="text", detail=f"упоминание {word} без пометки",
                        selector=slug, snippet=ctx_window[:200]))
                break
    out.append(mk(ctx, "DISC-004", "FAIL" if mentions else "PASS",
                  f"Упоминаний без пометки: {len(mentions)}" if mentions
                  else "Упоминаний Meta без пометки не найдено",
                  mentions[:6], needs_llm=bool(mentions)))
    return out


@detector("infrastructure")
def detect_infra(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    http = ctx.infra.get("http") or {}
    tls = ctx.infra.get("tls") or {}
    if http.get("redirects_to_https") is True and not tls.get("error"):
        out.append(mk(ctx, "INF-001", "PASS",
                      f"HTTP уводит на HTTPS, {tls.get('protocol', 'TLS')}",
                      [Evidence(kind="infra", detail=f"redirect -> {http.get('final_url')}")]))
    elif http.get("redirects_to_https") is False:
        out.append(mk(ctx, "INF-001", "FAIL", "HTTP доступен без редиректа на HTTPS",
                      [Evidence(kind="infra", detail=str(http)[:180])]))
    else:
        out.append(mk(ctx, "INF-001", "UNKNOWN",
                      f"Проверить не удалось: {http.get('error') or tls.get('error') or 'нет данных'}"))

    geo = ctx.infra.get("geo") or []
    ru = [g for g in geo if g.get("country") == "RU"]
    ev = [Evidence(kind="infra", detail=f"{g.get('ip')} — {g.get('country')} {g.get('org','')}")
          for g in geo[:4]]
    if not geo:
        out.append(mk(ctx, "INF-002", "UNKNOWN", "Геоданные хостинга не получены"))
    elif ru:
        out.append(mk(ctx, "INF-002", "WARN",
                      "Хостинг в РФ; принадлежность провайдера реестру РКН требует "
                      "отдельной сверки, а DDoS-прокси маскирует реальный origin", ev))
    else:
        out.append(mk(ctx, "INF-002", "WARN",
                      f"Хостинг за пределами РФ: {', '.join(sorted({g.get('country') or '?' for g in geo}))}",
                      ev))

    # INF-004: единый реестр запрещённой информации в скилл не подключён.
    # Сказать об этом прямо — единственный честный вариант: молчание по пункту
    # читается как «совпадений нет», а это утверждение, которого никто не делал.
    host = ctx.infra.get("host") or urllib.parse.urlparse(ctx.target).hostname or "—"
    out.append(mk(ctx, "INF-004", "UNKNOWN",
                  "Машиночитаемого источника реестра нет — проверяется вручную",
                  [Evidence(kind="infra", detail=f"домен {host}",
                            url="https://eais.rkn.gov.ru/")]))
    return out


@detector("form_endpoints_geo")
def detect_endpoints(ctx: Context) -> list[Finding]:
    """PDN-011 и INF-003: куда уходят данные форм."""
    if ctx.degraded:
        return [mk(ctx, rid, "UNKNOWN", "Без рендера приёмники форм не наблюдаются")
                for rid in ("PDN-011", "INF-003")]
    posts: dict[str, Evidence] = {}
    # Встроенные плееры и CDN шлют POST-телеметрию, и считать её отправкой
    # персональных данных нельзя: правило про приёмники форм, а не про любой POST.
    media_specs = ctx.sig["trackers"]["foreign_infra"]
    media_hosts = {s["host"] for s in media_specs}
    media_patterns = ("googlevideo.com", "youtube.com", "ytimg.com", "vimeocdn.com",
                      "doubleclick.net", "google-analytics.com", "googletagmanager.com",
                      "googleapis.com", "gstatic.com")
    for req in ctx.all_requests():
        if req.get("method") != "POST":
            continue
        if req.get("resource_type") not in (None, "xhr", "fetch", "document", "other"):
            continue
        host = host_of(req["url"])
        if not host or first_party(req["url"], ctx.target):
            continue
        if host in media_hosts or any(p in host for p in media_patterns):
            continue
        posts.setdefault(host, Evidence(
            kind="request", detail=f"POST на сторонний хост {host}",
            url=req["url"][:200]))
    actions = [(p.get("slug"), f.get("action")) for p in ctx.pages
               for f in (p.get("forms") or [])
               if (f.get("action") or "").startswith("http")
               and not first_party(f["action"], ctx.target)]

    ev = list(posts.values())[:6] + [
        Evidence(kind="dom", detail=f"форма отправляется на {a}", selector=s)
        for s, a in actions[:4]]
    if ev:
        return [mk(ctx, "PDN-011", "WARN",
                   "Данные форм уходят на сторонние хосты — требуется подтвердить, "
                   "где происходит первичная запись ПДн", ev, needs_llm=True),
                mk(ctx, "INF-003", "FAIL", "Найдены сторонние приёмники данных", ev)]
    note = ("Формы отправляются через JS без атрибута action — приёмник определён "
            "по сетевым запросам") if any(
        (f.get("action") or "") in ("#", "", None)
        for p in ctx.pages for f in (p.get("forms") or [])) else ""
    return [mk(ctx, "PDN-011", "PASS",
               "Сторонних приёмников данных форм не обнаружено. " + note),
            mk(ctx, "INF-003", "PASS", "Все наблюдаемые приёмники — на домене сайта")]


# --- Сборка ------------------------------------------------------------------


# Правила, чей вывод целиком опирается на содержимое страниц. Если страниц нет,
# ни одно из них не имеет права на PASS: отсутствие данных — не отсутствие
# нарушения. Инфраструктурные правила (INF-001, INF-002) проверяются по DNS и
# TLS и остаются валидными даже при заблокированном обходе.
CONTENT_DEPENDENT_GROUPS = {"auth", "disclaim", "pdn", "cookie", "org"}
INFRA_SURVIVES_BLOCK = {"INF-001", "INF-002"}

# Утверждения об отсутствии: их сила зависит от охвата обхода.
ABSENCE_CLAIMS = {"DISC-001", "DISC-003", "DISC-003b", "DISC-004", "DISC-005",
                  "DISC-006", "DISC-007", "AUTH-001", "AUTH-002", "AUTH-003",
                  "CK-005", "CK-006"}


def ensure_complete(ctx: Context, findings: list[Finding]) -> list[Finding]:
    """Дописывает пункты, по которым детекторы промолчали.

    Пользователю обещан статус по каждому правилу, и молчание — худший способ
    его не дать: отсутствующая строка читается как «здесь всё в порядке».
    Правил без статуса быть не должно, даже когда сказать по существу нечего:
    правило со смысловой проверкой уходит смысловому слою, правило детектора,
    не давшего наблюдений, — в UNKNOWN с прямым указанием на пробел.
    """
    seen = {f.rule_id for f in findings}
    for rule_id, rule in ctx.rules.items():
        if rule_id in seen:
            continue
        check = rule.get("check")
        logic = rule.get("status_logic") or {}
        if check == "info_only":
            findings.append(mk(ctx, rule_id, "NA",
                               logic.get("NA") or "Справочный пункт, проверке не подлежит"))
        elif check == "llm":
            findings.append(mk(ctx, rule_id, "UNKNOWN",
                               "Пункт закрывается смысловым анализом документов и "
                               "содержимого — автоматической проверки для него нет",
                               needs_llm=True))
        else:
            findings.append(mk(ctx, rule_id, "UNKNOWN",
                               "Проверка не выполнена: наблюдений по этому правилу "
                               "не собрано — проверить вручную"))
    order = {rid: i for i, rid in enumerate(ctx.rules)}

    def position(finding: Finding) -> tuple[int, str]:
        # Подпункт («DISC-003b») сортируется по своему правилу, а не улетает
        # в конец списка, где читатель его не свяжет с DISC-003.
        base = re.match(r"^([A-Z]+-\d+)", finding.rule_id)
        return (order.get(base.group(1) if base else finding.rule_id, len(order)),
                finding.rule_id)

    findings.sort(key=position)
    return findings


def apply_coverage_gates(ctx: Context, findings: list[Finding]) -> list[Finding]:
    """Приводит выводы в соответствие с тем, сколько данных реально собрано."""
    if ctx.blocked or ctx.analysed == 0:
        reason = ("сайт заблокировал обход (антибот-защита): ни одна страница не "
                  "открылась, проверять нечего"
                  if ctx.blocked else "ни одна страница не открылась")
        for f in findings:
            if f.rule_id in INFRA_SURVIVES_BLOCK or f.group == "internal":
                continue
            if f.group in CONTENT_DEPENDENT_GROUPS or f.status in ("PASS", "FAIL"):
                f.status = "UNKNOWN"
                f.summary = f"Проверить не удалось: {reason}"
                f.evidence = []
                f.needs_llm = False
        return findings

    if ctx.thin_coverage:
        for f in findings:
            if f.status == "PASS" and f.rule_id in ABSENCE_CLAIMS:
                f.status = "WARN"
                f.summary = (f"{f.summary}. Обход охватил всего {ctx.analysed} "
                             f"страниц(ы) — вывод об отсутствии ограничен охватом "
                             f"и требует ручной проверки остальных разделов")
                f.needs_llm = True
    return findings


def run(ctx: Context) -> dict[str, Any]:
    findings: list[Finding] = []
    order = ["requisites", "auth_providers", "registry_mentions", "meta_symbols",
             "documents", "forms_consent", "cookie_banner", "consent_gating",
             "cookie_inventory", "trackers_jurisdiction", "form_endpoints_geo",
             "infrastructure", "rkn_operator_registry"]
    for name in order:
        try:
            findings.extend(DETECTORS[name](ctx))
        except Exception as exc:  # детектор не должен ронять весь прогон
            # Упавший детектор не должен уносить свои правила из отчёта:
            # исчезнувший пункт читается как «проверять было нечего», и именно
            # так неполная проверка выдаёт себя за полную. Каждое правило
            # детектора получает UNKNOWN с причиной.
            reason = f"Детектор {name} завершился ошибкой: {type(exc).__name__}: {exc}"
            print(f"  !! {reason}", file=sys.stderr)
            owned = [r for r in ctx.rules.values() if r.get("detector") == name]
            for rule in owned:
                findings.append(mk(ctx, rule["id"], "UNKNOWN", reason))
            if not owned:
                findings.append(Finding(
                    rule_id=f"detector:{name}", group="internal", title=name,
                    status="UNKNOWN", severity="info", summary=reason))

    findings = apply_coverage_gates(ctx, ensure_complete(ctx, findings))

    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    fails = [f for f in findings if f.status == "FAIL"]
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (0 if f.status == "FAIL" else
                                 1 if f.status == "WARN" else
                                 2 if f.status == "UNKNOWN" else 3,
                                 sev_order.get(f.severity, 9), f.rule_id))

    return {
        "schema_version": SCHEMA_VERSION,
        "target": ctx.target,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "degraded": ctx.degraded,
        "degraded_reason": ctx.manifest.get("degraded_reason"),
        "blocked": ctx.blocked,
        "thin_coverage": ctx.thin_coverage,
        "unvisited_links": ctx.unvisited_links,
        "pages_analysed": len([p for p in ctx.pages if p.get("status") == 200]),
        "registry_status": {
            key: {"origin": d.origin, "trust": d.source_trust,
                  "entries": len(d.entries), "stale_days": d.stale_days,
                  "error": d.error}
            for key, d in ctx._registries.items()},
        "stats": {"by_status": by_status, "fail_count": len(fails),
                  "needs_llm": sum(1 for f in findings if f.needs_llm)},
        "findings": [asdict(f) for f in findings],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Детекторы соответствия требованиям РФ")
    ap.add_argument("--artifacts", default="artifacts", help="каталог артефактов collect.py")
    ap.add_argument("--out", default="findings.json")
    ap.add_argument("--inn", default=None,
                    help="ИНН оператора, если на сайте он не указан")
    ap.add_argument("--proxy", default=None, help=f"прокси для реестров ({reg.PROXY_ENV})")
    args = ap.parse_args()

    if args.proxy:
        reg.set_proxy(args.proxy)

    ctx = Context(Path(args.artifacts).resolve(), inn=args.inn)
    report = run(ctx)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    st = report["stats"]["by_status"]
    print(f"Цель: {report['target']}", file=sys.stderr)
    print(f"Страниц проанализировано: {report['pages_analysed']}"
          + (" (режим degraded)" if report["degraded"] else ""), file=sys.stderr)
    for status in ("FAIL", "WARN", "UNKNOWN", "PASS", "NA"):
        if st.get(status):
            print(f"  {status:<8} {st[status]}", file=sys.stderr)
    print(f"Требуют смыслового анализа: {report['stats']['needs_llm']}", file=sys.stderr)
    print(f"Записано: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
