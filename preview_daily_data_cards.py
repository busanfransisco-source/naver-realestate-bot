"""Build a local 30-card preview; never replace the live 26-card briefing.

The Seoul and KPX cards remain visibly unavailable until their approved API
keys and live response checks are complete. This script does not send messages.
"""

from datetime import datetime, timezone
from pathlib import Path
import re

import requests

from daily_data_card_sources import (
    SourceUnavailable,
    build_crypto_digest,
    fetch_crypto_history,
    fetch_wikimedia_digest,
)
from gen_briefing import build_html


WIKI_TITLES = ("부동산", "금리", "한국은행", "비트코인", "아파트")
OUTPUT = Path("tmp/briefing-30-preview.html")
PENDING_SEOUL = "인증키 준비 전 · 원자료 미수집\n\n자동공유 비활성\n출처: 서울 열린데이터광장"
PENDING_KPX = "활용승인·서비스키 준비 전 · 원자료 미수집\n\n자동공유 비활성\n출처: 한국전력거래소"


def preview_contents(session=requests, *, today_utc=None):
    today_utc = today_utc or datetime.now(timezone.utc).date()
    contents = {"seoulcommerce": PENDING_SEOUL, "kpxpower": PENDING_KPX}
    try:
        history = fetch_crypto_history(session)
        source_day = history[0][0]
        if not 0 <= (today_utc - source_day).days <= 1:
            raise SourceUnavailable("원자료 기준일이 오래됐거나 미래입니다")
        contents["cryptofear"] = build_crypto_digest(history)
    except (requests.RequestException, SourceUnavailable, ValueError):
        contents["cryptofear"] = "집계 대기 · 새 원자료 검증 실패\n\n자동공유 비활성\n출처: Alternative.me"
    try:
        digest = fetch_wikimedia_digest(session, WIKI_TITLES, today=today_utc)
        match = re.search(r"집계 마감: (\d{4}-\d{2}-\d{2}) \(UTC\)", digest)
        if not match or not 1 <= (today_utc - datetime.fromisoformat(match.group(1)).date()).days <= 3:
            raise SourceUnavailable("공통 집계 마감일이 오래됐거나 미래입니다")
        contents["wikiinterest"] = digest
    except (requests.RequestException, SourceUnavailable, ValueError):
        contents["wikiinterest"] = "집계 대기 · 새 원자료 검증 실패\n\n자동공유 비활성\n출처: Wikimedia Analytics API"
    return contents


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    html = build_html(new_data_contents=preview_contents())
    OUTPUT.write_text("<!-- LOCAL PREVIEW ONLY: DO NOT DEPLOY OR AUTO-SEND -->\n" + html, encoding="utf-8")
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()
