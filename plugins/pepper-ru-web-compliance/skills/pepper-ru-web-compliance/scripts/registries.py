#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""registries.py — слой государственных реестров.

Проверка упоминаний (правила DISC-001, DISC-003, DISC-006, DISC-007) имеет
смысл только против актуального реестра. Поэтому здесь три вещи: загрузка из
первоисточника, нормализация разнородных форматов в одну схему и поиск
упоминаний в тексте с учётом русского словоизменения.

Источники ведомств доступны нестабильно, и причины у этого разные:
`*.rkn.gov.ru` и `fedsfm.ru` отвечают только с российских адресов, а
`reestrs.minjust.gov.ru` вдобавок отдаёт неполную цепочку сертификатов (см.
`assets/ca/`). Ломать из-за этого всю проверку нельзя, поэтому каждый реестр
разрешается по цепочке
    официальный источник напрямую
      -> официальный источник через прокси пользователя (PEPPER_RU_REGISTRY_PROXY)
      -> зеркало
      -> локальный кэш -> локальный снапшот -> недоступен
и КАЖДЫЙ результат несёт две отметки: откуда взят (`origin`) и какова
юридическая сила источника (`source_trust`).

Разница между ними принципиальна. Официальный источник — в том числе
полученный через прокси, потому что прокси это транспорт, а не источник —
позволяет утверждать «упоминаний не найдено». Зеркало этого не позволяет:
данные могут быть полны и свежи, но это не официальная публикация, и вывод
по ним не поднимается выше WARN.

Снапшоты СОЗДАЁТ ПОЛЬЗОВАТЕЛЬ у себя (`import --as-snapshot`) и в релиз они
не входят намеренно. Реестр иноагентов пополняется еженедельно, и архивная
копия в дистрибутиве давала бы худший из возможных отказов — не «нет данных»,
а тихое ложное «упоминаний не найдено» по списку, где нужного лица ещё нет.

По той же причине детекторы обязаны переносить `origin` и `stale_days` в
findings и при `origin != "live"` понижать вывод до UNKNOWN там, где отсутствие
совпадений — это утверждение, а не наблюдение.

Использование:
    python3 scripts/registries.py status
    python3 scripts/registries.py update
    python3 scripts/registries.py update --registry minjust_extremist_orgs
    python3 scripts/registries.py import --registry minjust_foreign_agents --file ~/Downloads/reestr.xlsx
    python3 scripts/registries.py match --registry minjust_extremist_orgs --text-file page.txt
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import ssl
import zipfile
import xml.etree.ElementTree as ET
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1
DEFAULT_TTL_DAYS = 7
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "assets" / "registries-snapshot"
CACHE_DIR = Path(os.environ.get(
    "PEPPER_RU_COMPLIANCE_CACHE",
    Path.home() / ".cache" / "pepper-ru-web-compliance" / "registries",
))


# --- Схема -------------------------------------------------------------------


@dataclass
class Entry:
    """Одна запись реестра, приведённая к общему виду.

    `name` — как в первоисточнике, без правок: именно это значение подставляется
    в требуемую плашку. `aliases` — дополнительные написания для поиска
    (короткие названия в кавычках, латиница, аббревиатуры).
    """
    id: str
    kind: str                      # person | org | material
    name: str
    aliases: list[str] = field(default_factory=list)
    inn: str | None = None
    ogrn: str | None = None
    included_at: str | None = None
    # Исключённый из реестра плашки больше не требует, поэтому дату исключения
    # нужно донести до матчера, а не потерять при нормализации.
    excluded_at: str | None = None
    decision: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RegistryData:
    schema_version: int = SCHEMA_VERSION
    registry: str = ""
    title: str = ""
    fetched_at: str = ""
    source_url: str | None = None
    source_sha256: str | None = None
    source_trust: str | None = None  # official | mirror
    via_proxy: bool = False
    origin: str = "unavailable"    # live | cache | snapshot | unavailable
    stale_days: float | None = None
    error: str | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)


# --- Загрузка ----------------------------------------------------------------


# Прокси для доступа к ведомственным хостам. Часть из них (reestrs.minjust.gov.ru,
# все *.rkn.gov.ru) отвечает только с российских адресов, поэтому пользователь
# может указать свой канал — VPS или VPN с российским выходом.
#
# Переменная СВОЯ, а не общепринятая HTTPS_PROXY, и это принципиально: прокси
# применяется ТОЛЬКО к загрузке реестров. Обход проверяемого сайта (collect.py)
# должен идти напрямую — правила PDN-011 и INF-003 меряют, куда уходят данные
# форм, и точка наблюдения меняет результат. Плюс сайт может отдавать разное
# в зависимости от географии посетителя.
PROXY_ENV = "PEPPER_RU_REGISTRY_PROXY"
_proxy_url: str | None = os.environ.get(PROXY_ENV) or None


def set_proxy(url: str | None) -> None:
    global _proxy_url
    _proxy_url = url or None


# Часть ведомственных серверов отдаёт неполную цепочку сертификатов: не
# присылает промежуточный, и проверка падает с «не найден издатель». Лечится это
# не отключением проверки — для источника юридических данных подмена реестра
# недопустима, — а тем, что недостающие промежуточные сертификаты лежат рядом и
# цепочка достраивается локально. Проверка при этом остаётся включённой.
EXTRA_CA_DIR = ROOT / "assets" / "ca"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if EXTRA_CA_DIR.is_dir():
        for pem in sorted(EXTRA_CA_DIR.glob("*.pem")):
            try:
                ctx.load_verify_locations(cafile=str(pem))
            except Exception:
                # Битый файл в каталоге не должен ронять загрузку реестров:
                # системных корней достаточно для большинства источников.
                pass
    return ctx


def _opener(use_proxy: bool) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPSHandler(context=_ssl_context())
    ]
    if use_proxy and _proxy_url:
        handlers.append(urllib.request.ProxyHandler(
            {"http": _proxy_url, "https": _proxy_url}))
    else:
        # Пустой ProxyHandler отключает подхват окружения: иначе выставленный
        # для других задач HTTPS_PROXY незаметно изменил бы точку выхода.
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def http_get(url: str, timeout: int = 60, use_proxy: bool = True) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    with _opener(use_proxy).open(req, timeout=timeout) as resp:
        return resp.read()


def decode_best(raw: bytes) -> str:
    for enc in ("utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# --- Нормализация текста -----------------------------------------------------

QUOTE_CHARS = "«»“”„‟\"'‘’„“”"
DASHES = "‐‑‒–—―−⁃­"


def clean_html(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = html.unescape(fragment)
    fragment = fragment.replace("\xa0", " ")
    return re.sub(r"\s+", " ", fragment).strip()


def normalize_text(text: str) -> str:
    """Приводит текст к виду, пригодному для сопоставления.

    Регистр, ё и разнобой кавычек и тире — три источника ложных промахов,
    из-за которых упоминание в реестре и на странице выглядят разными строками.
    """
    text = text.lower().replace("ё", "е")
    for ch in QUOTE_CHARS:
        text = text.replace(ch, '"')
    for ch in DASHES:
        text = text.replace(ch, "-")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


# Описательная преамбула наименования. Юридически она часть названия, но на
# странице организацию почти всегда называют тем, что идёт после неё, поэтому
# ядро наименования извлекается отдельно и ищется самостоятельно.
LEGAL_FORM_PREFIX = re.compile(
    r"^(?:\s*(?:международн\w+|межрегиональн\w+|региональн\w+|местн\w+|"
    r"общественн\w+|религиозн\w+|молодежн\w+|молодёжн\w+|политическ\w+|"
    r"американск\w+|транснациональн\w+|холдингов\w+|некоммерческ\w+|"
    r"автономн\w+|незарегистрирован\w+|структурн\w+|террористическ\w+|"
    r"экстремистск\w+|организация|объединение|движение|группа|партия|"
    r"компания|фонд|сообщество|ассоциация|учреждение|формирование|"
    r"созданн\w+|в\s+форме|города|г\.)\s*,?\s*)+",
    re.I,
)

# Однословные псевдонимы вроде «Ичкерия», «Братство» или «Возрождение»
# встречаются в обычном тексте сплошь и рядом. Полностью отбрасывать их нельзя
# — иногда это единственное, чем организацию называют, — поэтому они идут с
# низкой уверенностью и отдаются на подтверждение смысловому слою.
STOP_ALIASES = {
    "мир", "союз", "дом", "центр", "рост", "база", "весна", "родина", "воля",
    "сила", "знание", "жизнь", "правда", "свобода", "движение", "город",
    "братство", "возрождение", "единство", "держава", "русь", "наследие",
    "согласие", "выбор", "оплот", "щит", "заря", "рассвет", "исход", "клин",
}


# Обиходные слова русского текста. Название, целиком собранное из них
# («Вот так» — так называется медиа из реестра иноагентов), в обычной прозе
# встречается постоянно: «первая генерация дала вот такой результат». Список
# нужен не для того, чтобы такие записи выбрасывать, а чтобы требовать от них
# подтверждения окружением.
COMMON_WORDS = frozenset("""
а без более больше будет было были быть в вам вас ваш весь вместе во вот все
всего всегда всех всё где говорить год да даже два дело день для до другой его
ее её если есть ещё еще же жизнь за здесь и из или им их к каждый как какой
когда который кто лучше люди меня менее место мне много мной может можно мой мы
на над надо наш не него нее неё нет ни но ну о об один она они оно опять от
очень первый перед по под после потом почти при про раз работа рука с сам свой
себя сейчас сказать слово снова со совсем так такой там твой те тем теперь то
тобой тогда только том тот три ту тут ты у уже хорошо хуже чего чем через что
чтобы эта эти это этот я
""".split())


def weak_phrase(phrase: str) -> bool:
    """Собрана ли фраза целиком из обиходных слов.

    Отличить название от куска обычного предложения по самой строке можно
    только так: если ни одно слово не выбивается из повседневной лексики,
    совпадение само по себе ничего не значит. Многословность тут не помогает —
    «вот так» состоит из двух слов и всё равно найдётся на любой странице.
    """
    tokens = phrase_tokens(phrase)
    if not tokens:
        return True
    # Короткое слово вне списка — не признак обиходности: «Ак-Дян», «СИЧ-С14» и
    # «ВЕК РА» тоже короткие, но в обычном тексте не встречаются. Судим только
    # по принадлежности к повседневной лексике.
    return all(token in COMMON_WORDS for token in tokens)


def extract_quoted(name: str) -> list[str]:
    """Достаёт из полного наименования короткие названия для поиска.

    В реестрах наименование обычно выглядит как
    «Межрегиональное общественное движение "Славянский союз"»: юридически
    значимо целое, а на странице встречается только то, что в кавычках.
    Кроме кавычек берём латинские имена собственных («Meta Platforms Inc.») —
    у части записей кавычек нет вовсе, и без этого они не находятся никогда.
    """
    out: list[str] = []

    # Кавычки разбираем парами отдельно по каждому виду: в реестрах регулярно
    # встречаются незакрытые кавычки, и сквозной поиск склеивает куски разных
    # названий в мусорный псевдоним.
    for opener, closer in (("«", "»"), ('"', '"'), ("“", "”")):
        pattern = re.escape(opener) + r"([^" + re.escape(opener + closer) + r"]{2,120})" + re.escape(closer)
        for match in re.findall(pattern, name):
            cleaned = match.strip(" ,.;:-")
            if len(cleaned) >= 3 and not cleaned.endswith(","):
                out.append(cleaned)

    # Латиница: «Meta Platforms Inc.», «Free Nations League», «(Pit Bull)».
    for match in re.findall(r"\b([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&.]+){1,4})", name):
        cleaned = match.strip(" .,")
        if len(cleaned) >= 6:
            out.append(cleaned)

    return list(dict.fromkeys(out))


def core_name(name: str) -> str:
    """Ядро наименования — то, что остаётся после описательной преамбулы."""
    stripped = LEGAL_FORM_PREFIX.sub("", name).strip(" ,.;:-–—")
    return stripped if len(stripped) >= 8 else name


# --- Парсеры первоисточников -------------------------------------------------


def parse_extremist_materials_csv(raw: bytes) -> list[Entry]:
    """Федеральный список экстремистских материалов. CSV, cp1251, разделитель ;"""
    text = decode_best(raw)
    reader = csv.reader(io.StringIO(text), delimiter=";")
    entries: list[Entry] = []
    for row in reader:
        if len(row) < 2:
            continue
        num = row[0].strip()
        if not num.isdigit():
            continue
        material = re.sub(r"\s+", " ", row[1]).strip()
        if not material:
            continue
        entries.append(Entry(
            id=f"fsm-{num}",
            kind="material",
            name=material,
            aliases=extract_quoted(material),
            included_at=(row[2].strip() if len(row) > 2 else None),
        ))
    return entries


def parse_extremist_orgs_html(raw: bytes) -> list[Entry]:
    """Перечень организаций, признанных экстремистскими.

    Разметка — плоский список абзацев «N. Наименование (решение суда от ...)».
    """
    text = decode_best(raw)
    entries: list[Entry] = []
    for match in re.finditer(r"<p[^>]*>\s*(\d{1,4})\.\s*(.+?)</p>", text, re.S):
        num, body = match.group(1), clean_html(match.group(2))
        if len(body) < 8:
            continue
        decision = None
        dec = re.search(r"\((решени[ея][^()]*(?:\([^)]*\))?[^()]*)\)\s*\.?$", body)
        if dec:
            decision = dec.group(1).strip()
            name = body[: dec.start()].strip(" .,")
        else:
            name = body.strip(" .,")
        entries.append(Entry(
            id=f"ext-org-{num}",
            kind="org",
            name=name,
            aliases=extract_quoted(name),
            decision=decision,
        ))
    return entries


def parse_fsb_terror_html(raw: bytes) -> list[Entry]:
    """Единый федеральный список террористических организаций. HTML-таблица."""
    text = decode_best(raw)
    entries: list[Entry] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [clean_html(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        if len(cells) < 2:
            continue
        num = cells[0].strip()
        if not num.isdigit():
            continue
        name = cells[1].strip()
        if len(name) < 3:
            continue
        entries.append(Entry(
            id=f"fsb-terror-{num}",
            kind="org",
            name=name,
            aliases=extract_quoted(name),
            decision=(cells[2] if len(cells) > 2 else None),
        ))
    return entries


def parse_minjust_export(raw: bytes) -> list[Entry]:
    """Выгрузка реестра Минюста (иноагенты, нежелательные организации).

    Формат выгрузки менялся, поэтому тип определяется по сигнатуре файла, а не
    по расширению: XLSX — zip-архив, XLS — составной документ OLE, встречается
    и отдача CSV или HTML-таблицы под тем же URL.
    """
    if raw[:2] == b"PK":
        return _parse_xlsx(raw)
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise RuntimeError(
            "выгрузка пришла в устаревшем формате XLS; пересохраните её в XLSX "
            "и повторите через `registries.py import`"
        )
    text = decode_best(raw)
    if "<table" in text.lower():
        return _parse_html_table(text)
    return _parse_delimited(text)


XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
XLSX_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _xlsx_column_index(ref: str) -> int:
    """A1 -> 0, B1 -> 1, AA1 -> 26. Нужно, чтобы пустые ячейки не сдвигали колонки."""
    letters = "".join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - 64)
    return idx - 1


def _parse_xlsx(raw: bytes) -> list[Entry]:
    """Читает первый лист XLSX средствами стандартной библиотеки.

    XLSX — это zip с XML, и вытащить из него таблицу значений можно без внешних
    пакетов. Зависимость стоила бы дороже, чем кажется: скилл ставят на чужие
    машины, где может не быть ни pip, ни python3-venv, и падение на `pip install`
    ради одного формата — плохой размен. Формул и стилей нам не нужно.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = set(zf.namelist())

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{XLSX_NS}si"):
                # Строка может быть разбита на несколько фрагментов <t> внутри <r>.
                shared.append("".join(t.text or "" for t in si.iter(f"{XLSX_NS}t")))

        sheet_name = _first_sheet_path(zf, names)
        rows: list[list[str]] = []
        for row_el in ET.fromstring(zf.read(sheet_name)).iter(f"{XLSX_NS}row"):
            row: list[str] = []
            for cell in row_el.findall(f"{XLSX_NS}c"):
                col = _xlsx_column_index(cell.get("r") or "A1")
                while len(row) < col:
                    row.append("")
                kind = cell.get("t")
                if kind == "s":
                    v = cell.find(f"{XLSX_NS}v")
                    idx = int(v.text) if v is not None and v.text else -1
                    text = shared[idx] if 0 <= idx < len(shared) else ""
                elif kind == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(f"{XLSX_NS}t"))
                else:
                    v = cell.find(f"{XLSX_NS}v")
                    text = (v.text or "") if v is not None else ""
                row.append(re.sub(r"\s+", " ", text).strip())
            if any(row):
                rows.append(row)
    return _entries_from_rows(rows)


def _first_sheet_path(zf: "zipfile.ZipFile", names: set[str]) -> str:
    """Путь к первому листу книги.

    Через workbook.xml и его rels, а не «xl/worksheets/sheet1.xml» наугад:
    порядок листов в книге и имена файлов совпадают не всегда.
    """
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        first = wb.find(f"{XLSX_NS}sheets/{XLSX_NS}sheet")
        rid = first.get(f"{XLSX_REL_NS}id") if first is not None else None
        if rid:
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rels:
                if rel.get("Id") == rid:
                    target = rel.get("Target", "")
                    target = target[1:] if target.startswith("/") else "xl/" + target.lstrip("./")
                    if target in names:
                        return target
    except Exception:
        pass
    sheets = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
    if not sheets:
        raise RuntimeError("в XLSX не найдено ни одного листа")
    return sheets[0]


def _parse_html_table(text: str) -> list[Entry]:
    rows: list[list[str]] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        cells = [clean_html(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        if cells:
            rows.append(cells)
    return _entries_from_rows(rows)


def _parse_delimited(text: str) -> list[Entry]:
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    rows = [row for row in csv.reader(io.StringIO(text), delimiter=delimiter) if row]
    return _entries_from_rows(rows)


HEADER_KEYS = ("наименован", "фио", "инн", "огрн", "дата", "основани", "п/п",
               "реестр", "тип", "адрес", "снилс")


def _find_header_row(rows: list[list[str]], scan: int = 15) -> int | None:
    """Ищет строку шапки, а не считает первую строку шапкой.

    Выгрузки Минюста начинаются с названия реестра и служебной даты, и только
    потом идёт шапка. Привязка к нулевой строке даёт сдвиг на всю таблицу:
    заголовки попадают в данные, а колонки определяются наугад.
    """
    best, best_score = None, 0
    for idx, row in enumerate(rows[:scan]):
        cells = [normalize_text(c) for c in row if c.strip()]
        if len(cells) < 3:
            continue
        score = sum(1 for c in cells if any(k in c for k in HEADER_KEYS))
        if score >= 3 and score > best_score:
            best, best_score = idx, score
    return best


def _entries_from_rows(rows: list[list[str]]) -> list[Entry]:
    """Собирает записи из таблицы неизвестной раскладки.

    Колонки ищутся по смыслу заголовка, а не по позиции: состав и порядок полей
    в выгрузках менялись. Если шапку опознать не удалось, за наименование
    берётся самая длинная текстовая колонка — грубо, но устойчивее позиции.
    """
    if not rows:
        return []

    header_idx = _find_header_row(rows)
    header = [normalize_text(c) for c in rows[header_idx]] if header_idx is not None else []
    body = rows[header_idx + 1:] if header_idx is not None else rows

    def find_col(*keys: str, exclude: tuple[str, ...] = ()) -> int | None:
        """Первая колонка, чей заголовок содержит любой из ключей."""
        for idx, cell in enumerate(header):
            if any(key in cell for key in keys) and not any(x in cell for x in exclude):
                return idx
        return None

    def find_col_all(*keys: str, exclude: tuple[str, ...] = ()) -> int | None:
        """Колонка, чей заголовок содержит ВСЕ ключи сразу.

        Нужно там, где одного слова мало: «Основания для включения» и «Дата
        принятия решения о включении в реестр» обе содержат «включени», и поиск
        по одному ключу подставляет в дату текст нормы.
        """
        for idx, cell in enumerate(header):
            if all(key in cell for key in keys) and not any(x in cell for x in exclude):
                return idx
        return None

    name_col = find_col("полное наименование", "наименование организации",
                        "наименован", "фио", "фамили")
    inn_col = find_col("инн")
    ogrn_col = find_col("огрн")
    snils_col = find_col("снилс")
    birth_col = find_col("дата рождения")
    type_col = find_col("тип иностранного агента", "тип")
    # «включении» и «исключении» — разные колонки, и путать их нельзя:
    # исключённый из реестра плашки уже не требует.
    incl_col = (find_col_all("дата", "включени", exclude=("исключ", "опубликован"))
                or find_col("дата включения", exclude=("исключ",)))
    excl_col = find_col_all("дата", "исключени") or find_col("дата исключения")
    basis_col = find_col("основани")

    if name_col is None and body:
        widths = [0] * max(len(r) for r in body)
        for row in body[:200]:
            for idx, cell in enumerate(row):
                widths[idx] = max(widths[idx], len(cell))
        name_col = widths.index(max(widths))

    def cell(row: list[str], col: int | None) -> str | None:
        if col is None or col >= len(row):
            return None
        return row[col].strip() or None

    entries: list[Entry] = []
    for idx, row in enumerate(body, start=1):
        name = re.sub(r"\s+", " ", (cell(row, name_col) or "")).strip(" /")
        if len(name) < 3:
            continue
        norm = normalize_text(name)
        # Повторы шапки встречаются в многостраничных выгрузках.
        if any(k in norm for k in ("наименование организации", "полное наименование",
                                   "№ п/п")) and len(norm) < 60:
            continue

        type_value = normalize_text(cell(row, type_col) or "")
        has_person_fields = bool(cell(row, snils_col) or cell(row, birth_col))
        if "физическ" in type_value or "гражданин" in type_value or has_person_fields:
            kind = "person"
        elif type_value:
            kind = "org"
        else:
            words = name.split()
            kind = "person" if (
                2 <= len(words) <= 4
                and all(w[:1].isupper() for w in words if w)
                and not any(m in norm for m in
                            ("ооо", "ао ", "фонд", "организац", "движен", "объединен",
                             "центр", "институт", "ассоциац", "союз", '"'))
            ) else "org"

        entries.append(Entry(
            id=f"row-{idx}",
            kind=kind,
            name=name,
            aliases=extract_quoted(name),
            inn=cell(row, inn_col),
            ogrn=cell(row, ogrn_col),
            included_at=cell(row, incl_col),
            excluded_at=cell(row, excl_col),
            decision=cell(row, basis_col),
        ))
    return entries


WIKIPEDIA_API = ("https://ru.wikipedia.org/w/api.php"
                 "?action=parse&format=json&prop=text&page={title}")


def parse_wikipedia_foreign_agents(raw: bytes) -> list[Entry]:
    """Реестр иностранных агентов по перечням русской Википедии.

    Запасной источник на случай, когда reestrs.minjust.gov.ru недоступен.
    Статья ведёт шесть отдельных перечней (НКО, СМИ, физлица-СМИ, физлица,
    незарегистрированные объединения, единый реестр) и обновляется в течение
    нескольких дней после пополнения реестра.

    Это НЕ официальная публикация, и записи помечаются соответствующе. Для нашей
    задачи направление ошибки благоприятное: волонтёрский перечень скорее
    избыточен, чем неполон, а лишние совпадения отсеивает смысловой слой —
    в отличие от пропуска, который оставит материал без обязательной плашки.
    """
    payload = json.loads(raw.decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(f"Wikipedia API: {payload['error'].get('info', 'ошибка')}")
    html_text = payload["parse"]["text"]["*"]

    entries: list[Entry] = []
    seen: set[str] = set()
    date_re = re.compile(r"\b\d{1,2}\.\d{2}\.\d{4}\b")
    # Ячейки-заголовки и адреса регулярно оказываются самыми длинными в строке,
    # поэтому выбор «просто самой длинной» подсовывает вместо имени шапку
    # таблицы или юридический адрес организации.
    header_re = re.compile(r"^(дата|наименован|назван|№|номер|прим|основан|статус|"
                           r"адрес|инн|огрн|источник|тип|категор|реестров)", re.I)
    address_re = re.compile(r"^\d{6},|\bул\.|\bд\.\s*\d|\bкорп\.|\bстр\.\s*\d|"
                            r"\bпроспект\b|\bпереулок\b|\bшоссе\b", re.I)

    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I):
        raw_cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)
        if len(raw_cells) < 2:
            continue
        cells = [clean_html(c) for c in raw_cells]
        included = next((date_re.search(c).group(0) for c in cells
                         if date_re.search(c)), None)

        def usable(text: str) -> bool:
            t = text.strip()
            # Описания должностей («журналист, главный редактор…») тоже бывают
            # со ссылкой, но начинаются со строчной буквы — имена собственные нет.
            return (4 <= len(t) <= 300 and not t.isdigit()
                    and not date_re.fullmatch(t) and t[:1].isupper()
                    and not header_re.match(t) and not address_re.search(t))

        # Имя субъекта в этих таблицах почти всегда оформлено вики-ссылкой —
        # это надёжнее любой эвристики по длине. Длина остаётся запасным
        # вариантом для строк без ссылок.
        linked = [clean_html(raw) for raw in raw_cells if "<a " in raw.lower()]
        candidates = [c for c in linked if usable(c)] or [c for c in cells if usable(c)]
        if not candidates:
            continue
        name = re.sub(r"\[\d+\]", "", max(candidates, key=len)).strip(" —–-").strip()
        if len(name) < 4 or len(name) > 300:
            continue
        key = normalize_text(name)
        if key in seen:
            continue
        seen.add(key)
        words = name.split()
        looks_like_person = (
            2 <= len(words) <= 4
            and all(w[:1].isupper() for w in words if w)
            and '"' not in name and "«" not in name
            and not any(m in key for m in ("ооо", "ао ", "фонд", "организац",
                                           "движен", "объединен", "центр",
                                           "институт", "ассоциац", "союз",
                                           "медиа", "проект"))
        )
        entries.append(Entry(
            id=f"wiki-{len(entries) + 1}",
            kind="person" if looks_like_person else "org",
            name=name,
            aliases=extract_quoted(name),
            included_at=included,
        ))
    return entries


MIRROR_BASE = "https://raw.githubusercontent.com/ITSalt/ru-registries-mirror/main/"


def parse_mirror_payload(raw: bytes) -> list[Entry]:
    """Записи из опубликованного зеркала.

    Зеркало отдаёт уже нормализованную схему, поэтому разбирать нечего — нужно
    лишь отфильтровать поля, которых в текущей версии Entry нет: схема зеркала
    может уйти вперёд, и падать на незнакомом ключе было бы глупо.
    """
    payload = json.loads(raw.decode("utf-8"))
    known = set(Entry.__dataclass_fields__)
    return [Entry(**{k: v for k, v in item.items() if k in known})
            for item in payload.get("entries", [])]


def mirror_meta(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    return {k: payload.get(k) for k in
            ("source_url", "source_sha256", "fetched_at", "freshness_window_days")}


def fetch_source_bytes(source: Source) -> bytes:
    """Забирает содержимое источника.

    Прокси применяется только к официальным источникам: он существует ради
    ведомственных хостов, отвечающих лишь с российских адресов. Гнать через
    него зеркала не нужно и рискованно — они доступны глобально, а вот из РФ
    могут быть недоступны как раз они.
    """
    if source.url.startswith("mirror:"):
        key = source.url.split(":", 1)[1]
        return http_get(f"{MIRROR_BASE}data/{key}.json", use_proxy=False)
    if source.url.startswith("wikipedia:"):
        title = source.url.split(":", 1)[1]
        return http_get(WIKIPEDIA_API.format(title=urllib.parse.quote(title)),
                        use_proxy=False)
    return http_get(source.url, use_proxy=(source.trust == "official"))


# --- Каталог реестров --------------------------------------------------------

@dataclass
class Source:
    """Один кандидат-источник реестра.

    `trust` — не про качество парсинга, а про юридическую силу вывода:
      official — первоисточник ведомства. По нему скилл вправе утверждать
                 «упоминаний не найдено».
      attested — зеркало, которое несёт проверяемую цепочку происхождения: URL
                 первоисточника, sha256 его исходных байт и время съёма. Пока
                 съём укладывается в окно свежести реестра, вывод по нему
                 приравнивается к официальному; просроченный снимок
                 автоматически понижается до mirror.
      mirror   — производный источник (энциклопедия, агрегатор) без цепочки
                 происхождения. Данные могут быть полны и свежи, но это не
                 официальная публикация, и вывод не поднимается выше WARN.

    Официальный источник, полученный через прокси пользователя, остаётся
    official: прокси — транспорт, а не источник.
    """
    url: str
    trust: str
    parser: Callable[[bytes], list[Entry]]
    note: str = ""


@dataclass
class RegistrySpec:
    key: str
    title: str
    sources: list[Source]
    note: str = ""


MINJUST_EXPORT = ("https://reestrs.minjust.gov.ru/rest/registry/{rid}/export?")

REGISTRIES: dict[str, RegistrySpec] = {
    "minjust_extremist_materials": RegistrySpec(
        key="minjust_extremist_materials",
        title="Федеральный список экстремистских материалов",
        sources=[Source("https://minjust.gov.ru/uploaded/files/exportfsm.csv",
                        "official", parse_extremist_materials_csv),
                 Source("mirror:minjust_extremist_materials", "attested",
                        parse_mirror_payload, note="зеркало ITSalt")],
        note="Много обобщённых формулировок — высокий риск ложных срабатываний, "
             "подтверждение смысловым слоем обязательно.",
    ),
    "minjust_extremist_orgs": RegistrySpec(
        key="minjust_extremist_orgs",
        title="Перечень организаций, признанных экстремистскими",
        sources=[Source("https://minjust.gov.ru/ru/documents/7822/",
                        "official", parse_extremist_orgs_html),
                 Source("mirror:minjust_extremist_orgs", "attested",
                        parse_mirror_payload, note="зеркало ITSalt")],
        note="Meta Platforms Inc. — пункт 96 этого перечня.",
    ),
    "fsb_terrorist_orgs": RegistrySpec(
        key="fsb_terrorist_orgs",
        title="Единый федеральный список террористических организаций",
        sources=[Source("http://www.fsb.ru/fsb/npd/terror.htm",
                        "official", parse_fsb_terror_html),
                 Source("mirror:fsb_terrorist_orgs", "attested",
                        parse_mirror_payload, note="зеркало ITSalt")],
    ),
    "minjust_foreign_agents": RegistrySpec(
        key="minjust_foreign_agents",
        title="Реестр иностранных агентов",
        sources=[
            Source(MINJUST_EXPORT.format(rid="39b95df9-9a68-6b6d-e1e3-e6388507067e"),
                   "official", parse_minjust_export,
                   note="Отвечает только с российских адресов — нужен прокси "
                        f"({PROXY_ENV}) либо ручной импорт"),
            Source("mirror:minjust_foreign_agents", "attested", parse_mirror_payload,
                   note="зеркало ITSalt, снимается с первоисточника ежедневно"),
            Source("wikipedia:Список «иностранных агентов» (Россия)",
                   "mirror", parse_wikipedia_foreign_agents,
                   note="Волонтёрский перечень, обновляется регулярно; не является "
                        "официальной публикацией"),
        ],
        note="Пополняется еженедельно. По зеркалу вывод не поднимается выше WARN.",
    ),
    "minjust_undesirable_orgs": RegistrySpec(
        key="minjust_undesirable_orgs",
        title="Перечень нежелательных организаций",
        sources=[
            Source(MINJUST_EXPORT.format(rid="c2d1692e-a9f6-5a79-13ee-5da5b42980df"),
                   "official", parse_minjust_export,
                   note="Отвечает только с российских адресов"),
            Source("mirror:minjust_undesirable_orgs", "attested", parse_mirror_payload,
                   note="зеркало ITSalt"),
        ],
        note="Дисклеймер при упоминании не требуется — правило DISC-006 ищет "
             "признаки распространения материалов, а не само упоминание.",
    ),
}


# --- Разрешение источника ----------------------------------------------------


def cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def snapshot_path(key: str) -> Path:
    return SNAPSHOT_DIR / f"{key}.json"


def read_stored(path: Path) -> RegistryData | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RegistryData(**data)
    except Exception:
        return None


def age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400


def fetch_live(spec: RegistrySpec) -> RegistryData:
    """Пробует источники по порядку: сначала официальные, потом зеркала."""
    errors: list[str] = []
    for source in spec.sources:
        try:
            raw = fetch_source_bytes(source)
            entries = source.parser(raw)
            if not entries:
                errors.append(f"{source.url}: разобрано 0 записей")
                continue

            trust = source.trust
            source_url = source.url
            source_sha = hashlib.sha256(raw).hexdigest()
            note = source.note

            if source.url.startswith("mirror:"):
                meta = mirror_meta(raw)
                # Для зеркала значим возраст СЪЁМА с первоисточника, а не момент,
                # когда мы скачали файл: свежий download архивных данных свежести
                # не добавляет.
                age = age_days(meta.get("fetched_at"))
                window = meta.get("freshness_window_days") or DEFAULT_TTL_DAYS
                source_url = meta.get("source_url") or source.url
                source_sha = meta.get("source_sha256") or source_sha
                if age is None or age > window:
                    trust = "mirror"
                    note = (f"снимок старше окна свежести ({age:.0f} д при норме "
                            f"{window} д) — вывод понижен")
                    errors.append(f"{source.url}: {note}")

            return RegistryData(
                registry=spec.key,
                title=spec.title,
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                source_url=source_url,
                source_sha256=source_sha,
                source_trust=trust,
                via_proxy=bool(_proxy_url) and source.trust == "official",
                origin="live",
                stale_days=0.0,
                error=note or None,
                entries=[asdict(e) for e in entries],
            )
        except Exception as exc:
            errors.append(f"{source.url[:70]}: {type(exc).__name__}: {exc}")
    return RegistryData(registry=spec.key, title=spec.title, origin="unavailable",
                        error="; ".join(errors))


def load_registry(key: str, ttl_days: float = DEFAULT_TTL_DAYS,
                  force_update: bool = False, offline: bool = False) -> RegistryData:
    """Разрешает реестр по цепочке живой источник -> кэш -> локальный снапшот.

    Возвращаемое значение всегда несёт `origin` и `stale_days`: без них вызывающий
    код не сможет отличить проверку по актуальным данным от проверки по
    архивному снимку, а для юридического вывода это принципиальная разница.
    """
    spec = REGISTRIES[key]
    cached = read_stored(cache_path(key))
    cached_age = age_days(cached.fetched_at) if cached else None

    fresh_enough = (cached is not None and cached_age is not None
                    and cached_age <= ttl_days and cached.entries)
    if not offline and (force_update or not fresh_enough):
        live = fetch_live(spec)
        if live.origin == "live":
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path(key).write_text(
                json.dumps(asdict(live), ensure_ascii=False), encoding="utf-8")
            return live
        if cached and cached.entries:
            cached.origin = "cache"
            cached.stale_days = cached_age
            cached.error = live.error
            return cached
        snap = read_stored(snapshot_path(key))
        if snap and snap.entries:
            snap.origin = "snapshot"
            snap.stale_days = age_days(snap.fetched_at)
            snap.error = live.error
            return snap
        return live

    if cached and cached.entries:
        cached.origin = "cache"
        cached.stale_days = cached_age
        return cached
    snap = read_stored(snapshot_path(key))
    if snap and snap.entries:
        snap.origin = "snapshot"
        snap.stale_days = age_days(snap.fetched_at)
        return snap
    return RegistryData(registry=key, title=spec.title, origin="unavailable",
                        error="нет ни кэша, ни снапшота")


# --- Поиск упоминаний --------------------------------------------------------

def stem(word: str) -> str:
    """Грубая основа слова.

    Русские фамилии, имена и названия склоняются в окончании, поэтому для поиска
    достаточно отрезать хвост и разрешить любое продолжение. Морфологический
    словарь дал бы точнее, но потянул бы зависимость с базой форм — при том что
    все совпадения всё равно проходят подтверждение смысловым слоем.
    """
    if len(word) <= 4:
        return word
    if len(word) <= 6:
        return word[:-1]
    return word[:-2]


def phrase_tokens(phrase: str) -> list[str]:
    """Значимые токены фразы — то, из чего реально строится поиск.

    Считать «слова» простым разбиением по пробелам нельзя: в реестрах полно
    строк вида «Система – …………!», где по пробелам выходит три слова, а искать
    можно ровно одно. Уверенность совпадения должна опираться на эти токены,
    иначе однословный поиск получит вес многословного.
    """
    return [w for w in re.split(r"[^0-9a-zа-я]+", normalize_text(phrase)) if w]


def build_pattern(phrase: str, strict: bool = False) -> re.Pattern[str] | None:
    """Строит регулярное выражение, устойчивое к склонению.

    Служебные слова («и», «за», «на») остаются в шаблоне буквально: выбросить
    их нельзя — без них «Конгресс народов Ичкерии и Дагестана» перестаёт
    находиться в тексте, где это название написано целиком.

    `strict` отключает запас на склонение. Он нужен фразам из обиходных слов:
    для них хвост `[а-я]{0,4}` — не устойчивость к падежу, а прямой источник
    ложных срабатываний, потому что превращает «вот так» в «вот такой».
    """
    words = phrase_tokens(phrase)
    if not words:
        return None
    parts = []
    for word in words:
        if strict or len(word) <= 2 or word.isdigit() or re.fullmatch(r"[a-z]+", word):
            parts.append(re.escape(word))
        else:
            parts.append(re.escape(stem(word)) + r"[а-я]{0,4}")
    return re.compile(r"\b" + r"[\s\-\"]+".join(parts) + r"\b")


@dataclass
class Match:
    entry_id: str
    entry_name: str
    matched_text: str
    matched_via: str        # name | core | alias
    confidence: str         # high | medium | low
    start: int
    context: str


class RegistryMatcher:
    """Ищет упоминания записей реестра в тексте страницы.

    Совпадения намеренно ранжируются по уверенности, а не фильтруются: правила
    группы B — гибридные, и решение «это действительно та организация» принимает
    смысловой слой. Задача матчера — не пропустить упоминание и честно
    сообщить, насколько находка надёжна.
    """

    def __init__(self, data: RegistryData, min_alias_len: int = 6) -> None:
        self.data = data
        self.min_alias_len = min_alias_len
        # (шаблон, запись, способ, уверенность, требуется ли подтверждение окружением)
        self._patterns: list[tuple[re.Pattern[str], dict[str, Any], str, str, bool]] = []
        for raw in data.entries:
            entry = raw if isinstance(raw, dict) else asdict(raw)
            # Исключённые из реестра не порождают обязанности маркировать
            # упоминание: искать их — значит выдавать ложные нарушения.
            if entry.get("excluded_at"):
                continue
            is_material = entry.get("kind") == "material"
            for alias in entry.get("aliases") or []:
                # Записи федерального списка экстремистских материалов публикуются
                # с вымаранным текстом («Система – …………!»). От такой строки
                # остаётся одно обиходное слово, которое найдётся на любом сайте.
                if "…" in alias or "..." in alias:
                    continue
                norm = normalize_text(alias)
                tokens = phrase_tokens(alias)
                if not tokens or len(norm) < min_alias_len or norm in STOP_ALIASES:
                    continue
                # Описание материала — не имя собственное: искать его по
                # обрывкам бессмысленно, поэтому порог здесь заметно выше.
                if is_material and (len(tokens) < 3 or len(norm) < 15):
                    continue
                # Однословный псевдоним — слабый признак: короткие такие слова
                # отбрасываем совсем, длинные берём с низкой уверенностью.
                # Фраза из обиходных слов слаба ровно так же, сколько бы слов в
                # ней ни было: «Вот так» — название телеканала-иноагента и
                # одновременно кусок любого предложения.
                weak = weak_phrase(alias)
                if len(tokens) == 1:
                    if len(norm) < 8:
                        continue
                    confidence = "low"
                elif weak:
                    confidence = "low"
                else:
                    confidence = "medium" if is_material else "high"
                pattern = build_pattern(alias, strict=weak)
                if pattern:
                    self._patterns.append(
                        (pattern, entry, "alias", confidence,
                         len(tokens) == 1 or weak))

            name = entry.get("name") or ""
            if is_material:
                # У материала нет наименования — есть описание на несколько строк
                # («Изображение рисунка животного, напоминающего…»). Искать его
                # как фразу бесполезно: на странице оно не воспроизводится.
                continue
            if entry.get("kind") == "person":
                for pattern, confidence in self._person_patterns(name):
                    self._patterns.append((pattern, entry, "name", confidence, False))
            else:
                # Полное наименование ищем ради точности, ядро — ради полноты:
                # целиком длинное официальное название на странице не пишет никто.
                for candidate, via in ((name, "name"), (core_name(name), "core")):
                    if len(normalize_text(candidate)) < 10 or len(phrase_tokens(candidate)) < 2:
                        continue
                    weak = weak_phrase(candidate)
                    pattern = build_pattern(candidate, strict=weak)
                    if pattern:
                        self._patterns.append(
                            (pattern, entry, via, "low" if weak else "high", weak))

    @staticmethod
    def _person_patterns(name: str) -> list[tuple[re.Pattern[str], str]]:
        """ФИО целиком и «Фамилия И. О.» — два способа, которыми человека
        называют в тексте. Одна фамилия сознательно не ищется: однофамильцы
        дали бы поток ложных срабатываний."""
        words = [w for w in re.split(r"\s+", normalize_text(name)) if len(w) > 1]
        out: list[tuple[re.Pattern[str], str]] = []
        if len(words) >= 3:
            surname, first, patronymic = words[0], words[1], words[2]
            # Фамилия и отчество склоняются предсказуемо, а короткие имена — нет:
            # «Лев» в родительном даёт «Льва», и усечение основы не помогает.
            # Поэтому имя в середине — свободное слово, а якорями служат
            # фамилия и отчество: вдвоём они опознают человека не хуже.
            full = re.compile(
                r"\b" + re.escape(stem(surname)) + r"[а-я]{0,4}\s+"
                + r"[а-яё]{2,14}\s+"
                + re.escape(stem(patronymic)) + r"[а-я]{0,4}\b"
            )
            out.append((full, "high"))
            initials = re.compile(
                r"\b" + re.escape(stem(surname)) + r"[а-я]{0,4}\s+"
                + re.escape(first[0]) + r"\.\s*" + re.escape(patronymic[0]) + r"\."
            )
            out.append((initials, "medium"))
        elif len(words) == 2:
            pattern = build_pattern(" ".join(words))
            if pattern:
                out.append((pattern, "medium"))
        return out

    # Слова, рядом с которыми однословное название действительно читается как
    # имя собственное, а не как обычное существительное.
    ORG_CONTEXT = ("центр", "фонд", "организаци", "движени", "объединени",
                   "ассоциаци", "союз", "партия", "компани", "группа", "проект",
                   "издани", "телеканал", "газет", "журнал", "агентств", "клуб",
                   "общество", "движение", "инициатив", "платформ", "сообществ")

    @staticmethod
    def _looks_like_name(norm: str, start: int, end: int) -> bool:
        """Читается ли совпадение как название, а не как обычные слова.

        «Действие» в реестре — название комьюнити-центра, но в тексте
        пользовательского соглашения это просто существительное, и совпадение по
        основе ловит «действий», «действия», «действием». «Вот так» — телеканал
        из реестра иноагентов, и он же — половина фразы «дала вот такой
        результат». Отличить одно от другого по самой строке нельзя: название
        либо стоит в кавычках, либо ему предшествует слово, обозначающее род
        организации, — и только это отличие здесь и проверяется.
        """
        before = norm[max(0, start - 45):start]
        after = norm[end:end + 2]
        if before.rstrip().endswith('"') and after.lstrip().startswith('"'):
            return True
        return any(word in before for word in RegistryMatcher.ORG_CONTEXT)

    def find(self, text: str, context_chars: int = 160) -> list[Match]:
        norm = normalize_text(text)
        order = {"high": 0, "medium": 1, "low": 2}
        raw_hits: list[tuple[int, int, Match]] = []

        for pattern, entry, via, confidence, guarded in self._patterns:
            for hit in pattern.finditer(norm):
                if guarded and not self._looks_like_name(norm, hit.start(), hit.end()):
                    continue
                lo = max(0, hit.start() - context_chars)
                hi = min(len(norm), hit.end() + context_chars)
                raw_hits.append((hit.start(), hit.end(), Match(
                    entry_id=entry["id"],
                    entry_name=entry["name"],
                    matched_text=hit.group(0),
                    matched_via=via,
                    confidence=confidence,
                    start=hit.start(),
                    context=norm[lo:hi],
                )))

        # На одном месте текста нередко срабатывают несколько записей: короткий
        # псевдоним одной организации попадает внутрь полного названия другой.
        # Оставляем самое длинное и самое уверенное совпадение на отрезок —
        # иначе отчёт наполняется дублями, указывающими на чужие организации.
        raw_hits.sort(key=lambda h: (-(h[1] - h[0]), order.get(h[2].confidence, 3)))
        kept: list[tuple[int, int, Match]] = []
        for start, end, match in raw_hits:
            if any(start < k_end and end > k_start for k_start, k_end, _ in kept):
                continue
            kept.append((start, end, match))

        matches = [m for _, _, m in kept]
        matches.sort(key=lambda m: (order.get(m.confidence, 3), m.start))
        return matches


# --- CLI ---------------------------------------------------------------------


TRUST_LABEL = {"official": "официальный", "attested": "зеркало+",
               "mirror": "ЗЕРКАЛО", None: "—"}


def cmd_status(args: argparse.Namespace) -> int:
    print(f"{'реестр':<32} {'откуда':<12} {'доверие':<12} {'записей':>8}  {'возраст':>9}")
    print("-" * 82)
    for key in REGISTRIES:
        data = load_registry(key, ttl_days=args.ttl, offline=True)
        age = f"{data.stale_days:.1f} д" if data.stale_days is not None else "—"
        trust = TRUST_LABEL.get(data.source_trust, data.source_trust or "—")
        print(f"{key:<32} {data.origin:<12} {trust:<12} {len(data.entries):>8}  {age:>9}")
    mirrors = [k for k in REGISTRIES
               if load_registry(k, ttl_days=args.ttl, offline=True).source_trust == "mirror"]
    if mirrors:
        print("\nЗагружено из неофициальных источников: " + ", ".join(mirrors))
        print("По ним вывод «упоминаний не найдено» не поднимается выше WARN.")
    print(f"\nкэш: {CACHE_DIR}")
    print(f"снапшоты: {SNAPSHOT_DIR}")
    print(f"прокси: {_proxy_url or 'не задан'}  (переменная {PROXY_ENV})")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Проверяет, какие источники доступны с текущей точки выхода.

    Ведомственные хосты отвечают не отовсюду, и диагностировать это по
    сообщению «реестр недоступен» неудобно. Здесь видно сразу, что именно
    не отвечает и помогает ли прокси.
    """
    print(f"прокси: {_proxy_url or 'не задан'}\n")
    print(f"{'реестр':<30} {'доверие':<11} {'код':<8} источник")
    print("-" * 96)
    for key, spec in REGISTRIES.items():
        for source in spec.sources:
            try:
                raw = fetch_source_bytes(source)
                status = f"ok {len(raw) // 1024}К"
            except Exception as exc:
                status = type(exc).__name__[:8]
            trust = TRUST_LABEL.get(source.trust, source.trust)
            print(f"{key:<30} {trust:<11} {status:<8} {source.url[:48]}")
            if source.note:
                print(f"{'':<51}{source.note[:44]}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    keys = [args.registry] if args.registry else list(REGISTRIES)
    failures = 0
    for key in keys:
        data = load_registry(key, ttl_days=args.ttl, force_update=True)
        mark = {"live": "обновлён", "cache": "из кэша", "snapshot": "из снапшота",
                "unavailable": "НЕДОСТУПЕН"}[data.origin]
        print(f"{key:<32} {mark:<14} записей: {len(data.entries)}")
        if data.error:
            print(f"    {data.error[:300]}")
        if data.origin == "unavailable":
            failures += 1
    if failures:
        print(f"\nНедоступно реестров: {failures}. Проверка по ним даст статус "
              f"UNKNOWN — это корректнее, чем PASS по отсутствующим данным.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Ручной ввод выгрузки, когда ведомственный хост недоступен."""
    spec = REGISTRIES[args.registry]
    raw = Path(args.file).expanduser().read_bytes()
    official = next((s for s in spec.sources if s.trust == "official"), spec.sources[0])
    entries = official.parser(raw)
    if not entries:
        print("разобрано 0 записей — проверьте формат файла", file=sys.stderr)
        return 1
    data = RegistryData(
        registry=spec.key, title=spec.title,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_url=f"file://{Path(args.file).expanduser()}",
        source_sha256=hashlib.sha256(raw).hexdigest(),
        # Файл выгружен пользователем с официальной страницы реестра, поэтому
        # уровень доверия тот же, что у прямой загрузки.
        source_trust="official",
        origin="live", stale_days=0.0,
        entries=[asdict(e) for e in entries],
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(spec.key).write_text(json.dumps(asdict(data), ensure_ascii=False),
                                   encoding="utf-8")
    print(f"{spec.key}: импортировано записей {len(entries)} -> {cache_path(spec.key)}")
    if args.as_snapshot:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path(spec.key).write_text(
            json.dumps(asdict(data), ensure_ascii=False), encoding="utf-8")
        print(f"    записан также снапшот: {snapshot_path(spec.key)}")
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    data = load_registry(args.registry, ttl_days=args.ttl, offline=args.offline)
    if not data.entries:
        print(f"реестр {args.registry} недоступен: {data.error}", file=sys.stderr)
        return 1
    text = Path(args.text_file).expanduser().read_text(encoding="utf-8", errors="replace")
    matcher = RegistryMatcher(data)
    matches = matcher.find(text)
    print(f"реестр: {data.title} ({data.origin}, записей {len(data.entries)})")
    print(f"совпадений: {len(matches)}\n")
    for m in matches[: args.limit]:
        print(f"[{m.confidence}] {m.entry_name[:80]}")
        print(f"    найдено: {m.matched_text!r} (через {m.matched_via})")
        print(f"    контекст: ...{m.context[:200]}...\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Государственные реестры для проверки упоминаний")
    parser.add_argument("--ttl", type=float, default=DEFAULT_TTL_DAYS,
                        help="возраст кэша в днях, после которого он считается устаревшим")
    parser.add_argument("--proxy", default=None,
                        help=f"прокси для ведомственных хостов, например "
                             f"http://user:pass@vps:3128 (или переменная {PROXY_ENV}). "
                             f"Применяется только к загрузке реестров, обход сайта идёт напрямую")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="что загружено и насколько свежее")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("probe", help="проверить доступность источников с этой машины")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("update", help="обновить из первоисточника")
    p.add_argument("--registry", choices=list(REGISTRIES))
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("import", help="загрузить выгрузку из локального файла")
    p.add_argument("--registry", choices=list(REGISTRIES), required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--as-snapshot", action="store_true",
                   help="сохранить также как локальный снапшот (в релиз не входит)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("match", help="проверить текст на упоминания")
    p.add_argument("--registry", choices=list(REGISTRIES), required=True)
    p.add_argument("--text-file", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offline", action="store_true")
    p.set_defaults(func=cmd_match)

    args = parser.parse_args()
    if args.proxy:
        set_proxy(args.proxy)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
