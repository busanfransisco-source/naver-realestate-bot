"""Build a local 29-card preview; never replace the live 26-card briefing.

Seoul remains unavailable until its full freshness checks are complete.
Power is excluded and is never collected. This script does not send messages.
"""

from datetime import datetime, timezone
from pathlib import Path
import re

import requests

from daily_data_card_sources import (
    SourceUnavailable,
    WIKIMEDIA_TOPICS,
    build_crypto_digest,
    fetch_crypto_history,
    fetch_wikimedia_digest,
)
from gen_briefing import build_html


WIKI_TITLES = tuple(title for titles in WIKIMEDIA_TOPICS.values() for title in titles)
OUTPUT = Path("tmp/briefing-29-preview.html")
LEGACY_OUTPUT = Path("tmp/briefing-30-preview.html")
PENDING_SEOUL = "정식 키 발급 완료 · 전체 상권 최신성 검증 중\n\n자동공유 비활성\n출처: 서울 열린데이터광장"


def preview_contents(session=requests, *, today_utc=None):
    today_utc = today_utc or datetime.now(timezone.utc).date()
    contents = {"seoulcommerce": PENDING_SEOUL}
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
    rendered = "<!-- LOCAL PREVIEW ONLY: 29 CARDS, POWER EXCLUDED; DO NOT DEPLOY OR AUTO-SEND -->\n" + html
    OUTPUT.write_text(rendered, encoding="utf-8")
    # Refresh the previously opened preview too, so it cannot retain the removed card.
    LEGACY_OUTPUT.write_text(rendered, encoding="utf-8")
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()
