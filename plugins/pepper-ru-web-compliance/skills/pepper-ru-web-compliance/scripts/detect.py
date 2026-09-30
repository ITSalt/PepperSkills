#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
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
    uv run --no-project scripts/detect.py --artifacts artifacts/ --out findings.json
    uv run --no-project scripts/detect.py --artifacts artifacts/ --out findings.json --inn 7736207543
"""
from __future__ import annotations

import base64
import audit_transport as transport
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
from report_provenance import current_producer
from network_evidence import classify_request, request_context, safe_url
from review_contract import valid_action_review

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
            f"`uv run --no-project scripts/gen_checklist.py --write` на машине с PyYAML "
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
    context: dict[str, Any] | None = None


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
    rule_evidence: list[str] = field(default_factory=list)
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
    # Основание обработки проверяется отдельно от факта подключения сервиса.
    processing_basis: str | None = None
    basis_evidence: list[dict[str, Any]] = field(default_factory=list)
    basis_recommendation: str | None = None
    basis_status: str = "UNKNOWN"
    processing_activities: list[dict[str, Any]] = field(default_factory=list)
    semantic_review: dict[str, Any] | None = None


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
                    for phase in ("before_consent", "after_consent", "before_reject", "after_reject",
                                  "revisit_reject", "walk", "scenario")}
        # Активные сценарии (вход, корзина, модальные формы) и доразведка
        # (гео и вендоры получателей, внешние ссылки, документы, доступность из
        # РФ). Старые артефакты их не содержат — правила, которым эти факты
        # нужны, называют это технической причиной, а не просят проверить руками.
        self.scenarios: list[dict[str, Any]] = self.manifest.get("scenarios") or []
        self.has_scenarios = "scenarios" in self.manifest
        self.cookies = {phase: self._load_json(f"cookies/{phase}.json", [])
                        for phase in ("before_consent", "after_consent", "before_reject", "after_reject", "revisit_reject")}
        self._texts: dict[str, str] | None = None
        self._doms: dict[str, str] | None = None
        self._registries: dict[str, reg.RegistryData] = {}

    def enrich(self, name: str) -> dict[str, Any]:
        data = self._load_json(f"enrich/{name}.json", {})
        return data if isinstance(data, dict) else {}

    def scenario(self, name: str) -> dict[str, Any] | None:
        return next((s for s in self.scenarios if s.get("name") == name), None)

    def host_info(self, host: str) -> dict[str, Any]:
        return (self.enrich("hosts").get("hosts") or {}).get(host) or {}

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
            saved = self._load_json(f"registries/{key}.json", None)
            self._registries[key] = reg.RegistryData(**saved) if saved else reg.load_registry(
                key, offline=not (transport.ACTIVE or reg._proxy_url))
            if saved:
                self._registries[key].stale_days = reg.age_days(self._registries[key].fetched_at)
        return self._registries[key]


# --- Вспомогательное ---------------------------------------------------------


def registrable_domain(host: str) -> str:
    """Домен, который регистрируют: example.com для app.example.com."""
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
        fix_hint=extra.pop("fix_hint", None) or rule.get("fix_hint"),
        rule_evidence=rule.get("evidence") or [],
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
    login_pages = [p for p in ctx.pages
                   if p.get("scenario") == "auth" or looks_like_login_page(ctx, p)]
    has_auth = bool(login_pages)
    # «Маркеров нет» честно только тогда, когда интерфейс входа открывался:
    # кнопка «Войти через Google» живёт в модалке, которую обход страниц не видит.
    login_seen = login_form_observed(ctx)
    auth_scenario = ctx.scenario("auth") or {}
    unseen_reason = ("интерфейс входа не открылся при сборе"
                     + (f": сценарий входа — {auth_scenario.get('status')}"
                        + (f" ({auth_scenario.get('error')})" if auth_scenario.get("error") else "")
                        if auth_scenario else ": сценарий входа этим сборщиком не выполнялся"))

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
        if not ev and has_auth and not login_seen:
            out.append(mk(ctx, rule_id, "UNKNOWN", "На сайте есть вход, но " + unseen_reason,
                          [Evidence(kind="dom", detail="признак входа", selector=p.get("slug", ""))
                           for p in login_pages[:2]]))
        elif not ev:
            out.append(mk(ctx, rule_id, "PASS", "Иностранных провайдеров входа нет"
                          + (" в интерфейсе входа" if login_seen else "")))
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
    elif has_auth and not login_seen:
        out.append(mk(ctx, "AUTH-002", "UNKNOWN", "На сайте есть вход, но " + unseen_reason))
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

    network_allowed = [e for e in allowed_ev if e.kind == "request"]
    if not has_auth:
        out.append(mk(ctx, "AUTH-004", "NA", "Признаков авторизации на сайте не найдено"))
    elif not login_seen and not network_allowed:
        # Надпись «VK» в подвале — ссылка на сообщество, а не способ входа.
        # Без открытого интерфейса входа о способах входа сказать нечего.
        out.append(mk(ctx, "AUTH-004", "UNKNOWN", "Авторизация на сайте есть, но " + unseen_reason,
                      [Evidence(kind="dom", detail="признак авторизации", selector=p.get("slug", ""))
                       for p in login_pages[:3]]))
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
                      "Авторизация на сайте есть, но " + unseen_reason,
                      [Evidence(kind="dom", detail="признак авторизации",
                                selector=p.get("slug", ""))
                       for p in login_pages[:3]],
                      ))

    providers = [e for e in allowed_ev if "телефон" not in e.detail]
    out.append(mk(ctx, "AUTH-006", "PASS" if providers else "NA",
                  "Используются российские провайдеры входа" if providers
                  else "Российские провайдеры входа не используются", providers[:4]))
    return out


@detector("trackers_jurisdiction")
def detect_trackers(ctx: Context) -> list[Finding]:
    """CK-005, CK-006, PDN-009: кто получает данные посетителей и где он.

    Страна получателя берётся из сигнатуры вендора, а для хостов без сигнатуры —
    из доразведки (IP, ASN, RDAP). Вывод даётся по каждому получателю: «сторонние
    запросы есть, требуют квалификации» не отвечает ни на один вопрос владельца.
    """
    out: list[Finding] = []
    if ctx.degraded:
        return [mk(ctx, rid, "UNKNOWN", "Сбор шёл без рендера — сетевые запросы не наблюдались")
                for rid in ("CK-005", "CK-006", "PDN-009")]
    border = cross_border_declared(ctx)
    recipients = third_party_recipients(ctx)
    optional_kinds = ("analytics", "ads", "session_recording", "tagmanager")

    foreign_trackers = [r for r in recipients.values()
                        if r["country"] not in (None, "RU") and r["kind"] in optional_kinds]
    ev = [recipient_evidence(r) for r in foreign_trackers][:8]
    if not foreign_trackers:
        out.append(mk(ctx, "CK-005", "PASS", "Иностранных трекеров нет"))
    elif border == "declared":
        out.append(mk(ctx, "CK-005", "WARN",
                      f"Подключены иностранные трекеры: {names(foreign_trackers)}; "
                      "трансграничная передача в политике заявлена — нужно уведомление РКН по ст. 12",
                      ev, **basis_kwargs(ctx)))
    else:
        out.append(mk(ctx, "CK-005", "FAIL",
                      f"Подключены иностранные трекеры: {names(foreign_trackers)}; "
                      + ("политика прямо отрицает трансграничную передачу"
                         if border == "negated" else
                         "в политике нет сведений о трансграничной передаче"),
                      ev, **basis_kwargs(ctx)))

    infra = [r for r in recipients.values()
             if r["country"] not in (None, "RU") and r["kind"] not in optional_kinds]
    if infra:
        out.append(mk(ctx, "CK-006", "WARN",
                      f"Иностранные сервисы инфраструктуры получают IP посетителей: {names(infra)}",
                      [recipient_evidence(r) for r in infra][:6]))
    else:
        out.append(mk(ctx, "CK-006", "PASS", "Иностранных CDN, шрифтов и капч нет"))

    foreign = [r for r in recipients.values() if r["country"] not in (None, "RU")]
    unknown = [r for r in recipients.values() if r["country"] is None]
    russian = [r for r in recipients.values() if r["country"] == "RU"]
    if not recipients:
        out.append(mk(ctx, "PDN-009", "NA", "Сторонних получателей нет"))
    elif foreign:
        status = "WARN" if border == "declared" else "FAIL"
        out.append(mk(ctx, "PDN-009", status,
                      f"Иностранные получатели: {names(foreign)}; "
                      + ("трансграничная передача в политике заявлена, нужно уведомление РКН"
                         if status == "WARN" else "сведений о трансграничной передаче в политике нет"),
                      [recipient_evidence(r) for r in foreign][:8], **basis_kwargs(ctx)))
    elif unknown:
        out.append(mk(ctx, "PDN-009", "UNKNOWN",
                      f"Страна не определена для получателей: {names(unknown)} — "
                      "доразведка (IP, ASN, RDAP) в этом сборе не выполнялась",
                      [recipient_evidence(r) for r in unknown][:8]))
    else:
        out.append(mk(ctx, "PDN-009", "PASS",
                      f"Все сторонние получатели — российские: {names(russian)}",
                      [recipient_evidence(r) for r in russian][:8]))
    return out


def looks_like_login_form(ctx: Context, form: dict[str, Any]) -> bool:
    """Use this form's fields/action, never the page header or another form."""
    if any(f.get("type") == "password" for f in form.get("fields") or []):
        return True
    action = urllib.parse.urlparse(form.get("action") or "").path.lower()
    segments = set(re.split(r"[^a-z0-9]+", action))
    return bool(segments & set(ctx.sig["auth"]["login_context"]["url_segments"]))


CART_RE = re.compile(r"корзин|в корзину|купить|оформить заказ|basket|\bcart\b|add to cart", re.I)


def cart_present(ctx: Context) -> bool:
    """Есть ли на сайте покупка: ссылка на корзину или кнопка «В корзину»."""
    for page in ctx.pages:
        url = (page.get("final_url") or page.get("url") or "").lower()
        if re.search(r"korzin|/cart|basket|checkout|/order", url):
            return True
        if any(CART_RE.search(label) for label in clickable_labels(ctx.doms.get(page.get("slug", ""), ""))):
            return True
    return False


def unobserved_forms(ctx: Context) -> list[str]:
    """Формы, которые на сайте есть, но сбор до них не дошёл.

    Вывод «во всех формах есть чекбокс» по одной форме подписки — ложный PASS.
    Если сценарий входа или заказа был и не удался, это техническая причина и
    она называется прямо; если сценарий дошёл до формы, её поля уже в выборке.
    """
    missing = []
    auth = ctx.scenario("auth")
    if any(looks_like_login_page(ctx, p) for p in ctx.pages) and not login_form_observed(ctx):
        missing.append("вход и регистрация" + (f" (сценарий: {auth.get('status')})" if auth else ""))
    checkout = ctx.scenario("checkout")
    checkout_seen = any(p.get("scenario") == "checkout" and p.get("forms") for p in ctx.pages)
    if cart_present(ctx) and not checkout_seen:
        missing.append("оформление заказа" + (f" (сценарий: {checkout.get('status')})" if checkout else ""))
    return missing


def login_form_observed(ctx: Context) -> bool:
    """Интерфейс входа действительно наблюдался: форма с полем логина."""
    for page in ctx.pages:
        in_login = page.get("scenario") == "auth" or looks_like_login_page(ctx, page)
        for form in page.get("forms") or []:
            types = {(f.get("type") or "").lower() for f in form.get("fields") or []}
            if "password" in types or (in_login and types & {"tel", "email"}
                                       and (page.get("scenario") == "auth" or looks_like_login_form(ctx, form))):
                return True
    return False


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
            # Login links or widgets elsewhere on the page do not classify this form.
            if collects_pd and not looks_like_login_form(ctx, form) and page.get("scenario") != "auth":
                forms.append((page, form))
            elif collects_pd:
                login_forms.append((page, form))

    if ctx.degraded:
        for rid in ("PDN-004", "PDN-005", "PDN-006", "PDN-007"):
            out.append(mk(ctx, rid, "UNKNOWN",
                          "Без рендера состояние чекбоксов недостоверно"))
        return out

    if not forms:
        note = ("Найдены только формы авторизации; основание обработки проверяется отдельно в PDN-013"
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

    # Формы, до которых сбор не дошёл: PASS по одной форме подписки был бы
    # утверждением о формах, которых никто не видел.
    unseen = unobserved_forms(ctx)
    if unseen and not no_cb:
        distinct = {(f.get("selector"), tuple(x.get("name") for x in f.get("fields") or [])) for _, f in forms}
        note = (f"Проверено разных форм: {len(distinct)}; не наблюдались: {', '.join(unseen)}")
        out.append(mk(ctx, "PDN-004", "UNKNOWN", note + ". В наблюдавшихся формах чекбокс согласия есть"))
        out.append(mk(ctx, "PDN-005", "FAIL" if prechecked else "UNKNOWN",
                      f"Предотмеченных чекбоксов: {len(prechecked)}" if prechecked
                      else note + ". В наблюдавшихся формах предотмеченных чекбоксов нет", prechecked[:6]))
        out.append(mk(ctx, "PDN-006", "FAIL" if no_link else "UNKNOWN",
                      f"Чекбоксов без ссылки на политику: {len(no_link)}" if no_link
                      else note + ". В наблюдавшихся формах ссылка на политику есть", no_link[:6]))
        out.append(advertising_consent(ctx, single_cb))
        return out
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
    out.append(advertising_consent(ctx, single_cb))
    return out


AD_RE = re.compile(r"рассылк|реклам|новост|акци|спецпредложени|маркетинг|newsletter", re.I)
PD_RE = re.compile(r"политик|персональн|обработк|конфиденциальн", re.I)


def advertising_consent(ctx: Context, single_cb: list[Evidence]) -> Finding:
    """PDN-007: рекламное согласие не должно ехать в одном чекбоксе с обработкой ПДн.

    Один чекбокс «Согласен с политикой» в форме заказа — нормальная форма: о
    рекламе в нём нет ни слова. Нарушение — когда одна галочка покрывает и
    обработку данных, и рассылку.
    """
    merged = [e for e in single_cb if AD_RE.search(e.snippet or "") and PD_RE.search(e.snippet or "")]
    if merged:
        return mk(ctx, "PDN-007", "FAIL",
                  f"Одним чекбоксом собирается согласие и на обработку данных, и на рекламу: {len(merged)}",
                  merged[:6], fix_hint="Разделить чекбокс на два: согласие на обработку данных и "
                                       "отдельное необязательное согласие на рекламную рассылку.")
    return mk(ctx, "PDN-007", "PASS", "Согласие на рекламу не совмещено с согласием на обработку данных")


@detector("cookie_banner")
def detect_banner(ctx: Context) -> list[Finding]:
    """CK-001, CK-002, CK-007: есть ли выбор и честен ли он.

    Основание аналитики — не повод откладывать вывод. Нет баннера, аналитика
    работает с первого визита, а в документах не заявлено ни согласие, ни
    законный интерес, — основания нет ни в каком виде: это нарушение. Если
    законный интерес заявлен, это риск, и его применимость проверяет LI-001.
    """
    sig = ctx.sig["cookie_banner"]
    out: list[Finding] = []
    if ctx.degraded:
        return [mk(ctx, rid, "UNKNOWN", "Без рендера баннер не наблюдается")
                for rid in ("CK-001", "CK-002", "CK-007")]

    found = ctx.banner.get("found")
    candidates = ctx.banner.get("candidates") or []
    basis = basis_kwargs(ctx)
    declared = declared_bases(ctx)
    services = optional_services(ctx, ("before_consent",)) or optional_services(ctx)
    service_ev = [recipient_evidence(r) for r in services.values()][:8]
    if not found:
        ev = [Evidence(kind="dom", detail="баннер согласия на главной странице не найден")] + service_ev
        if not services:
            out.append(mk(ctx, "CK-001", "NA",
                          "Баннера нет, и необязательной аналитики нет — согласие не требуется", ev[:1], **basis))
        elif declared["legitimate_interest"]:
            out.append(mk(ctx, "CK-001", "WARN",
                          f"Баннера нет; аналитика ({names(services.values())}) работает с первого "
                          "визита по заявленному законному интересу — применимость в LI-001",
                          ev + declared["evidence"][:2], **basis))
        elif declared["consent"]:
            out.append(mk(ctx, "CK-001", "FAIL",
                          f"Политика заявляет обработку по согласию, но согласие не запрашивается: "
                          f"баннера нет, аналитика ({names(services.values())}) работает с первого визита",
                          ev + declared["evidence"][:2], **basis))
        else:
            out.append(mk(ctx, "CK-001", "FAIL",
                          f"Баннера нет, аналитика и реклама ({names(services.values())}) работают с "
                          "первого визита; ни согласие, ни законный интерес в документах не заявлены",
                          ev, **basis))
        out.append(mk(ctx, "CK-002", "NA", "Баннера нет — отказываться не от чего"))
        out.append(mk(ctx, "CK-007", "NA", "Баннера нет — выбора, который можно затруднить, не предлагается"))
        return out

    if not candidates:
        return [mk(ctx, rid, "UNKNOWN", "Баннер отмечен, но его текст не сохранён")
                for rid in ("CK-001", "CK-002", "CK-007")]
    top = candidates[0]
    ev = [Evidence(kind="dom", detail="уведомление о cookie", selector=top.get("selector"),
                   snippet=(top.get("text") or "")[:300])]
    buttons = [b.get("text", "").lower() for b in top.get("buttons") or []]
    low = (top.get("text") or "").lower()
    explicit_consent = any(re.search(r"соглас|принять|разрешить|accept|allow", b)
                           for b in buttons)
    necessary_only = bool(re.search(r"только (?:строго )?(?:необходим|техническ)", low))
    if necessary_only and not explicit_consent and not services:
        out.append(mk(ctx, "CK-001", "NA", "Информационное уведомление о необходимых cookie", ev))
        out.append(mk(ctx, "CK-002", "NA", "Запроса согласия нет — кнопка отказа не нужна", ev))
        out.append(mk(ctx, "CK-007", "NA", "Запроса согласия нет", ev))
        return out
    if not explicit_consent:
        # Уведомление «Мы используем cookie. [Понятно]» при работающей
        # аналитике — не запрос согласия: выбора нет, есть только информирование.
        if not services:
            out.append(mk(ctx, "CK-001", "NA", "Уведомление о cookie; необязательной аналитики нет", ev))
        elif declared["legitimate_interest"]:
            out.append(mk(ctx, "CK-001", "WARN",
                          "Уведомление без выбора, аналитика работает по заявленному законному интересу — "
                          "применимость в LI-001", ev + service_ev, **basis))
        else:
            out.append(mk(ctx, "CK-001", "FAIL",
                          f"Уведомление о cookie без выбора: кнопки согласия и отказа нет, аналитика "
                          f"({names(services.values())}) работает, законный интерес не заявлен",
                          ev + service_ev, **basis))
        out.append(mk(ctx, "CK-002", "WARN" if services else "NA",
                      "Отказаться от аналитики в уведомлении нельзя" if services
                      else "Запроса согласия нет", ev))
        out.append(mk(ctx, "CK-007", "NA", "Запроса согласия нет — есть только уведомление", ev))
        return out

    out.append(mk(ctx, "CK-001", "PASS", "Запрос согласия отображается", ev))
    direct_reject = [b for b in buttons if any(r in b for r in sig["reject_texts"])
                     and not re.search(r"настро|управлен|параметр", b)]
    settings_only = [b for b in buttons if re.search(r"настро|управлен|параметр", b)]
    has_reject = bool(direct_reject or settings_only)
    out.append(mk(ctx, "CK-002", "PASS" if has_reject else "WARN",
                  "Кнопка отказа есть" + (f": «{(direct_reject or settings_only)[0]}»" if has_reject else "")
                  if has_reject else "В баннере нет кнопки отказа — только согласие", ev))
    if direct_reject:
        out.append(mk(ctx, "CK-007", "PASS", "Отказ доступен на первом экране наравне с согласием", ev))
    else:
        out.append(mk(ctx, "CK-007", "WARN",
                      "На первом экране баннера только «Принять»; отказ "
                      + ("спрятан в настройках" if settings_only else "не предусмотрен"), ev))
    return out


@detector("consent_gating")
def detect_gating(ctx: Context) -> list[Finding]:
    """CK-003: что грузится до выбора пользователя — по журналу первого визита."""
    if ctx.degraded:
        return [mk(ctx, "CK-003", "UNKNOWN", "Без рендера сетевой журнал первого визита недоступен")]
    declared = declared_bases(ctx)
    # Без баннера выбора нет ни в одном проходе: всё, что грузится, грузится
    # до выбора. С баннером смотрим только журнал до клика.
    leaked = optional_services(ctx, ("before_consent",) if ctx.banner.get("found") else None)
    cookies_before = [c.get("name") for c in ctx.cookies.get("before_consent") or []
                      if c.get("name", "").lower() not in
                      ctx.sig["cookie_banner"]["technical_cookie_names"]]
    if not leaked:
        if not optional_services(ctx):
            return [mk(ctx, "CK-003", "NA", "Необязательной аналитики нет")]
        return [mk(ctx, "CK-003", "PASS", "До выбора пользователя аналитика и реклама не загружаются")]
    ev = [recipient_evidence(r) for r in leaked.values()][:8]
    if cookies_before:
        ev.append(Evidence(kind="cookie", detail="cookie до выбора: " + ", ".join(cookies_before[:12])))
    where = "до выбора в баннере" if ctx.banner.get("found") else "при первом визите (баннера нет)"
    if declared["legitimate_interest"]:
        return [mk(ctx, "CK-003", "WARN",
                   f"{names(leaked.values())} загружаются {where}; для аналитики заявлен законный "
                   "интерес — применимость в LI-001", ev, **basis_kwargs(ctx))]
    return [mk(ctx, "CK-003", "FAIL",
               f"{names(leaked.values())} загружаются {where}, законный интерес для них не заявлен",
               ev, **basis_kwargs(ctx))]


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
            and first_party(p.get("final_url") or p.get("url") or "", ctx.target)
            and any(h in (p.get("final_url") or p.get("url") or "").lower()
                    for h in PRIVACY_URL_HINTS)]


def privacy_documents(ctx: Context) -> list[dict[str, Any]]:
    return [d for d in ctx.documents
            if d.get("status") == 200
            and first_party(d.get("final_url") or d.get("url") or "", ctx.target)
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
    elif any(d.get("status") == 200 and any(h in (d.get("final_url") or d.get("url") or "").lower()
             for h in PRIVACY_URL_HINTS) for d in ctx.pages + ctx.documents):
        out.append(mk(ctx, "PDN-001", "UNKNOWN",
                      "Найден документ на стороннем домене; принадлежность оператору не подтверждена",
                      needs_llm=True))
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
        if page.get("status") == 200 and first_party(url, ctx.target) and any(h in url for h in POLICY_URL_HINTS):
            text = ctx.texts.get(slug)
            if text:
                out[slug] = text
    return out


def basis_kwargs(ctx: Context) -> dict[str, Any]:
    """Declarations are candidates scoped to an observed service and purpose.

    A document sentence can support a declaration, never its legal validity.
    Ambiguous, negative and multi-purpose clauses stay UNKNOWN.
    """
    from processing_basis import classify_activities
    docs = [(ctx.page_by_slug(slug).get("final_url") or
             ctx.page_by_slug(slug).get("url") or slug, text)
            for slug, text in policy_texts(ctx).items()]
    specs = ctx.sig["trackers"]["foreign"] + ctx.sig["trackers"]["russian"]
    observed = []
    for spec in specs:
        if spec.get("kind") not in ("analytics", "ads", "session_recording"):
            continue
        requests = [r for r in ctx.all_requests() if match_host(host_of(r["url"]), spec)
                    and (not spec.get("paths") or any(p in urllib.parse.urlparse(r["url"]).path
                                                     for p in spec["paths"]))]
        if requests:
            observed.append({"service": spec["vendor"], "purpose": spec["kind"],
                             "requests": list(dict.fromkeys(r["url"] for r in requests))[:8]})
    activities = classify_activities(docs, observed)
    values = {a["declared_basis"] for a in activities}
    basis = next(iter(values)) if len(values) == 1 else "UNKNOWN"
    evidence = [e for a in activities for e in a["evidence"]]
    return {"processing_basis": basis, "basis_status": "UNVERIFIED",
            "processing_activities": activities, "basis_evidence": evidence,
            "basis_recommendation": "Подтвердить основание отдельно для каждого сервиса и цели. "
                "Декларация не подтверждает законность; проверить состав данных, необходимость, "
                "минимизацию, баланс интересов и фактический отказ, если выбран законный интерес."}


def optional_tracking_observed(ctx: Context) -> bool:
    """Whether collected evidence contains analytics, ads, or session replay."""
    return bool(optional_services(ctx))


OPTIONAL_KINDS = ("analytics", "ads", "session_recording")


def tracker_spec(ctx: Context, url: str) -> dict[str, Any] | None:
    host, path = host_of(url), urllib.parse.urlparse(url).path
    for spec in (ctx.sig["trackers"]["foreign"] + ctx.sig["trackers"]["foreign_infra"]
                 + ctx.sig["trackers"]["russian"]):
        if match_host(host, spec) and (not spec.get("paths") or any(p in path for p in spec["paths"])):
            return spec
    return None


def third_party_recipients(ctx: Context, phases: tuple[str, ...] | None = None) -> dict[str, dict[str, Any]]:
    """Сторонние получатели: вендор, страна, назначение, хосты и примеры адресов.

    Ключ — вендор, если он известен по сигнатуре или доразведке, иначе
    регистрируемый домен: два хоста одного сервиса — один получатель.
    """
    out: dict[str, dict[str, Any]] = {}
    for phase, rows in ctx.net.items():
        if phases and phase not in phases:
            continue
        for req in rows:
            url = req.get("url") or ""
            host = host_of(url)
            if not host or first_party(url, ctx.target):
                continue
            spec = tracker_spec(ctx, url)
            info = ctx.host_info(host) or ctx.host_info(registrable_domain(host))
            if not spec and info.get("vendor"):
                # Вендор найден доразведкой (по коду скрипта или RDAP): страна и
                # назначение берутся из сигнатуры того же вендора, если она есть.
                spec = next((s for s in ctx.sig["trackers"]["foreign"] + ctx.sig["trackers"]["russian"]
                             if s["vendor"].lower() == info["vendor"].lower()), None)
            vendor = (spec or {}).get("vendor") or info.get("vendor")
            country = (spec or {}).get("country") or info.get("country")
            kind = (spec or {}).get("kind") or info.get("kind") or "unknown"
            key = vendor or registrable_domain(host)
            item = out.setdefault(key, {"name": vendor or registrable_domain(host), "vendor": vendor,
                                        "country": country, "kind": kind, "hosts": [], "urls": [],
                                        "phases": [], "asn": info.get("asn"), "org": info.get("org")})
            if item["country"] is None and country:
                item["country"] = country
            if item["kind"] == "unknown" and kind != "unknown":
                item["kind"] = kind
            if host not in item["hosts"]:
                item["hosts"].append(host)
            if len(item["urls"]) < 3 and safe_url(url) not in item["urls"]:
                item["urls"].append(safe_url(url))
            if phase not in item["phases"]:
                item["phases"].append(phase)
    return out


def optional_services(ctx: Context, phases: tuple[str, ...] | None = None) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in third_party_recipients(ctx, phases).items() if v["kind"] in OPTIONAL_KINDS}


def names(items) -> str:
    items = list(items)
    return ", ".join(i["name"] for i in items[:8]) + (f" и ещё {len(items) - 8}" if len(items) > 8 else "")


def recipient_evidence(r: dict[str, Any]) -> Evidence:
    where = r["country"] or "страна не установлена"
    net = f"; сеть {r['asn']} {r['org']}" if r.get("asn") or r.get("org") else ""
    kind = {"analytics": "аналитика", "ads": "реклама", "session_recording": "запись сессий",
            "tagmanager": "менеджер тегов", "fonts": "шрифты", "captcha": "капча", "cdn": "CDN",
            "embed": "встроенное видео", "support": "чат поддержки", "errors": "сбор ошибок"}.get(
                r["kind"], "назначение по адресу не определено")
    return Evidence(kind="request", detail=f"{r['name']} — {kind}, {where}{net}; хосты: "
                    + ", ".join(r["hosts"][:4]), url=(r["urls"] or [None])[0])


def legal_corpus(ctx: Context, privacy_only: bool = False) -> dict[str, str]:
    """Тексты правовых документов: страницы сайта и извлечённые файлы доразведки."""
    texts = dict(policy_texts(ctx))
    if privacy_only:
        slugs = {p.get("slug") for p in privacy_pages(ctx)}
        texts = {k: v for k, v in texts.items() if k in slugs} or texts
    for doc in ctx.enrich("documents").get("documents") or []:
        rel = doc.get("text_path")
        if not rel or doc.get("extraction") == "failed":
            continue
        path = ctx.dir / "enrich" / rel if not rel.startswith("enrich/") else ctx.dir / rel
        url = (doc.get("url") or "").lower()
        if privacy_only and not any(h in url for h in PRIVACY_URL_HINTS + ("confidential",)):
            continue
        if path.exists():
            texts["doc:" + (doc.get("url") or rel)] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def sentences_with(text: str, pattern: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n+", text)
            if re.search(pattern, s, re.I)]


def declared_bases(ctx: Context) -> dict[str, Any]:
    """Заявленные в документах основания для аналитики и рекламы.

    Нужна не юридическая оценка, а факт: написал ли оператор хоть где-то, что
    аналитика идёт по согласию или по законному интересу. «Ничего не заявлено»
    — это вывод, а не пробел.
    """
    li, consent, ev = False, False, []
    for slug, text in legal_corpus(ctx).items():
        for s in sentences_with(text, r"законн\w* интерес"):
            if re.search(r"аналитик|статистик|cookie|куки|метрик|реклам|маркетинг", s, re.I):
                li = True
                ev.append(Evidence(kind="text", detail="заявлен законный интерес", selector=slug,
                                   snippet=s[:240]))
                break
        for s in sentences_with(text, r"(?:cookie|куки|аналитик|метрик)[^.]{0,120}соглас|соглас[^.]{0,120}(?:cookie|куки|аналитик|метрик)"):
            consent = True
            ev.append(Evidence(kind="text", detail="заявлено согласие на cookie или аналитику",
                               selector=slug, snippet=s[:240]))
            break
    for activity in basis_kwargs(ctx)["processing_activities"]:
        if activity["declared_basis"] == "legitimate_interest_declared":
            li = True
        if activity["declared_basis"] == "consent_declared":
            consent = True
    return {"legitimate_interest": li, "consent": consent, "evidence": ev}


def cross_border_declared(ctx: Context) -> str:
    """declared | negated | absent — что политика говорит о трансграничной передаче."""
    found = "absent"
    for text in legal_corpus(ctx).values():
        for s in sentences_with(text, r"трансграничн"):
            if re.search(r"\bне\s+(?:осуществля|производ|вед[её]т|планиру|передаёт|передает)\w*", s, re.I):
                found = "negated" if found == "absent" else found
            else:
                return "declared"
    return found


@detector("legitimate_interest")
def detect_legitimate_interest(ctx: Context) -> list[Finding]:
    """LI-001: законный интерес — только если его заявили, и только с работающим отказом."""
    if ctx.degraded or ctx.blocked:
        return [mk(ctx, "LI-001", "UNKNOWN", "Нет браузерных доказательств для проверки аналитики")]
    services = optional_services(ctx)
    if not services:
        return [mk(ctx, "LI-001", "NA", "Необязательной аналитики нет")]
    declared = declared_bases(ctx)
    basis = basis_kwargs(ctx)
    if not declared["legitimate_interest"]:
        return [mk(ctx, "LI-001", "NA",
                   "Законный интерес в документах не заявлен — основание аналитики оценено в CK-001",
                   **basis)]
    refusal = ctx.manifest.get("refusal") or {}
    after = optional_services(ctx, ("after_reject", "revisit_reject"))
    objection = []
    for slug, text in legal_corpus(ctx).items():
        for s in sentences_with(text, r"возраж|отказ\w*[^.]{0,60}(?:аналитик|метрик|cookie)|opt-?out"):
            objection.append(Evidence(kind="text", detail="порядок возражения", selector=slug, snippet=s[:240]))
            break
    ev = declared["evidence"][:2] + objection[:2]
    if refusal.get("click_status") == "clicked" and refusal.get("revisit_completed") and not after:
        return [mk(ctx, "LI-001", "PASS",
                   "Законный интерес заявлен; после отказа и повторного визита аналитика не загружается",
                   ev, needs_llm=True, **basis)]
    if after:
        return [mk(ctx, "LI-001", "WARN",
                   f"Законный интерес заявлен, но после отказа продолжают загружаться: {names(after.values())}",
                   ev + [recipient_evidence(r) for r in after.values()][:4], **basis)]
    if objection:
        return [mk(ctx, "LI-001", "WARN",
                   "Законный интерес заявлен, возражение описано только текстом; кнопки отказа на сайте нет",
                   ev, needs_llm=True, **basis)]
    return [mk(ctx, "LI-001", "WARN",
               "Законный интерес заявлен, но способа возразить против аналитики на сайте нет",
               ev, **basis)]


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
    mentions: list[Evidence] = []
    for slug, text in ctx.texts.items():
        for m in RESPONSIBLE_RE.finditer(text):
            mentioned = True
            if len(mentions) < 2:
                mentions.append(Evidence(kind="text", detail="упоминание ответственного без контакта",
                                         selector=slug,
                                         snippet=re.sub(r"\s+", " ", text[max(0, m.start() - 60):m.end() + 120])))
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
                      "для обращений субъекта рядом нет", mentions,
                      fix_hint="Указать в политике рядом с упоминанием ответственного его ФИО или "
                               "должность и контакт для обращений субъектов: почту или телефон."))
    elif policy_texts(ctx):
        out.append(mk(ctx, "ORG-003", "FAIL",
                      "В разобранных правовых документах нет ни ответственного за "
                      "организацию обработки ПДн, ни контакта для обращений субъекта",
                      [Evidence(kind="text", detail="проверенные документы: " + ", ".join(policy_texts(ctx)))]))
    elif not privacy_pages(ctx) and not privacy_documents(ctx):
        out.append(mk(ctx, "ORG-003", "FAIL",
                      "Политики обработки ПДн на сайте нет, контактов ответственного "
                      "за организацию обработки — тоже",
                      [Evidence(kind="text", detail="обойдено страниц: " + str(len(ctx.pages)))]))
    else:
        out.append(mk(ctx, "ORG-003", "UNKNOWN",
                      "Правовой документ опубликован файлом и не разобран — "
                      "проверять текст на упоминание ответственного не по чему"))

    ctx.inn = ctx.inn or (inns[0][1] if inns else None)
    return out


@detector("cookie_inventory")
def detect_cookie_inventory(ctx: Context) -> list[Finding]:
    """CK-004: какие cookie сайт реально ставит и какие из них названы в документах."""
    if ctx.degraded:
        return [mk(ctx, "CK-004", "UNKNOWN",
                   "Сбор шёл без рендера: какие cookie ставятся, не наблюдалось")]
    jar = {c.get("name"): c for phase in ("before_consent", "after_consent")
           for c in (ctx.cookies.get(phase) or []) if c.get("name")}
    if not jar:
        return [mk(ctx, "CK-004", "PASS", "Сайт не устанавливает cookie")]

    docs = legal_corpus(ctx)
    if not docs and not privacy_pages(ctx) and not privacy_documents(ctx):
        return [mk(ctx, "CK-004", "FAIL",
                   f"Сайт ставит cookie ({len(jar)}), а политики, в которой их можно "
                   f"было бы описать, на сайте нет", cookie_list_evidence(jar, list(jar)))]
    if not docs:
        return [mk(ctx, "CK-004", "UNKNOWN",
                   f"Сайт ставит cookie ({len(jar)}), но текст политики не извлечён из файла",
                   cookie_list_evidence(jar, list(jar)))]
    joined = " ".join(docs.values()).lower()
    if not re.search(r"cookie|куки|кук-", joined):
        return [mk(ctx, "CK-004", "FAIL",
                   f"Сайт ставит cookie ({len(jar)}), а в правовых документах cookie не упоминаются",
                   cookie_list_evidence(jar, list(jar)))]
    missing = [name for name in jar if name.lower() not in joined]
    if not missing:
        return [mk(ctx, "CK-004", "PASS", f"Все {len(jar)} cookie названы в документах")]
    spec = ctx.sig["policy_checks"]["cookie_description"]
    cookie_text = " ".join(s for t in docs.values() for s in sentences_with(t, r"cookie|куки"))
    described = (any(re.search(p, cookie_text, re.I) for p in spec["categories"])
                 and any(re.search(p, cookie_text, re.I) for p in spec["purposes"]))
    if described:
        return [mk(ctx, "CK-004", "WARN",
                   f"Cookie описаны в общем виде, но из {len(jar)} фактических имён не названы "
                   f"{len(missing)}", cookie_list_evidence(jar, missing))]
    return [mk(ctx, "CK-004", "FAIL",
               f"Cookie упомянуты без описания типов и назначения; из {len(jar)} фактических имён "
               f"не названы {len(missing)}", cookie_list_evidence(jar, missing))]


def cookie_list_evidence(jar: dict[str, dict[str, Any]], names_: list[str]) -> list[Evidence]:
    """Один перечень вместо дюжины строк: это и есть содержимое будущей таблицы."""
    rows = [f"{n} ({jar[n].get('domain') or '—'})" for n in names_]
    return [Evidence(kind="cookie", detail="не описаны в документах: " + ", ".join(rows))]


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
    saved = {}
    try:
        saved = ctx._load_json("registries/operators.json", {})
        if saved.get("inn") == ctx.inn and saved.get("body_base64"):
            age = reg.age_days(saved.get("fetched_at"))
            if age is None or age > reg.DEFAULT_TTL_DAYS:
                raise transport.NetworkError("operators_snapshot_stale")
            raw = base64.b64decode(saved["body_base64"], validate=True)
        elif transport.ACTIVE or reg._proxy_url:
            raw = reg.http_get(url, timeout=40)
        else:
            raise transport.NetworkError("operators_not_collected")
    except Exception as exc:
        # Сообщение читает человек, который прокси ещё не настраивал. Название
        # переменной без команды, в которую её подставляют, ему ничего не даёт.
        error_code = (saved.get('error') if isinstance(saved, dict) else None) or (
            exc.code if isinstance(exc, transport.NetworkError) else type(exc).__name__)
        return [mk(ctx, "PDN-010", "UNKNOWN",
                   f"Реестр операторов не дал подтверждённого ответа: {error_code}",
                   [Evidence(kind="registry", detail="запрос к реестру", url=url)],
                   manual_check=(
                       "Проверить оператора вручную: открыть "
                       "https://pd.rkn.gov.ru/operators-registry/operators-list/ и "
                       f"ввести ИНН {ctx.inn} в поле «ИНН», нажать «Найти» и сохранить "
                       "дату и результат. Пустой ответ требует проверки работоспособности поиска.\n\n"
                       "Для нового автоматического сбора используйте scripts/audit.py "
                       "с managed-шлюзом и пустым каталогом --out; этот detect "
                       "повторно обрабатывает только уже сохранённые данные."))]
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
        stale = data.stale_days is not None and data.stale_days > reg.DEFAULT_TTL_DAYS
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
            if stale:
                finding.status = "WARN" if hits else "UNKNOWN"
                finding.source_note = note + f"; архивный снимок: {data.stale_days:.1f} дней"
                finding.summary += "; актуальность реестра не подтверждена"
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
    """DISC-004, DISC-005: видимая символика отдельно от невидимой разметки.

    Иконка и ссылка на странице — публичная демонстрация символики. Instagram в
    JSON-LD sameAs посетитель не видит, но поисковик показывает его в карточке
    организации; это риск, который снимается одной правкой разметки.
    """
    sig = ctx.sig["symbols"]
    out: list[Finding] = []
    visible: list[Evidence] = []
    hidden: list[Evidence] = []
    for slug, dom in ctx.doms.items():
        low = dom.lower()
        body = SCRIPT_RE.sub(" ", low)
        for cls in sig["meta"]["css_classes"]:
            if cls in body:
                visible.append(Evidence(kind="dom", detail=f"иконка соцсети: {cls}", selector=slug))
                break
        for host in sig["meta"]["link_hosts"]:
            if re.search(rf"href=[\"'][^\"']*//{re.escape(host)}", body):
                visible.append(Evidence(kind="dom", detail=f"видимая ссылка на {host}", selector=slug))
                break
            if f"//{host}" in low and f"//{host}" not in body:
                hidden.append(Evidence(kind="dom", detail=f"{host} только в скрытой разметке (JSON-LD, скрипты)",
                                       selector=slug, snippet=jsonld_snippet(dom, host)))
                break
    if visible:
        out.append(mk(ctx, "DISC-005", "FAIL",
                      f"Видимые иконки или ссылки Instagram/Facebook: {len(visible)}", visible[:6]))
    elif hidden:
        pages = sorted({e.selector for e in hidden})
        out.append(mk(ctx, "DISC-005", "WARN",
                      f"Instagram/Facebook не видны посетителю, но указаны в разметке schema.org "
                      f"(sameAs) на {len(pages)} страницах — поисковики показывают их в карточке компании",
                      hidden[:3], fix_hint="Удалить адреса Instagram и Facebook из JSON-LD (поле sameAs) "
                                           "в шаблоне сайта."))
    else:
        out.append(mk(ctx, "DISC-005", "PASS", "Иконок и ссылок Instagram/Facebook нет"))

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
                  else "Упоминаний Meta без пометки нет",
                  mentions[:6], needs_llm=bool(mentions)))
    return out


SCRIPT_RE = re.compile(r"<script\b.*?</script>|<noscript\b.*?</noscript>|<!--.*?-->", re.S | re.I)


def jsonld_snippet(dom: str, host: str) -> str:
    i = dom.lower().find("//" + host)
    return re.sub(r"\s+", " ", dom[max(0, i - 80): i + 80]) if i >= 0 else ""


@detector("blocked_platforms")
def detect_blocked_platforms(ctx: Context) -> list[Finding]:
    """DISC-008: видимые ссылки на площадки, заблокированные в РФ."""
    platforms = ctx.sig["blocked_platforms"]
    links = {l.get("url"): l for l in ctx.enrich("links").get("links") or []}
    found: dict[str, Evidence] = {}
    external: set[str] = set()
    for slug, dom in ctx.doms.items():
        body = SCRIPT_RE.sub(" ", dom)
        for href in re.findall(r"href=[\"'](https?://[^\"']+)", body, re.I):
            host = host_of(href)
            if not host or first_party(href, ctx.target):
                continue
            external.add(registrable_domain(host))
            for name, hosts in platforms.items():
                if host in hosts and name not in found:
                    info = links.get(href) or {}
                    owner = {True: "; аккаунт принадлежит бренду", False: "; аккаунт бренду не принадлежит"}.get(
                        info.get("brand_match"), "")
                    found[name] = Evidence(kind="dom", detail=f"ссылка на {name}{owner}", url=href,
                                           selector=slug, snippet=info.get("brand_evidence"))
    if found:
        return [mk(ctx, "DISC-008", "WARN",
                   "Видимые ссылки на заблокированные в РФ площадки: " + ", ".join(found),
                   list(found.values()))]
    social = sorted(d for d in external if d.split(".")[0] in
                    ("t", "vk", "ok", "youtube", "rutube", "dzen", "telegram", "max"))
    return [mk(ctx, "DISC-008", "PASS",
               "Ссылок на заблокированные площадки нет"
               + (f"; внешние площадки на сайте: {', '.join(social)}" if social else ""))]


@detector("vpn_ads")
def detect_vpn_ads(ctx: Context) -> list[Finding]:
    """DISC-009: реклама VPN — термин и призыв в одном предложении."""
    spec = ctx.sig["vpn_markers"]
    term = "|".join(spec["terms"])
    promo = "|".join(spec["promo"])
    hits = []
    for slug, text in ctx.texts.items():
        for s in sentences_with(text, rf"(?<![0-9a-zа-яё])(?:{term})"):
            if re.search(promo, s, re.I):
                hits.append(Evidence(kind="text", detail="VPN в рекламном контексте", selector=slug,
                                     snippet=s[:240]))
    if hits:
        return [mk(ctx, "DISC-009", "FAIL", f"Тексты, продвигающие VPN или обход блокировок: {len(hits)}",
                   hits[:6], needs_llm=True)]
    return [mk(ctx, "DISC-009", "PASS",
               f"Рекламы VPN и средств обхода блокировок нет ({len(ctx.texts)} страниц)")]


def element_check(text: str, elements: dict[str, dict[str, Any]]) -> tuple[list[str], list[Evidence]]:
    missing, found = [], []
    for key, spec in elements.items():
        quote = None
        for pattern in spec["patterns"]:
            m = re.search(pattern, text, re.I)
            if m:
                quote = re.sub(r"\s+", " ", text[max(0, m.start() - 60): m.end() + 100]).strip()
                break
        if quote:
            found.append(Evidence(kind="text", detail=f"есть: {spec['label']}", snippet=quote))
        else:
            missing.append(spec["label"])
    return missing, found


@detector("policy_content")
def detect_policy_content(ctx: Context) -> list[Finding]:
    """PDN-003: обязательные сведения политики — поимённо «есть» или «нет»."""
    docs = legal_corpus(ctx, privacy_only=True)
    if not docs:
        if privacy_documents(ctx):
            return [mk(ctx, "PDN-003", "UNKNOWN", "Политика опубликована файлом, текст из него не извлечён")]
        return [mk(ctx, "PDN-003", "FAIL", "Политики нет — раскрывать сведения негде (см. PDN-001)")]
    slug, text = max(docs.items(), key=lambda kv: len(kv[1]))
    missing, found = element_check(text, ctx.sig["policy_checks"]["policy_elements"])
    where = Evidence(kind="text", detail="проверенный документ", selector=slug)
    if missing:
        return [mk(ctx, "PDN-003", "FAIL", "В политике нет: " + "; ".join(missing),
                   [where] + [Evidence(kind="text", detail="отсутствует: " + m) for m in missing] + found[:4],
                   needs_llm=True)]
    return [mk(ctx, "PDN-003", "PASS", "Все обязательные сведения в политике найдены", [where] + found[:6],
               needs_llm=True)]


CONSENT_URL_HINTS = ("soglas", "agree", "consent", "personal-data", "personalnyh", "obrabotk")


@detector("consent_content")
def detect_consent_content(ctx: Context) -> list[Finding]:
    """PDN-008: текст согласия, на который ведёт подпись чекбокса."""
    forms = [(p, f) for p in ctx.pages for f in p.get("forms") or [] if form_collects_pd(f)]
    if not forms:
        return [mk(ctx, "PDN-008", "NA", "Форм сбора персональных данных нет")]
    linked: set[str] = set()
    labels = []
    for _, form in forms:
        for cb in form.get("fields") or []:
            if cb.get("type") == "checkbox":
                labels.append(cb.get("label_text") or "")
                for href in cb.get("label_links") or []:
                    linked.add(urllib.parse.urljoin(ctx.target + "/", href).split("#")[0].rstrip("/"))
    candidates = []
    for page in ctx.pages:
        url = (page.get("final_url") or page.get("url") or "").split("#")[0].rstrip("/")
        text = ctx.texts.get(page.get("slug", ""))
        low_url = url.lower()
        if not text or re.search(r"privacy|polic|politik|konfidenc", low_url):
            continue
        if re.search(r"user-?agreement|polzovatel|terms|oferta|offer|rules|pravila", low_url):
            continue
        head = text[:3000]
        is_consent = (re.search(r"согласи", head, re.I)
                      and re.search(r"персональн|обработк|рассылк", head, re.I))
        if is_consent and (url in linked or any(h in low_url for h in CONSENT_URL_HINTS)):
            candidates.append((page.get("slug"), text))
    if not candidates:
        label = next((l for l in labels if l), "")
        return [mk(ctx, "PDN-008", "FAIL",
                   "Отдельного текста согласия нет: подпись чекбокса ссылается только на политику"
                   if label else "Отдельного текста согласия нет, чекбокса согласия в формах нет",
                   [Evidence(kind="dom", detail="подпись чекбокса", snippet=label[:200])] if label else [],
                   needs_llm=True)]
    results = []
    for slug, text in candidates:
        missing, found = element_check(text, ctx.sig["policy_checks"]["consent_elements"])
        results.append((slug, missing, found))
    worst = max(results, key=lambda r: len(r[1]))
    slug, missing, found = worst
    where = Evidence(kind="text", detail="проверенный текст согласия", selector=slug)
    path = urllib.parse.urlparse(ctx.page_by_slug(slug).get("final_url") or ctx.page_by_slug(slug).get("url") or "").path
    if missing:
        return [mk(ctx, "PDN-008", "FAIL", f"В тексте согласия ({path or slug}) нет: " + "; ".join(missing),
                   [where] + [Evidence(kind="text", detail="отсутствует: " + m) for m in missing] + found[:3],
                   needs_llm=True)]
    return [mk(ctx, "PDN-008", "PASS", "Текст согласия содержит все элементы ч. 4 ст. 9",
               [where] + found[:5], needs_llm=True)]


PD_CATEGORIES = {
    "email": ("адрес электронной почты", r"электронн\w* почт|e-?mail"),
    "phone": ("номер телефона", r"телефон"),
    "name": ("имя", r"\bимя\b|фамили|ф\.?и\.?о"),
    "address": ("адрес", r"адрес\w*(?! электронн)"),
    "birth": ("дата рождения", r"дат\w* рождени"),
}


def field_categories(form: dict[str, Any]) -> set[str]:
    cats = set()
    for f in form.get("fields") or []:
        blob = " ".join(str(f.get(k) or "") for k in ("type", "name", "id", "placeholder", "label",
                                                     "autocomplete")).lower()
        if f.get("type") == "email" or re.search(r"e-?mail|почт", blob):
            cats.add("email")
        if f.get("type") == "tel" or re.search(r"phone|tel\b|телефон", blob):
            cats.add("phone")
        if re.search(r"\bname\b|fio|имя|фамил|first_?name|last_?name|surname", blob):
            cats.add("name")
        if re.search(r"address|адрес|street|улиц", blob) and "email" not in blob:
            cats.add("address")
        if re.search(r"birth|рожд", blob):
            cats.add("birth")
    return cats


def form_collects_pd(form: dict[str, Any]) -> bool:
    return bool(field_categories(form))


@detector("policy_vs_practice")
def detect_policy_vs_practice(ctx: Context) -> list[Finding]:
    """PDN-012: всё, что сайт подключил и собирает, должно быть названо в политике."""
    docs = legal_corpus(ctx)
    if not docs:
        if privacy_documents(ctx):
            return [mk(ctx, "PDN-012", "UNKNOWN", "Политика опубликована файлом, текст из него не извлечён")]
        return [mk(ctx, "PDN-012", "FAIL", "Политики нет — описать фактическую обработку негде")]
    corpus = " ".join(docs.values()).lower()
    aliases = ctx.sig["trackers"].get("aliases") or {}
    absent_services = []
    for r in third_party_recipients(ctx).values():
        if r["kind"] in ("fonts", "cdn", "captcha", "embed", "errors"):
            continue
        variants = aliases.get(r["vendor"] or "", []) + [h.split(".")[-2] for h in r["hosts"] if "." in h]
        if not any(v.lower() in corpus for v in variants if len(v) > 2):
            absent_services.append(r)
    collected = set()
    for page in ctx.pages:
        for form in page.get("forms") or []:
            collected |= field_categories(form)
    absent_data = [PD_CATEGORIES[c][0] for c in sorted(collected) if not re.search(PD_CATEGORIES[c][1], corpus)]
    ev = [recipient_evidence(r) for r in absent_services][:8]
    ev += [Evidence(kind="dom", detail=f"поле формы «{d}» не описано в политике") for d in absent_data]
    parts = []
    if absent_services:
        parts.append("сервисы " + names(absent_services))
    if absent_data:
        parts.append("данные: " + ", ".join(absent_data))
    if parts:
        return [mk(ctx, "PDN-012", "FAIL", "На сайте есть, в документах не названы: " + "; ".join(parts),
                   ev, needs_llm=True)]
    return [mk(ctx, "PDN-012", "PASS",
               "Подключённые сервисы и собираемые данные названы в документах", needs_llm=True)]


EXCESSIVE_FIELDS = {
    "passport": ("паспортные данные", r"passport|паспорт"),
    "snils": ("СНИЛС", r"snils|снилс"),
    "inn": ("ИНН", r"\binn\b|\bинн\b"),
    "birth": ("дата рождения", r"birth|рожд"),
    "gender": ("пол", r"\bgender\b|\bsex\b|\bпол\b"),
}


@detector("forms_minimization")
def detect_forms_minimization(ctx: Context) -> list[Finding]:
    """PDN-013: состав полей формы против её назначения."""
    forms = [(p, f) for p in ctx.pages for f in p.get("forms") or [] if form_collects_pd(f)]
    if not forms:
        return [mk(ctx, "PDN-013", "NA", "Форм сбора персональных данных нет")]
    excessive, kinds = [], {}
    for page, form in forms:
        cats = field_categories(form)
        blob = " ".join(" ".join(str(f.get(k) or "") for k in ("name", "id", "placeholder", "label"))
                        for f in form.get("fields") or []).lower()
        order = "address" in cats and "phone" in cats
        kind = ("оформление заказа" if order else "подписка" if cats == {"email"}
                else "вход" if page.get("scenario") == "auth" else "заявка")
        kinds.setdefault(kind, set()).update(PD_CATEGORIES[c][0] for c in cats)
        for key, (label, pattern) in EXCESSIVE_FIELDS.items():
            if re.search(pattern, blob) and not (order and key == "inn"):
                excessive.append(Evidence(kind="dom", detail=f"{kind}: поле «{label}»",
                                          selector=f"{page.get('slug')} {form.get('selector')}"))
    if excessive:
        return [mk(ctx, "PDN-013", "FAIL", "Формы собирают лишние данные: "
                   + ", ".join(e.detail for e in excessive[:6]), excessive[:6], needs_llm=True)]
    summary = "; ".join(f"{k} — {', '.join(sorted(v))}" for k, v in kinds.items())
    return [mk(ctx, "PDN-013", "PASS", "Состав полей форм не шире назначения: " + summary, needs_llm=True)]


@detector("applicability")
def detect_applicability(ctx: Context) -> list[Finding]:
    """AUTH-005: к кому обращено требование — определяется по ИНН с сайта."""
    if ctx.inn and len(ctx.inn) in (10, 12):
        who = "юрлицо" if len(ctx.inn) == 10 else "ИП или гражданин"
        return [mk(ctx, "AUTH-005", "PASS", f"Владелец — российское {who}: ИНН {ctx.inn}",
                   [Evidence(kind="text", detail=f"ИНН {ctx.inn} на сайте, контрольная сумма верна")])]
    return [mk(ctx, "AUTH-005", "WARN",
               "ИНН на сайте не найден; сайт русскоязычный и ориентирован на РФ — требования группы "
               "считаются применимыми")]


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

    out.append(hosting_finding(ctx))
    out.append(blocklist_finding(ctx))
    return out


LEGAL_FORM_TOKENS = {"ооо", "ао", "пао", "зао", "оао", "llc", "ltd", "jsc", "inc", "gmbh", "limited",
                     "co", "company", "общество", "ограниченной", "ответственностью", "с"}
TRANSLIT = str.maketrans({"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
                          "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
                          "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
                          "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ы": "y",
                          "э": "e", "ю": "yu", "я": "ya", "ъ": "", "ь": ""})


def org_key(name: str) -> str:
    """Сопоставимое ядро названия: «ООО «ДДОС-ГАРД»» и «DDOS-GUARD LTD» -> ddosgard / ddosguard."""
    tokens = [t for t in re.split(r"[^0-9a-zа-яё]+", (name or "").lower()) if t and t not in LEGAL_FORM_TOKENS]
    key = "".join(tokens).translate(TRANSLIT)
    return key.replace("guard", "gard").replace("ks", "x")


def hosting_finding(ctx: Context) -> Finding:
    geo = ctx.infra.get("geo") or []
    site = (ctx.enrich("hosts").get("site") or {})
    orgs = [o for o in [site.get("org"), site.get("whois_org")] + [g.get("org") for g in geo] if o]
    ev = [Evidence(kind="infra", detail=f"{g.get('ip')} — {g.get('country')} {g.get('org', '')}")
          for g in geo[:4]]
    if not geo and not site:
        return mk(ctx, "INF-002", "UNKNOWN", "Геоданные хостинга не получены")
    if geo and not any(g.get("country") == "RU" for g in geo):
        return mk(ctx, "INF-002", "WARN",
                  "Хостинг за пределами РФ: " + ", ".join(sorted({g.get('country') or '?' for g in geo})), ev)
    try:
        registry = ctx.registry("rkn_hosting_providers")
    except Exception as exc:  # старый пакет реестров без этого ключа
        return mk(ctx, "INF-002", "UNKNOWN", f"Реестр провайдеров хостинга не загружен ({type(exc).__name__})", ev)
    if not registry.entries:
        return mk(ctx, "INF-002", "UNKNOWN",
                  f"Реестр провайдеров хостинга не загружен ({registry.error or 'нет данных'})", ev)
    wanted = {org_key(o) for o in orgs if org_key(o)}
    for entry in registry.entries:
        names_ = [entry.get("name") or ""] + list(entry.get("aliases") or [])
        keys = {org_key(n) for n in names_ if org_key(n)}
        if any(w and k and (w in k or k in w) for w in wanted for k in keys):
            return mk(ctx, "INF-002", "PASS",
                      f"Провайдер {orgs[0]} есть в реестре провайдеров хостинга: {entry.get('name')}",
                      ev + [Evidence(kind="registry", detail=f"запись реестра: {entry.get('name')}"
                                     + (f", ИНН {entry.get('inn')}" if entry.get("inn") else ""))],
                      source_trust=registry.source_trust)
    return mk(ctx, "INF-002", "WARN",
              f"Организация сети сайта ({', '.join(dict.fromkeys(orgs)) or 'не определена'}) в реестре "
              f"провайдеров хостинга не найдена", ev, source_trust=registry.source_trust)


BLOCK_STUB_FALLBACK = ("доступ к информационному ресурсу ограничен", "доступ к ресурсу ограничен",
                       "ресурс заблокирован", "eais.rkn.gov.ru", "blocked by roskomnadzor",
                       "внесён в единый реестр")


def blocklist_finding(ctx: Context) -> Finding:
    """INF-004: сайт открывается из РФ — значит, по домену он не заблокирован.

    Реестр ЕАИС закрыт капчей, но сам факт его применения виден снаружи:
    операторы связи обязаны отдать заглушку вместо сайта. Проверка идёт через
    российский выход аудита, поэтому доступность — прямое наблюдение.
    """
    host = ctx.infra.get("host") or urllib.parse.urlparse(ctx.target).hostname or "—"
    reach = ctx.enrich("reachability")
    network = ctx.manifest.get("network") or {}
    egress = network.get("egress") or {}
    home = next((p for p in ctx.pages if p.get("slug") == "index"), ctx.pages[0] if ctx.pages else {})
    markers = [m.lower() for m in (ctx.sig.get("block_stubs") or {}).get("text_markers", [])] \
        or list(BLOCK_STUB_FALLBACK)
    text = (ctx.texts.get(home.get("slug", ""), "") or "")[:5000].lower()
    stub = reach.get("block_stub") or any(m in text for m in markers)
    ru = reach.get("ru_exit") if "ru_exit" in reach else egress.get("country") == "RU"
    if stub:
        return mk(ctx, "INF-004", "FAIL", f"Через российский выход вместо {host} отдаётся страница блокировки",
                  [Evidence(kind="http", detail=reach.get("matched_marker") or "маркер заглушки блокировки",
                            url=home.get("final_url"))])
    if ru and home.get("status") == 200 and (home.get("text_chars") or len(text)) > 0:
        return mk(ctx, "INF-004", "PASS",
                  f"{host} открывается через российский выход ({egress.get('ip') or 'РФ'}) без заглушки "
                  "блокировки", [Evidence(kind="http", detail=f"HTTP 200 через выход {egress.get('ip', '')} "
                                                              f"({egress.get('country', 'RU')})",
                                          url=home.get("final_url"))])
    if not ru:
        return mk(ctx, "INF-004", "UNKNOWN", "Сбор шёл не через российский выход — доступность из РФ не наблюдалась")
    return mk(ctx, "INF-004", "UNKNOWN", "Главная страница через российский выход не открылась")


STATIC_RE = re.compile(r"\.(?:svg|png|jpe?g|gif|webp|avif|ico|css|woff2?|ttf|otf|eot|mp4|webm|map)(?:$|\?)", re.I)


@detector("form_endpoints_geo")
def detect_endpoints(ctx: Context) -> list[Finding]:
    """PDN-011 и INF-003: куда уходят данные и где эти получатели.

    Статика своего домена (спрайты, шрифты, стили) — не поток данных, и в
    доказательствах локализации ей не место: она прячет единственно значимые
    строки среди сотни одинаковых.
    """
    if ctx.degraded:
        return [mk(ctx, rid, "UNKNOWN", "Без рендера приёмники форм не наблюдаются")
                for rid in ("PDN-011", "INF-003")]
    ev, seen = [], set()
    foreign_forms = []
    # Куда формы отправляют данные по разметке: пустой action — тот же адрес.
    form_hosts = set()
    for page in ctx.pages:
        for form in page.get("forms") or []:
            if form_collects_pd(form):
                action = urllib.parse.urljoin(page.get("final_url") or page.get("url") or ctx.target,
                                              form.get("action") or "")
                form_hosts.add(host_of(action))
    for req in ctx.all_requests():
        url = safe_url(req.get("url"))
        if not url:
            continue
        category, basis = classify_request(req)
        own = first_party(url, ctx.target)
        shape = (req.get("payload_shape") or {}).get("known_fields")
        if (req.get("method") in ("GET", "HEAD", None)) and not shape and category == "unknown":
            continue
        if STATIC_RE.search(url) and not shape:
            continue
        key = (url, req.get("method"), category)
        if key in seen:
            continue
        seen.add(key)
        context = request_context(req)
        detail = f"{req.get('method', '?')}: {basis}"
        ev.append(Evidence(kind="request", detail=detail, url=url, context=context))
        if category == "form_submission" and not own:
            country = (tracker_spec(ctx, url) or {}).get("country") or ctx.host_info(host_of(url)).get("country")
            if country and country != "RU":
                foreign_forms.append((url, country))
    recipients = third_party_recipients(ctx)
    foreign = [r for r in recipients.values() if r["country"] not in (None, "RU")]
    unknown = [r for r in recipients.values() if r["country"] is None]
    if foreign_forms:
        pdn011 = mk(ctx, "PDN-011", "FAIL",
                    "Данные формы отправляются напрямую на сервер за пределами РФ: "
                    + ", ".join(f"{host_of(u)} ({c})" for u, c in foreign_forms[:4]), ev[:8])
    elif foreign:
        pdn011 = mk(ctx, "PDN-011", "WARN",
                    f"Данные посетителей получают иностранные сервисы ({names(foreign)}): первичная "
                    "запись их идентификаторов происходит вне РФ",
                    [recipient_evidence(r) for r in foreign][:6])
    else:
        own_forms = form_hosts and all(first_party("https://" + h, ctx.target) for h in form_hosts if h)
        parts = []
        if own_forms:
            parts.append("формы отправляют данные на собственный домен (" + ", ".join(sorted(form_hosts)) + ")")
        if recipients and not unknown:
            parts.append("сторонние получатели российские: " + names(recipients.values()))
        elif unknown:
            parts.append("страна не определена для: " + names(unknown))
        summary = "; ".join(parts) or "сторонних получателей нет"
        pdn011 = mk(ctx, "PDN-011", "EXTERNAL",
                    summary[0].upper() + summary[1:] + ". Где стоят базы, снаружи не видно — подтверждает владелец",
                    ev[:6] + [recipient_evidence(r) for r in recipients.values()][:6])
    if foreign:
        inf003 = mk(ctx, "INF-003", "WARN", f"Получатели за пределами РФ: {names(foreign)}",
                    [recipient_evidence(r) for r in foreign][:8])
    elif unknown:
        inf003 = mk(ctx, "INF-003", "UNKNOWN",
                    f"Страна не определена для: {names(unknown)} — доразведка в этом сборе не выполнялась",
                    [recipient_evidence(r) for r in unknown][:8])
    else:
        inf003 = mk(ctx, "INF-003", "PASS",
                    "Все получатели наблюдаемых потоков — в РФ"
                    + (f": {names(recipients.values())}" if recipients else " (сторонних получателей нет)"),
                    [recipient_evidence(r) for r in recipients.values()][:8])
    return [pdn011, inf003]


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


def artifact_fingerprint(ctx: Context) -> str:
    import hashlib
    digest = hashlib.sha256()
    for path in sorted(ctx.dir.rglob("*")):
        if path.is_file() and path.name != "semantic-review.json":
            if path.suffix not in {".json", ".jsonl", ".txt", ".html"}:
                continue
            digest.update(path.relative_to(ctx.dir).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def attach_semantic_reviews(ctx: Context, findings: list[Finding]):
    # Reusing findings after an artifact change must not retain a stale review.
    for finding in findings:
        finding.semantic_review = None
    review = ctx._load_json("semantic-review.json", {})
    if not isinstance(review, dict) or not review or review.get("target") != ctx.target or review.get("artifacts_sha256") != artifact_fingerprint(ctx):
        return
    rules = review.get("rules")
    if not isinstance(rules, dict):
        return
    for f in findings:
        item = rules.get(f.rule_id)
        if not isinstance(item, dict):
            continue
        if item.get("status") not in {"PASS", "FAIL", "WARN", "UNKNOWN", "NA", "EXTERNAL"}:
            continue
        if not all(item.get(k) for k in ("reviewer", "reviewed_at", "evidence")):
            continue
        activities = item.get("activities") or []
        if not isinstance(activities, list) or not all(isinstance(a, dict) for a in activities):
            continue
        if not isinstance(item["evidence"], list):
            continue
        if not valid_action_review(item):
            continue
        required = {(a["service"], a["purpose"]) for a in f.processing_activities}
        verified = {(a.get("service"), a.get("purpose")) for a in activities
                    if a.get("verified_basis") and a.get("evidence")}
        if item["status"] == "PASS" and not required.issubset(verified):
            continue
        f.semantic_review = item


def run(ctx: Context) -> dict[str, Any]:
    findings: list[Finding] = []
    order = ["requisites", "applicability", "auth_providers", "registry_mentions", "meta_symbols",
             "blocked_platforms", "vpn_ads",
             "documents", "policy_content", "consent_content", "policy_vs_practice",
             "forms_consent", "forms_minimization", "cookie_banner", "consent_gating",
             "legitimate_interest",
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

    attach_semantic_reviews(ctx, findings)
    if ctx.manifest.get("network") and not ctx.manifest["network"].get("complete"):
        for f in findings:
            # Direct observations on opened pages and independent registry/DNS
            # checks remain usable. Absence and applicability claims need the
            # pages that failed to load, so they stay UNKNOWN.
            if f.rule_id in ("INF-001", "INF-002", "PDN-010") or f.group == "internal":
                continue
            if f.status in ("FAIL", "WARN") and f.evidence:
                f.summary = "Неполный обход; на доступных страницах: " + f.summary
                continue
            original = f.status
            f.status = "UNKNOWN"
            f.summary = f"Сетевой этап неполон (предварительно {original}): " + f.summary
            f.semantic_review = None
    by_status: dict[str, int] = {}
    effective_by_status: dict[str, int] = {}
    for f in findings:
        by_status[f.status] = by_status.get(f.status, 0) + 1
        effective = (f.semantic_review or {}).get("status") or f.status
        effective_by_status[effective] = effective_by_status.get(effective, 0) + 1
    fails = [f for f in findings if f.status == "FAIL"]
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda f: (0 if f.status == "FAIL" else
                                 1 if f.status == "WARN" else
                                 2 if f.status == "UNKNOWN" else 3,
                                 sev_order.get(f.severity, 9), f.rule_id))

    return {
        "schema_version": SCHEMA_VERSION,
        "producer": current_producer(),
        "collection": {
            "collector": ctx.manifest.get("collector"),
            "schema_version": ctx.manifest.get("schema_version"),
            "started_at": ctx.manifest.get("started_at"),
            "finished_at": ctx.manifest.get("finished_at"),
            "visual_complete": ctx.manifest.get("visual_complete"),
            "partial_pages": ctx.manifest.get("partial_pages"),
            "refusal": ctx.manifest.get("refusal"),
            "banner_found": bool(ctx.banner.get("found")),
            "network": ctx.manifest.get("network"),
            "network_observations": {
                "count": sum(len(rows) for rows in ctx.net.values()),
                "versions": sorted({str(row.get("observation_version", 1))
                                    for rows in ctx.net.values() for row in rows}),
            },
        },
        "artifacts_sha256": artifact_fingerprint(ctx),
        "target": ctx.target,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "network": ctx.manifest.get("network", {}),
        "degraded": ctx.degraded,
        "degraded_reason": ctx.manifest.get("degraded_reason"),
        "blocked": ctx.blocked,
        "thin_coverage": ctx.thin_coverage,
        "unvisited_links": ctx.unvisited_links,
        "pages_analysed": len([p for p in ctx.pages if p.get("status") == 200]),
        # Адрес страницы по её slug: отчёт называет место находки ссылкой,
        # а не внутренним именем каталога артефактов.
        "pages": [{"slug": p.get("slug"), "url": safe_url(p.get("final_url") or p.get("url")),
                   "scenario": p.get("scenario")} for p in ctx.pages],
        "scenarios": [{k: s.get(k) for k in ("name", "status", "url", "error")} for s in ctx.scenarios],
        "registry_status": {
            key: {"origin": d.origin, "trust": d.source_trust,
                  "entries": len(d.entries), "stale_days": d.stale_days,
                  "error": d.error}
            for key, d in ctx._registries.items()},
        "stats": {"by_status": by_status, "effective_by_status": effective_by_status,
                  "fail_count": len(fails), "effective_fail_count": effective_by_status.get("FAIL", 0),
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

    artifacts = Path(args.artifacts).resolve()
    if reg._proxy_url:
        # Backwards-compatible, explicitly configured registry-only network refresh.
        from audit import snapshot_registries
        transport.preflight(browser=False)
        target = json.loads((artifacts / "manifest.json").read_text(encoding="utf-8"))["target"]
        with transport.NetworkSession(target, mode="custom", proxy=reg._proxy_url):
            snapshot_registries(artifacts, args.inn)
        reg.set_proxy(None)
    ctx = Context(artifacts, inn=args.inn)
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
