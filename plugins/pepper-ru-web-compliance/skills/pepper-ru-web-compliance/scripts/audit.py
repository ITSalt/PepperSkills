#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["h11>=0.16,<0.17", "playwright==1.56.0"]
# ///
"""One explicit network launch; all later analysis uses local evidence."""
import argparse
import base64
import json
import hashlib
import sys
from dataclasses import asdict
from pathlib import Path

import audit_transport as transport
import collect
import detect
import registries


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def snapshot_registries(out, inn=None):
    for key in registries.REGISTRIES:
        data = registries.load_registry(key, force_update=True)
        save(out / "registries" / (key + ".json"), asdict(data))
    ctx = detect.Context(out, inn=inn)
    detect.DETECTORS["requisites"](ctx)
    if ctx.inn:
        result = {"inn": ctx.inn}
        try:
            response = transport.current().registry("operators", ctx.inn)
            if response is not None:
                raw, metadata = response
                result.update(metadata)
            else:
                address = ctx.sig["rkn_operators"]["search_url"].format(inn=ctx.inn)
                raw = registries.http_get(address, timeout=40)
                result.update(source_url=address, source_trust="official", fetched_at=collect.now_iso(),
                              source_sha256=hashlib.sha256(raw).hexdigest())
            result["body_base64"] = base64.b64encode(raw).decode()
        except Exception as exc:
            result["error"] = exc.code if isinstance(exc, transport.NetworkError) else type(exc).__name__
        save(out / "registries/operators.json", result)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Локальный аудит через РФ-выход: один сетевой запуск, затем офлайн-анализ")
    ap.add_argument("target", nargs="?")
    ap.add_argument("--out", default="artifacts")
    ap.add_argument("--findings", default="findings.json")
    ap.add_argument("--inn")
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=45000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--source-dir")
    ap.add_argument("--offline", action="store_true", help="только повторная обработка сохранённых артефактов; без выдачи сессии")
    ap.add_argument("--mode", choices=("managed", "custom"))
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    if not args.offline:
        if not args.target:
            ap.error("target обязателен для сетевого запуска")
        # Do not combine stale evidence from different network sessions.
        if out.exists() and any(out.iterdir()):
            ap.error("для нового сбора нужен пустой --out; для готовых артефактов используйте --offline")
        if args.max_pages < 1 or args.max_pages > 100:
            ap.error("--max-pages: от 1 до 100")
        try:
            transport.preflight(browser=not args.no_browser)
        except Exception as exc:
            print(f"Подготовка не пройдена ({type(exc).__name__}); квота не списана. Установите зависимости и Chromium.", file=sys.stderr)
            return 2
        network = transport.NetworkSession(collect.normalize_target(args.target), mode=args.mode)
        try:
            with network:
                collect.collect(args)
                snapshot_registries(out, args.inn)
                network.status()
        except Exception as exc:
            network.metadata.update(complete=False, transport_error=(
                exc.code if isinstance(exc, transport.NetworkError) else type(exc).__name__))
            print(f"Сетевой этап: {network.metadata['transport_error']}. "
                  f"Retry-After: {getattr(exc, 'retry_after', None) or 'не указан'}. "
                  "Автоматического нового запуска нет. Для custom-прокси нужен новый пустой --out; "
                  "транспорт будет отмечен как custom.", file=sys.stderr)
        finally:
            collect.update_network(out, network.metadata)
        if not (out / "manifest.json").exists():
            return 2
    # Force this phase offline even when a legacy registry proxy is configured.
    registries.set_proxy(None)
    report = detect.run(detect.Context(out, inn=args.inn))
    save(Path(args.findings), report)
    return 0 if report.get("network", {}).get("complete", args.offline) else 2


if __name__ == "__main__":
    raise SystemExit(main())
