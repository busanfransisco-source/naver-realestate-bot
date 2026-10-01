"""Source-checked draft collectors for the proposed daily data briefing cards.

These functions do not change the live briefing or send KakaoTalk messages.
Each rendered value carries its source date; callers must not relabel it as today.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import requests


CRYPTO_URL = "https://api.alternative.me/fng/"
WIKIMEDIA_BASE = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "ko.wikipedia.org/all-access/user"
)
WIKIMEDIA_USER_AGENT = (
    "RealEstateBriefingDataCards/0.1 "
    "(https://github.com/busanfransisco-source/naver-realestate-bot)"
)
CRYPTO_LABELS = {
    "Extreme Fear": "극도의 공포",
    "Fear": "공포",
    "Neutral": "중립",
    "Greed": "탐욕",
    "Extreme Greed": "극도의 탐욕",
}
SEOUL_COMMERCE_LEVEL_PREFIXES = ("한산", "보통", "바쁜", "분주")


class SourceUnavailable(ValueError):
    """A source did not provide enough trustworthy data for a new card."""


def parse_seoul_commerce_payload(payload, expected_area):
    """Validate one place's official citydata_cmrcl JSON response.

    The public sample key exposes only 광화문·덕수궁. Parsing one place is not
    evidence that the planned 82-place card is ready for release.
    """
    if not isinstance(payload, dict) or payload.get("RESULT", {}).get("resultCode") != "INFO-000":
        raise SourceUnavailable("서울 상권 API가 정상 응답을 주지 않았습니다")
    if payload.get("AREA_NM") != expected_area:
        raise SourceUnavailable("요청 장소와 응답 장소가 다릅니다")
    commerce = payload.get("LIVE_CMRCL_STTS")
    if not isinstance(commerce, dict):
        raise SourceUnavailable("서울 상권 현황이 없습니다")
    try:
        observed_at = datetime.strptime(commerce["CMRCL_TIME"], "%Y%m%d %H%M")
        level = commerce["AREA_CMRCL_LVL"]
        payments = int(commerce["AREA_SH_PAYMENT_CNT"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceUnavailable("서울 상권 현황 형식이 잘못됐습니다") from exc
    if (not isinstance(level, str) or
            not level.startswith(SEOUL_COMMERCE_LEVEL_PREFIXES) or payments < 0):
        raise SourceUnavailable("서울 상권 현황 값이 유효하지 않습니다")
    return {"area": expected_area, "observed_at_kst": observed_at,
            "relative_level": level, "shinhan_payment_count": payments}


def _request_json(session, url, *, params=None, headers=None):
    response = session.get(url, params=params, headers=headers, timeout=25)
    response.raise_for_status()
    return response.json()


def fetch_crypto_history(session=requests):
    """Return 30 distinct daily Bitcoin sentiment observations, newest first."""
    payload = _request_json(
        session, CRYPTO_URL, params={"limit": 31, "format": "json"}
    )
    if payload.get("metadata", {}).get("error"):
        raise SourceUnavailable("Alternative.me API가 오류를 반환했습니다")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) < 30:
        raise SourceUnavailable("비트코인 심리 지수 30일치가 부족합니다")
    by_day = {}
    for row in rows:
        try:
            day = datetime.fromtimestamp(int(row["timestamp"]), timezone.utc).date()
            value = int(row["value"])
            classification = str(row["value_classification"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise SourceUnavailable("비트코인 심리 지수 형식이 잘못됐습니다") from exc
        if not 0 <= value <= 100 or classification not in CRYPTO_LABELS:
            raise SourceUnavailable("비트코인 심리 지수 값이 유효하지 않습니다")
        by_day.setdefault(day, (value, classification))
    days = sorted(by_day, reverse=True)[:30]
    if len(days) < 30 or any(
        older != newer - timedelta(days=1)
        for newer, older in zip(days, days[1:])
    ):
        raise SourceUnavailable("비트코인 심리 지수의 일별 자료가 이어지지 않습니다")
    return [(day, *by_day[day]) for day in days]


def build_crypto_digest(history):
    """Use the API's UTC date label, never the page-generation date."""
    if len(history) < 30:
        raise SourceUnavailable("비트코인 심리 지수 30일치가 부족합니다")
    day, value, classification = history[0]
    previous = history[1]
    if previous[0] != day - timedelta(days=1):
        raise SourceUnavailable("전일 비교 자료가 없습니다")
    values = [row[1] for row in history[:30]]
    lowest, highest = min(values), max(values)
    change = value - previous[1]
    change_text = f"{change:+d}점" if change else "변동 없음"
    if lowest == highest:
        position = "30일간 같은 점수"
    else:
        position = f"최저~최고 구간의 {(value-lowest)/(highest-lowest)*100:.0f}% 지점"
    return "\n".join(
        [
            "비트코인 공포·탐욕 지수",
            f"원자료 기준일: {day.isoformat()} (UTC)",
            "",
            f"{value}/100 · {CRYPTO_LABELS[classification]} (전일 {change_text})",
            f"최근 30일: {lowest}~{highest}점 · 현재 {position}",
            "",
            "※ 비트코인 시장 심리 지표이며 주식시장 전체 심리가 아닙니다.",
            "출처: Alternative.me (Crypto Fear & Greed Index)",
        ]
    )


def fetch_wikimedia_history(session, title, start, end):
    """Fetch one Korean Wikipedia article's user page views by UTC day."""
    if start > end:
        raise ValueError("시작일이 종료일보다 늦습니다")
    article = quote(title.replace(" ", "_"), safe="")
    url = (
        f"{WIKIMEDIA_BASE}/{article}/daily/"
        f"{start:%Y%m%d}/{end:%Y%m%d}"
    )
    payload = _request_json(
        session, url, headers={"User-Agent": WIKIMEDIA_USER_AGENT}
    )
    rows = payload.get("items")
    if not isinstance(rows, list) or not rows:
        raise SourceUnavailable(f"위키백과 '{title}' 조회수 자료가 없습니다")
    by_day = {}
    for row in rows:
        try:
            stamp = str(row["timestamp"])
            day = datetime.strptime(stamp, "%Y%m%d00").date()
            views = int(row["views"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable(f"위키백과 '{title}' 조회수 형식이 잘못됐습니다") from exc
        if views < 0 or row.get("article", "").replace("_", " ") != title.replace("_", " "):
            raise SourceUnavailable(f"위키백과 '{title}' 조회수 대상이 맞지 않습니다")
        by_day[day] = views
    return by_day


def build_wikimedia_digest(histories, *, min_weekly_views=100):
    """Compare two completed 7-day windows ending on a shared UTC day."""
    if not histories:
        raise SourceUnavailable("비교할 위키백과 문서가 없습니다")
    common = set.intersection(*(set(history) for history in histories.values()))
    valid_days = [
        day for day in common
        if all(day - timedelta(days=offset) in common for offset in range(1, 14))
    ]
    if not valid_days:
        raise SourceUnavailable("모든 문서에 공통인 14일치 집계가 없습니다")
    day = max(valid_days)
    ranked = []
    for title, history in histories.items():
        recent = sum(history[day - timedelta(days=offset)] for offset in range(7))
        previous = sum(
            history[day - timedelta(days=offset)] for offset in range(7, 14)
        )
        if recent >= min_weekly_views and previous >= min_weekly_views / 2:
            change = (recent / previous - 1) * 100
            ranked.append((change, recent, previous, title))
    ranked.sort(reverse=True)
    lines = [
        "경제 주제 읽기 관심도",
        f"집계 마감: {day.isoformat()} (UTC) · 한국어 위키백과 문서 조회수",
        "비교: 최근 7일 합계 vs 직전 7일 합계",
        "",
    ]
    growing = [row for row in ranked if row[0] > 0][:3]
    if growing:
        lines.append("조회가 늘어난 문서")
        lines.extend(
            f"{title} {recent:,}회 (직전 7일 {previous:,}회, +{change:.0f}%)"
            for change, recent, previous, title in growing
        )
    else:
        lines.append("표본 기준을 넘는 관심 증가 문서가 없습니다.")
    lines.extend(
        [
            "",
            f"비교 대상: 사전 지정한 {len(histories)}개 문서 · 최근 7일 100회 이상만 표시",
            "※ 검색량이나 매수 수요가 아닌 문서 조회수입니다.",
            "출처: Wikimedia Analytics API (CC0)",
        ]
    )
    return "\n".join(lines)


def fetch_wikimedia_digest(session, titles, *, today=None):
    """Allow the UTC source at least one completed day; never fabricate 0 views."""
    if not titles or len(set(titles)) != len(titles):
        raise ValueError("중복 없는 위키백과 문서 목록이 필요합니다")
    today = today or datetime.now(timezone.utc).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=20)
    histories = {
        title: fetch_wikimedia_history(session, title, start, end)
        for title in titles
    }
    return build_wikimedia_digest(histories)
