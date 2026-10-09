"""Source-checked draft collectors for the proposed daily data briefing cards.

These functions do not change the live briefing or send KakaoTalk messages.
Each rendered value carries its source date; callers must not relabel it as today.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import isfinite
from html.parser import HTMLParser
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from xml.etree import ElementTree

import requests
from seoul_commerce_catalogue import SEOUL_COMMERCE_CODES


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
KPX_SUPPLY_URL = (
    "https://openapi.kpx.or.kr/openapi/sukub5mMaxDatetime/"
    "getSukub5mMaxDatetime"
)
KPX_SUPPLY_PAGE_URL = "https://www.kpx.or.kr/powerinfoSubmain.es?mid=a10404030000"
WIKIMEDIA_TOPICS = {
    "주택·세금": ("부동산", "아파트", "전세권", "도시 재개발", "재건축",
                "종합부동산세", "취득세", "양도소득세"),
    "거시·금융": ("기준금리", "한국은행", "인플레이션", "소비자 물가지수",
                "환율", "국내총생산"),
    "시장·가상자산": ("비트코인", "이더리움", "코스피", "코스닥"),
}
KPX_PRICE_URL = (
    "https://apis.data.go.kr/B552115/SmpWithForecastDemand/"
    "getSmpWithForecastDemand"
)


class SourceUnavailable(ValueError):
    """A source did not provide enough trustworthy data for a new card."""


class _KpxSupplyPageParser(HTMLParser):
    """Only collect the timestamp and explicitly identified actual-value cells."""

    def __init__(self):
        super().__init__()
        self.fields = {}
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        target = attrs.get("id") if tag == "td" else None
        if tag == "p" and "info_top" in attrs.get("class", "").split():
            target = "timestamp"
        if target in ("timestamp", "avil", "load", "supPow", "supPer"):
            if target in self.fields:
                raise SourceUnavailable("전력수급 공식 페이지의 항목이 중복됐습니다")
            self.active = (target, tag)
            self.fields[target] = ""

    def handle_data(self, data):
        if self.active:
            self.fields[self.active[0]] += data

    def handle_endtag(self, tag):
        if self.active and tag == self.active[1]:
            self.active = None


def parse_kpx_supply_page(html_text):
    """Read KPX's market-demand actuals, not estimated total demand or forecasts."""
    sections = re.findall(r"<h3>\s*실시간 전력수급현황\s*</h3>(.*?)<h4>", html_text, re.S)
    if len(sections) != 1:
        raise SourceUnavailable("전력수급 공식 페이지의 실시간 수급 영역이 없습니다")
    parser = _KpxSupplyPageParser()
    parser.feed(sections[0])
    fields = parser.fields
    stamp = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\([^)]*\)\s+(\d{2}):(\d{2})",
                      fields.get("timestamp", ""))
    if not stamp or "현재수요(전력시장)" not in sections[0]:
        raise SourceUnavailable("전력수급 공식 페이지의 기준시각·시장수요 표기가 없습니다")
    try:
        observed_at = datetime(*(int(value) for value in stamp.groups()))
    except ValueError as exc:
        raise SourceUnavailable("전력수급 공식 페이지의 기준시각이 잘못됐습니다") from exc

    def cell(name, unit):
        match = re.fullmatch(r"\s*([\d,]+(?:\.\d+)?)\s*" + re.escape(unit) + r"\s*",
                             fields.get(name, ""))
        if not match:
            raise SourceUnavailable("전력수급 공식 페이지의 수치·단위가 잘못됐습니다")
        return _positive_number(match[1].replace(",", ""), name, allow_zero=True)

    capacity, demand = cell("avil", "MW"), cell("load", "MW")
    reserve, rate = cell("supPow", "MW"), cell("supPer", "%")
    if (demand <= 0 or capacity < demand or rate > 100 or
            abs(capacity - demand - reserve) > 3 or
            abs(reserve / demand * 100 - rate) > 0.1):
        raise SourceUnavailable("전력수급 공식 페이지의 수치 사이에 모순이 있습니다")
    return {"observed_at_kst": observed_at, "demand_mw": demand,
            "capacity_mw": capacity, "reserve_rate_pct": rate,
            "source_url": KPX_SUPPLY_PAGE_URL, "source_route": "official_web",
            "demand_scope": "전력시장"}


def fetch_kpx_supply_page(session):
    response = session.get(KPX_SUPPLY_PAGE_URL, timeout=25)
    response.raise_for_status()
    response.encoding = "utf-8"
    return parse_kpx_supply_page(response.text)


def parse_seoul_commerce_payload(payload, expected_area):
    """Validate one place's official citydata_cmrcl JSON response.

    The public sample key exposes only 광화문·덕수궁. Parsing one place is not
    evidence that the planned 82-place card is ready for release.
    """
    if not isinstance(payload, dict) or payload.get("RESULT", {}).get("resultCode") != "INFO-000":
        raise SourceUnavailable("서울 상권 API가 정상 응답을 주지 않았습니다")
    if (payload.get("AREA_CD") != expected_area if expected_area.startswith("POI")
            else payload.get("AREA_NM") != expected_area):
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
    area = payload.get("AREA_NM")
    if not isinstance(area, str) or not area.strip():
        raise SourceUnavailable("서울 상권 장소명이 없습니다")
    industries = []
    industry_rows = commerce.get("CMRCL_RSB", [])
    if not isinstance(industry_rows, list):
        raise SourceUnavailable("서울 상권 업종 자료 형식이 잘못됐습니다")
    for row in industry_rows:
        if not isinstance(row, dict):
            raise SourceUnavailable("서울 상권 업종 항목 형식이 잘못됐습니다")
        name, industry_level = row.get("RSB_MID_CTGR"), row.get("RSB_PAYMENT_LVL")
        if (isinstance(name, str) and isinstance(industry_level, str)
                and industry_level.startswith(SEOUL_COMMERCE_LEVEL_PREFIXES)):
            industries.append({"industry": name, "relative_level": industry_level})
    return {"area": area, "code": payload.get("AREA_CD"), "observed_at_kst": observed_at,
            "relative_level": level, "shinhan_payment_count": payments,
            "industries": industries}


def build_seoul_commerce_digest(rows, *, now_kst=None, expected_count=82):
    """Current snapshot, never an absolute sales ranking or city total."""
    now_kst = now_kst or datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
    names = [row['area'] for row in rows]
    if len(set(names)) != len(names) or len(rows) > expected_count:
        raise SourceUnavailable("서울 상권 응답의 장소가 중복되거나 범위를 초과했습니다")
    fresh = [row for row in rows if row['observed_at_kst'].date() == now_kst.date()
             and timedelta(minutes=-5) <= now_kst-row['observed_at_kst'] <= timedelta(minutes=30)]
    if len(fresh) < (expected_count * 3 + 3) // 4:
        raise SourceUnavailable("서울 상권 최근 30분 자료가 대상 장소의 75%에 못 미칩니다")
    grouped = {prefix: sorted((row for row in fresh if row['relative_level'].startswith(prefix)),
                             key=lambda row: row['area']) for prefix in SEOUL_COMMERCE_LEVEL_PREFIXES}
    active_count = len(grouped['바쁜']) + len(grouped['분주'])
    source_min = min(row['observed_at_kst'] for row in fresh)
    source_max = max(row['observed_at_kst'] for row in fresh)
    weekday = '월화수목금토일'[now_kst.weekday()]
    lines = ["📍 서울 주요 상권 실시간",
             f"{now_kst.month}월 {now_kst.day}일({weekday}) 소비 현황", "",
             f"🕚 조회: {now_kst:%Y-%m-%d %H:%M} (KST)",
             f"원자료 시각: {source_min:%H:%M}~{source_max:%H:%M}",
             "조회 시점 기준 최근 30분 자료 반영", "",
             "📊 한눈에 보는 상권 분위기", "",
             f"자료가 확보된 {len(fresh)}곳 중 {active_count}곳이 평소보다 소비가 활발합니다.", "",
             f"🔴 분주 {len(grouped['분주'])}곳 · 🟠 바쁨 {len(grouped['바쁜'])}곳",
             f"🟢 보통 {len(grouped['보통'])}곳 · ⚪ 한산 {len(grouped['한산'])}곳", "",
             f"바쁨·분주 비중은 {active_count/len(fresh)*100:.1f}%입니다.",
             f"전체 {expected_count}곳 중 {len(fresh)}곳을 반영했으며, "
             f"자료가 지연된 {len(rows)-len(fresh)}곳·수집 실패 {expected_count-len(rows)}곳은 제외했습니다.",
             "", "🔥 평소보다 소비가 활발한 상권"]
    active = grouped['분주'] + grouped['바쁜']
    def append_examples(examples, label):
        clocks = {row['observed_at_kst'].strftime('%H:%M') for row in examples}
        for prefix, heading in (('분주', '🔴 분주'), ('바쁜', '🟠 바쁨')):
            selected = [row for row in examples if row['relative_level'].startswith(prefix)]
            if selected:
                lines.extend(['', heading])
                lines.extend('• ' + label(row) + (f" ({row['observed_at_kst']:%H:%M})"
                             if len(clocks) > 1 else '') for row in selected)
        return clocks
    clocks = append_examples(active[:6], lambda row: row['area'])
    if not active:
        lines.extend(['', "자료에서 바쁨·분주 단계인 상권은 없습니다."])
    elif len(active) > 6:
        lines.extend(['', f"이 밖에 {len(active)-6}곳도 바쁨·분주 단계입니다."])
    if len(clocks) == 1:
        lines.append(f"위에 표시한 {min(len(active),6)}곳의 원자료 기준시각은 모두 {next(iter(clocks))}입니다.")
    sector_examples = []
    for row in sorted(fresh, key=lambda row: row['area']):
        for industry in sorted(row.get('industries', []), key=lambda item: item['industry']):
            if industry['relative_level'].startswith(('분주', '바쁜')):
                sector_examples.append(dict(area=row['area'], industry=industry['industry'],
                    relative_level=industry['relative_level'], observed_at_kst=row['observed_at_kst']))
    lines.extend(["", "🏪 소비가 활발한 업종 사례"])
    clocks = append_examples(sector_examples[:4], lambda row: row['area'] + ' — ' + row['industry'].replace('/', '·'))
    if not sector_examples:
        lines.extend(['', "자료에 바쁨·분주 단계 업종이 없습니다."])
    elif len(clocks) == 1:
        lines.extend(['', f"위 업종 사례의 원자료 기준시각은 모두 {next(iter(clocks))}입니다."])
    lines.extend(["", "💡 이렇게 읽으세요", "",
                  "‘바쁨·분주’는 최근 4주 같은 요일·시간대와 비교한 소비 상태입니다.", "",
                  "방문·영업 동선을 정할 때, 평소보다 소비가 활발한 상권과 업종을 함께 살펴보세요."])
    return '\n'.join(lines)


def fetch_seoul_commerce_rows(session, service_key):
    if not service_key:
        raise SourceUnavailable("서울 정식 인증키가 없습니다")
    def collect(code):
        try:
            url = f"http://openapi.seoul.go.kr:8088/{service_key}/json/citydata_cmrcl/1/5/{code}"
            return parse_seoul_commerce_payload(_request_json(session, url), code)
        except (requests.RequestException, SourceUnavailable, ValueError):
            return None  # Never print credential-bearing request URLs.
    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = [row for row in executor.map(collect, SEOUL_COMMERCE_CODES) if row is not None]
    return rows


def fetch_seoul_commerce_digest(session, service_key, *, now_kst=None):
    return build_seoul_commerce_digest(fetch_seoul_commerce_rows(session, service_key), now_kst=now_kst)


def _positive_number(value, label, *, allow_zero=False):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceUnavailable(f"{label} 값이 없습니다") from exc
    if not isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise SourceUnavailable(f"{label} 값이 유효하지 않습니다")
    return number


def parse_kpx_supply_xml(xml_text):
    """Validate the official five-minute actuals, without inventing a source time."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise SourceUnavailable("전력수급 API XML 형식이 잘못됐습니다") from exc
    code = root.findtext(".//resultCode")
    if code != "00":
        if code == "30":
            raise SourceUnavailable("전력수급 API 인증 서버가 키를 등록된 키로 인정하지 않습니다 (코드 30)")
        raise SourceUnavailable("전력수급 API가 정상 응답을 주지 않았습니다")
    try:
        observed_at = datetime.strptime(root.findtext(".//baseDatetime"), "%Y%m%d%H%M%S")
    except (TypeError, ValueError) as exc:
        raise SourceUnavailable("전력수급 실측 기준시각이 없습니다") from exc
    demand = _positive_number(root.findtext(".//currPwrTot"), "현재 전력수요")
    capacity = _positive_number(root.findtext(".//suppAbility"), "공급능력")
    reserve_rate = _positive_number(
        root.findtext(".//suppReserveRate"), "공급예비율", allow_zero=True
    )
    if demand > capacity or reserve_rate > 100:
        raise SourceUnavailable("전력수급 실측값 사이에 모순이 있습니다")
    return {
        "observed_at_kst": observed_at,
        "demand_mw": demand,
        "capacity_mw": capacity,
        "reserve_rate_pct": reserve_rate,
    }


def parse_kpx_price_json(payload):
    """Validate one complete JSON page of hourly day-ahead data."""
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        payload = payload["response"]
    if not isinstance(payload, dict) or payload.get("header", {}).get("resultCode") != "00":
        raise SourceUnavailable("도매가격 API가 정상 응답을 주지 않았습니다")
    body = payload.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("items"), dict):
        raise SourceUnavailable("도매가격 API 응답 항목이 없습니다")
    rows = body["items"].get("item")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        raise SourceUnavailable("도매가격·수요예측 자료가 없습니다")
    try:
        total_count = int(body.get("totalCount", len(rows)))
    except (TypeError, ValueError) as exc:
        raise SourceUnavailable("도매가격 API 전체 건수가 잘못됐습니다") from exc
    if total_count != len(rows):
        raise SourceUnavailable("도매가격 API 페이지가 일부만 수집됐습니다")
    result = []
    for row in rows:
        try:
            day = datetime.strptime(str(row["date"]), "%Y%m%d").date()
            hour = int(row["hour"])
            area = str(row["areaName"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceUnavailable("도매가격·수요예측 시각 형식이 잘못됐습니다") from exc
        if not 1 <= hour <= 24 or not area:
            raise SourceUnavailable("도매가격·수요예측 지역·시간이 유효하지 않습니다")
        result.append({
            "date_kst": day,
            "hour_ending": hour,
            "area": area,
            "smp_krw_per_kwh": _positive_number(row.get("smp"), "계통한계가격", allow_zero=True),
            "mainland_forecast_mw": (
                _positive_number(row.get("mlfd"), "육지 예측수요")
                if area == "육지" else None
            ),
        })
    return result


def build_kpx_digest(supply, prices, *, today=None, now_kst=None):
    """Keep real-time actual demand separate from day-ahead forecast and SMP."""
    now_kst = now_kst or datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
    today = today or now_kst.date()
    observed_at = supply["observed_at_kst"]
    age = now_kst - observed_at
    if observed_at.date() != today or not timedelta(minutes=-5) <= age <= timedelta(minutes=20):
        raise SourceUnavailable("전력수급 실측값이 최근 20분 이내 자료가 아닙니다")
    mainland = [row for row in prices if row["area"] == "육지"]
    if not mainland:
        raise SourceUnavailable("육지 도매가격·예측수요 자료가 없습니다")
    forecast_day = max(row["date_kst"] for row in mainland)
    if forecast_day not in (today, today + timedelta(days=1)):
        raise SourceUnavailable("도매가격·수요예측 대상일이 오늘 또는 내일이 아닙니다")
    day_rows = [row for row in mainland if row["date_kst"] == forecast_day]
    hours = {row["hour_ending"] for row in day_rows}
    if len(day_rows) != 24 or hours != set(range(1, 25)):
        raise SourceUnavailable("육지 시간별 도매가격·예측수요 24개가 모이지 않았습니다")
    peak_forecast = max(day_rows, key=lambda row: row["mainland_forecast_mw"])
    peak_smp = max(day_rows, key=lambda row: row["smp_krw_per_kwh"])
    mean_smp = sum(row["smp_krw_per_kwh"] for row in day_rows) / 24
    return "\n".join([
        "대한민국 전력 수급·도매가격",
        f"전력수급 실측: {observed_at:%Y-%m-%d %H:%M} (KST)",
        f"현재 전력수요{(' (' + supply['demand_scope'] + ')') if supply.get('demand_scope') else ''} "
        f"{supply['demand_mw']:,.0f}MW · 공급능력 {supply['capacity_mw']:,.0f}MW",
        f"공급예비율 {supply['reserve_rate_pct']:.1f}%",
        "",
        f"육지 하루전 계획 대상일: {forecast_day.isoformat()} (KST)",
        f"예측 최대수요 {peak_forecast['mainland_forecast_mw']:,.0f}MW "
        f"({peak_forecast['hour_ending']}시 종료 구간)",
        f"계통한계가격(SMP) 24시간 평균 {mean_smp:.1f}원/kWh · "
        f"최고 {peak_smp['smp_krw_per_kwh']:.1f}원/kWh "
        f"({peak_smp['hour_ending']}시 종료 구간)",
        "",
        "※ 위의 현재수요는 실측, 최대수요는 하루전 예측입니다. "
        "SMP는 도매시장 가격이며 가정용 전기요금이 아닙니다.",
        "출처: 한국전력거래소·공공데이터포털",
        "수급 수집경로: " + ("전력거래소 공식 홈페이지" if supply.get("source_route") == "official_web" else "전력수급 API"),
        supply.get("source_url", KPX_SUPPLY_URL),
    ])


def fetch_kpx_supply(session, service_key):
    """Read the official five-minute actuals using a locally protected key."""
    response = session.get(
        KPX_SUPPLY_URL, params={"ServiceKey": service_key}, timeout=25
    )
    response.raise_for_status()
    return parse_kpx_supply_xml(response.text)


def fetch_kpx_prices(session, service_key, target_day):
    """Read every hourly mainland/Jeju record for one plan date."""
    payload = _request_json(session, KPX_PRICE_URL, params={
        "serviceKey": service_key,
        "pageNo": "1",
        "numOfRows": "100",
        "dataType": "json",
        "date": target_day.strftime("%Y%m%d"),
    })
    return parse_kpx_price_json(payload)


def fetch_kpx_digest(session, service_key, *, now_kst=None):
    now_kst = now_kst or datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
    try:
        supply = fetch_kpx_supply(session, service_key)
        age = now_kst - supply["observed_at_kst"]
        if not timedelta(minutes=-5) <= age <= timedelta(minutes=20):
            raise SourceUnavailable("전력수급 API 자료가 오래됐습니다")
    except (requests.RequestException, SourceUnavailable):
        supply = fetch_kpx_supply_page(session)
    prices = fetch_kpx_prices(session, service_key, now_kst.date())
    return build_kpx_digest(supply, prices, now_kst=now_kst)


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
    history = history[:30]
    if any(row[0] != history[0][0] - timedelta(days=offset)
           or not isinstance(row[1], int) or not 0 <= row[1] <= 100
           or row[2] not in CRYPTO_LABELS for offset, row in enumerate(history)):
        raise SourceUnavailable("비트코인 심리 지수의 날짜·점수·분류가 유효하지 않습니다")
    day, value, classification = history[0]
    previous = history[1]
    if previous[0] != day - timedelta(days=1):
        raise SourceUnavailable("전일 비교 자료가 없습니다")
    values = [row[1] for row in history[:30]]
    lowest, highest = min(values), max(values)
    change = value - previous[1]
    change_text = f"{change:+d}점" if change else "변동 없음"
    week_change = value - history[7][1]
    week_change_text = f"{week_change:+d}점" if week_change else "변동 없음"
    week_average = sum(values[:7]) / 7
    prior_week_average = sum(values[7:14]) / 7
    month_average = sum(values) / 30
    month_gap = value - month_average
    lower_days = sum(score < value for score in values)
    equal_days = sum(score == value for score in values)
    higher_days = sum(score > value for score in values)
    streak = next((offset for offset, row in enumerate(history)
                   if row[2] != classification), len(history))
    streak_text = (f"현재 '{CRYPTO_LABELS[classification]}' 분류가 "
                   f"{'최소 ' if streak == 30 else ''}{streak}일 연속입니다.")
    if classification != previous[2]:
        streak_text += f" 전일 '{CRYPTO_LABELS[previous[2]]}'에서 분류가 바뀌었습니다."
    summary = (f"한눈에: {CRYPTO_LABELS[classification]} {value}점, 전일 대비 {change_text}. "
               f"30일 평균보다 {abs(month_gap):.1f}점 {'높습니다' if month_gap >= 0 else '낮습니다'}.")
    if lowest == highest:
        position = "30일간 같은 점수"
    else:
        position = f"최저~최고 구간의 {(value-lowest)/(highest-lowest)*100:.0f}% 지점"
    return "\n".join(
        [
            "🪙 비트코인 공포·탐욕 지수",
            f"📅 원자료 기준일: {day.isoformat()} (UTC)",
            "",
            f"🌡️ 현재 {value}/100 · {CRYPTO_LABELS[classification]}",
            "출처: Alternative.me (Crypto Fear & Greed Index)",
            "",
            "📌 " + summary,
            "",
            "📊 최근 흐름",
            "",
            f"전일 {previous[1]}점 대비 {change_text}",
            f"7일 전 {history[7][1]}점 대비 {week_change_text}",
            "",
            f"최근 7일 평균 {week_average:.1f}점 · 직전 7일 평균 {prior_week_average:.1f}점",
            f"최근 30일 평균 {month_average:.1f}점 · 최저 {lowest}점 / 최고 {highest}점",
            "",
            "📍 최근 30일 속 현재 위치",
            "",
            f"현재 위치: {position}",
            "구간 위치는 최저·최고 사이 거리이며 관측일 순위나 확률이 아닙니다.",
            "",
            "30일 관측 비교 (현재일 포함)",
            f"• 현재보다 낮은 날 {lower_days}일",
            f"• 같은 날 {equal_days}일",
            f"• 높은 날 {higher_days}일",
            "",
            "🔎 심리 상태의 지속",
            "",
            streak_text,
            "",
            "💡 읽는 법",
            "",
            "0에 가까울수록 공포, 100에 가까울수록 탐욕입니다.",
            "",
            "⚠️ 비트코인 시장 심리 지표입니다. 주식시장 전체 심리나 가격 전망·매수 신호가 아닙니다.",
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
    all_stats = {}
    for title, history in histories.items():
        recent = sum(history[day - timedelta(days=offset)] for offset in range(7))
        previous = sum(
            history[day - timedelta(days=offset)] for offset in range(7, 14)
        )
        all_stats[title] = (recent, previous)
        if recent >= min_weekly_views and previous >= min_weekly_views / 2:
            change = (recent / previous - 1) * 100
            ranked.append((change, recent, previous, title))
    ranked.sort(reverse=True)
    total_recent = sum(recent for recent, _ in all_stats.values())
    total_previous = sum(previous for _, previous in all_stats.values())

    def delta_label(recent, previous):
        if previous == 0:
            return "전주 비교 불가"
        return f"{(recent / previous - 1) * 100:+.0f}%"

    lines = [
        "📚 경제 주제 읽기 관심도",
        f"📅 집계 마감: {day.isoformat()} (UTC) · 한국어 위키백과 문서 조회수",
        f"선정 {len(histories)}개 문서 최근 7일 조회 합계 {total_recent:,}회 "
        f"(직전 7일 대비 {delta_label(total_recent, total_previous)})",
        f"비교 기간: {day - timedelta(days=6):%m/%d}~{day:%m/%d} vs "
        f"{day - timedelta(days=13):%m/%d}~{day - timedelta(days=7):%m/%d} (UTC)",
        "",
    ]
    # Keep absolute changes next to percentages so a small denominator cannot
    # masquerade as broad interest. Low-base articles still enter totals, not ranks.
    absolute_change = total_recent - total_previous
    lines.append(f"선정 문서 전체 증감 {absolute_change:+,}회 · 증가율 순위 비교 대상 {len(ranked)}/{len(histories)}개 문서")
    lines.append("")
    groups = []
    group_stats = []
    for label, titles in WIKIMEDIA_TOPICS.items():
        included = [all_stats[title] for title in titles if title in all_stats]
        if included:
            recent = sum(value[0] for value in included)
            previous = sum(value[1] for value in included)
            group_stats.append((label, recent, previous))
            groups.append(f"{label} {recent:,}회 ({delta_label(recent, previous)}) · {len(included)}개 문서")
    if groups:
        lines.extend(["🗂️ 주제별 조회 합계", ""])
        lines.extend(groups)
        lines.append("")
    rising_count = sum(recent > previous for recent, previous in all_stats.values())
    falling_count = sum(recent < previous for recent, previous in all_stats.values())
    flat_count = len(all_stats) - rising_count - falling_count
    top_group = max(group_stats, key=lambda row: row[1], default=None)
    lines.extend(["📊 이번 주 읽기 흐름", ""])
    lines.append(f"조회 증가 {rising_count}개 · 감소 {falling_count}개 · 보합 {flat_count}개 문서")
    if top_group and total_recent:
        label, recent, previous = top_group
        lines.append(
            f"가장 많이 읽힌 묶음은 {label} ({recent:,}회, 전체의 {recent / total_recent * 100:.0f}%)"
        )
    rising_groups = [row for row in group_stats if row[1] > row[2]]
    falling_groups = [row for row in group_stats if row[1] < row[2]]
    if rising_groups and falling_groups:
        up = max(rising_groups, key=lambda row: row[1] / row[2] if row[2] else float("inf"))
        down = min(falling_groups, key=lambda row: row[1] / row[2])
        lines.append(
            f"선정 문서 기준 {up[0]}은 {delta_label(up[1], up[2])}, "
            f"{down[0]}은 {delta_label(down[1], down[2])}로 방향이 엇갈렸습니다."
        )
        lines.append("읽기 포인트: 주제별 방향이 다르므로 한 문서의 급증을 경제 전반의 관심 증가로 확대하지 마십시오.")
    elif group_stats and all(row[1] == row[2] for row in group_stats):
        lines.append("읽기 포인트: 주제별 합계가 보합입니다. 증가 문서가 있어도 다른 문서의 감소와 상쇄될 수 있습니다.")
    elif total_recent <= total_previous:
        lines.append("읽기 포인트: 선정 문서 전체 조회는 늘지 않았습니다. 개별 증가 문서는 전체 흐름과 나눠 읽으십시오.")
    else:
        lines.append("읽기 포인트: 선정 문서 전체 조회가 늘었습니다. 증가 문서 수와 실제 증가 횟수도 함께 보십시오.")
    lines.append("")
    most_read = sorted(
        [(recent, previous, title) for title, (recent, previous) in all_stats.items()
         if recent >= min_weekly_views],
        key=lambda row: (-row[0], row[2]),
    )[:3]
    if most_read:
        lines.extend(["🏆 가장 많이 읽힌 문서", ""])
        lines.extend(
            f"{index}. {title} {recent:,}회"
            for index, (recent, previous, title) in enumerate(most_read, 1)
        )
        lines.append("")
    growing = [row for row in ranked if row[0] > 0][:3]
    if growing:
        change, recent, previous, title = growing[0]
        lines[4:4] = ["", f"📌 한눈에: 조회 증가율이 가장 큰 문서는 '{title}'. "
                      f"최근 7일 {recent:,}회로 직전 {previous:,}회보다 {change:.0f}% 늘었습니다.",
                      "증가율 순위는 아래 최소 조회수 기준을 넘는 문서만 비교합니다."]
        lines.extend(["📈 조회 증가가 두드러진 문서", ""])
        lines.extend(
            f"{index}. {title} {recent:,}회 (직전 7일 {previous:,}회, +{change:.0f}%)"
            for index, (change, recent, previous, title) in enumerate(growing, 1)
        )
        absolute_leader = max([row for row in ranked if row[0] > 0],
                              key=lambda row: (row[1] - row[2], row[3]))
        _, leader_recent, leader_previous, leader_title = absolute_leader
        lines.extend(["", f"🔎 조회 증가 횟수가 가장 큰 문서: {leader_title} +{leader_recent-leader_previous:,}회 "
                     f"({leader_previous:,}→{leader_recent:,}회), 순위 비교 대상 중입니다.",
                     "", "증가율 1위와 다를 수 있습니다."])
        tied_growth = [row[3] for row in ranked if row[0] == change]
        if len(tied_growth) > 1:
            lines.append("증가율 공동 1위: " + " · ".join(sorted(tied_growth)))
        reading_questions = {
            "주택·세금": "주택·세금 용어를 읽을 때는 적용 대상·시점·예외가 무엇인지 확인하십시오.",
            "거시·금융": "거시·금융 용어를 읽을 때는 지표의 정의와 발표 주기, 실제 최신 발표치를 따로 확인하십시오.",
            "시장·가상자산": "시장·가상자산 용어를 읽을 때는 가격 변화와 문서 조회 증가가 실제로 함께 나타났는지 따로 확인하십시오.",
        }
        for label, titles in WIKIMEDIA_TOPICS.items():
            if title in titles:
                lines.extend(["", f"💡 '{title}'에서 이어 읽을 점: {reading_questions[label]}"])
                break
    else:
        lines.append("표본 기준을 넘는 관심 증가 문서가 없습니다.")
    lines.append("")
    declining = sorted((row for row in ranked if row[0] < 0), key=lambda row: row[0])[:2]
    if declining:
        lines.extend(["📉 조회 감소가 두드러진 문서", ""])
        lines.extend(
            f"{index}. {title} {recent:,}회 (직전 7일 {previous:,}회, {change:.0f}%)"
            for index, (change, recent, previous, title) in enumerate(declining, 1)
        )
    lines.extend(
        [
            "",
            f"📏 순위 표시 기준: 최근 7일 {min_weekly_views:,}회 이상 · "
            f"직전 7일 {min_weekly_views / 2:g}회 이상",
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
