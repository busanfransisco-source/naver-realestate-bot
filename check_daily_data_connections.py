"""Non-secret live diagnostics; no publishing or message delivery."""

from datetime import datetime, timedelta, timezone
import json
import socket
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import requests

import daily_data_card_sources as sources
from local_api_secrets import load_secret


def check_connections():
    now = datetime.now(timezone(timedelta(hours=9)))
    report = {"checked_at_kst": now.isoformat(), "sources": {}}
    results = report["sources"]

    def run(name, action):
        try:
            results[name] = action()
        except sources.SourceUnavailable as exc:
            results[name] = {"status": "failed", "reason": str(exc)}
        except Exception as exc:
            # requests exceptions can contain a credential-bearing URL.
            results[name] = {"status": "failed", "reason": type(exc).__name__}

    def crypto():
        history = sources.fetch_crypto_history()
        sources.build_crypto_digest(history)
        return {"status": "ok", "source_date_utc": str(history[0][0]), "days": len(history)}

    def wiki():
        titles = tuple(t for group in sources.WIKIMEDIA_TOPICS.values() for t in group)
        digest = sources.fetch_wikimedia_digest(requests, titles)
        return {"status": "ok", "documents": len(titles), "source_line": digest.splitlines()[1]}

    def supply():
        key = load_secret("kpx")
        if not key:
            return {"status": "missing_key"}
        response = requests.get(sources.KPX_SUPPLY_URL, params={"ServiceKey": key}, timeout=25)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        code = root.findtext(".//resultCode")
        if code != "00":
            return {"status": "failed", "http_status": response.status_code,
                    "result_code": code,
                    "reason": "provider_does_not_recognize_key" if code == "30" else "provider_error"}
        actual = sources.parse_kpx_supply_xml(response.text)
        return {"status": "ok", "source_time_kst": str(actual["observed_at_kst"])}

    def supply_network():
        host = "openapi.kpx.or.kr"
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443)})
        try:
            with socket.create_connection((host, 443), timeout=8):
                return {"status": "ok", "host": host, "dns_addresses": addresses,
                        "tcp_port": 443}
        except OSError as exc:
            return {"status": "failed", "host": host, "dns_addresses": addresses,
                    "tcp_port": 443, "reason": type(exc).__name__}

    def price():
        key = load_secret("kpx")
        if not key:
            return {"status": "missing_key"}
        rows = sources.fetch_kpx_prices(requests, key, now.date())
        return {"status": "ok", "records": len(rows),
                "dates_kst": sorted({str(row["date_kst"]) for row in rows}),
                "areas": sorted({row["area"] for row in rows})}

    def seoul():
        key = load_secret("seoul")
        # Exact names from Seoul's official 82-place catalogue (2026-04-14).
        areas = ("광화문·덕수궁", "홍대입구역(2호선)", "강남역") if key else ("광화문·덕수궁",)
        observations = []
        for area in areas:
            url = f"http://openapi.seoul.go.kr:8088/{key or 'sample'}/json/citydata_cmrcl/1/5/{quote(area)}"
            response = requests.get(url, timeout=25)
            response.raise_for_status()
            actual = sources.parse_seoul_commerce_payload(response.json(), area)
            observations.append({"area": area,
                                 "source_time_kst": str(actual["observed_at_kst"])})
        return {"status": "ok" if key else "sample_only",
                "private_key_stored": bool(key), "tested_places": len(areas),
                "observations": observations}

    for name, action in (("crypto", crypto), ("wikimedia", wiki),
                         ("kpx_supply_network", supply_network),
                         ("kpx_supply", supply), ("kpx_price", price), ("seoul", seoul)):
        run(name, action)
    return report


if __name__ == "__main__":
    report = check_connections()
    output = Path("tmp/api-connection-status.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
