# -*- coding: utf-8 -*-
"""국토교통부 전국 아파트 실거래 원자료를 매일 비교해 신규 등록 요약을 만든다.

수집 대상은 계약일이 아니라 API에 새로 나타난 레코드다. 전날 스냅샷과
오늘 스냅샷을 비교하므로 컴퓨터가 꺼져 있어도 GitHub Actions에서 실행할 수 있다.
"""

from __future__ import annotations

import csv
import hashlib
import http.cookiejar
import io
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR_SHORT = ["월", "화", "수", "목", "금", "토", "일"]
STATE_PATH = Path("transactions-state.json")
DOWNLOAD_PAGE = "https://rt.molit.go.kr/pt/xls/xls.do?mobileAt="
DOWNLOAD_URL = "https://rt.molit.go.kr/pt/xls/ptXlsCSVDown.do"
API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
REGION_CODES_PATH = Path("transactions-region-codes.json")
API_MIN_INTERVAL_SECONDS = 0.55
_API_RATE_LOCK = threading.Lock()
_API_LAST_REQUEST_AT = 0.0

PROVINCE_SHORT = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
    "세종특별자치시": "세종",
    "경기도": "경기",
    "강원특별자치도": "강원",
    "충청북도": "충북",
    "충청남도": "충남",
    "전북특별자치도": "전북",
    "전라남도": "전남",
    "경상북도": "경북",
    "경상남도": "경남",
    "제주특별자치도": "제주",
    "전남광주통합특별시": "광주·전남",
}


def download_form(today):
    return {
        "srhThingNo": "A",          # 아파트
        "srhDelngSecd": "1",       # 매매
        "srhAddrGbn": "1",         # 지번주소
        "srhLfstsSecd": "1",
        "sidoNm": "전체",
        "sggNm": "전체",
        "emdNm": "전체",
        "loadNm": "전체",
        "areaNm": "전체",
        "hsmpNm": "전체",
        "mobileAt": "",
        # 전국 파일은 최대 1개월 범위까지 내려받을 수 있다.
        "srhFromDt": (today - timedelta(days=30)).isoformat(),
        "srhToDt": today.isoformat(),
        "srhNewRonSecd": "",
        "srhSidoCd": "",
        "srhSggCd": "",
        "srhEmdCd": "",
        "srhRoadNm": "",
        "srhLoadCd": "",
        "srhHsmpCd": "",
        "srhArea": "",
        "srhFromAmount": "",
        "srhToAmount": "",
        "srhLrArea": "",
    }


def parse_government_csv(payload):
    text = payload.decode("cp949")
    lines = text.splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if line.startswith('"NO","시군구"')),
        None,
    )
    if header_index is None:
        raise RuntimeError("국토부 CSV 머리글을 찾지 못했습니다")

    rows = []
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    for raw in reader:
        cancellation = (raw.get("해제사유발생일") or "").strip()
        if not raw.get("단지명") or cancellation not in ("", "-"):
            continue
        deal_ym = (raw.get("계약년월") or "").strip()
        if len(deal_ym) != 6:
            continue
        try:
            area = float((raw.get("전용면적(㎡)") or "0").replace(",", ""))
            amount = int((raw.get("거래금액(만원)") or "0").replace(",", "").strip())
            price_per_pyeong = round(amount / (area / 3.3058)) if area else 0
        except ValueError:
            continue
        full_region = (raw.get("시군구") or "").strip()
        parts = full_region.split()
        if len(parts) >= 3 and parts[1].endswith("시") and parts[2].endswith("구"):
            region_name = " ".join(parts[:3])
        elif len(parts) >= 2:
            region_name = " ".join(parts[:2])
        else:
            region_name = full_region
        rows.append(
            {
                "region_name": region_name,
                "year": deal_ym[:4],
                "month": str(int(deal_ym[4:])),
                "day": str(int((raw.get("계약일") or "0").strip() or 0)),
                "dong": parts[-1] if len(parts) >= 2 else "",
                "jibun": (raw.get("번지") or "").strip(),
                "building_name": (raw.get("단지명") or "").strip(),
                "area": area,
                "floor": (raw.get("층") or "").strip(),
                "deal_amount": amount,
                "price_per_pyeong": price_per_pyeong,
                "build_year": (raw.get("건축년도") or "").strip(),
                "deal_type": (raw.get("거래유형") or "").strip(),
            }
        )
    if not rows:
        raise RuntimeError("국토부 전국 CSV에 정상 거래가 없습니다")
    return rows


def fetch_nationwide_transactions(today):
    """국토부 공개시스템에서 전국 최근 31일 계약분을 한 파일로 받는다."""
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": DOWNLOAD_PAGE,
    }
    opener.open(urllib.request.Request(DOWNLOAD_PAGE, headers=headers), timeout=45).read()
    body = urllib.parse.urlencode(download_form(today)).encode("utf-8")
    request = urllib.request.Request(DOWNLOAD_URL, data=body, headers=headers)
    with opener.open(request, timeout=180) as response:
        payload = response.read()
    return parse_government_csv(payload)


def api_months(today):
    first = today.replace(day=1)
    return [(first - timedelta(days=1)).strftime("%Y%m"), today.strftime("%Y%m")]


def api_request(service_key, region_code, year_month, page_no):
    global _API_LAST_REQUEST_AT
    params = urllib.parse.urlencode(
        {
            "serviceKey": service_key,
            "LAWD_CD": region_code,
            "DEAL_YMD": year_month,
            "pageNo": page_no,
            "numOfRows": 1000,
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": "Mozilla/5.0 naver-realestate-bot/1.0"},
    )
    last_error = None
    for attempt in range(4):
        try:
            # 공공데이터 서버의 초당 호출 제한을 넘지 않도록 요청 시작을 간격화한다.
            with _API_RATE_LOCK:
                wait = API_MIN_INTERVAL_SECONDS - (time.monotonic() - _API_LAST_REQUEST_AT)
                if wait > 0:
                    time.sleep(wait)
                _API_LAST_REQUEST_AT = time.monotonic()
            with urllib.request.urlopen(request, timeout=40) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if getattr(exc, "code", None) == 429:
                time.sleep(10 * (attempt + 1))
            else:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{region_code}/{year_month}/{page_no}: {last_error}")


def parse_api_item(item, region_name):
    get = lambda tag: (item.findtext(tag) or "").strip()
    if get("cdealDay"):
        return None
    try:
        area = float(get("excluUseAr") or 0)
        amount = int(get("dealAmount").replace(",", ""))
    except ValueError:
        return None
    if not get("aptNm") or not amount:
        return None
    return {
        "region_name": region_name,
        "year": get("dealYear"),
        "month": str(int(get("dealMonth") or 0)),
        "day": str(int(get("dealDay") or 0)),
        "dong": get("umdNm"),
        "jibun": get("jibun"),
        "building_name": get("aptNm"),
        "area": area,
        "floor": get("floor"),
        "deal_amount": amount,
        "price_per_pyeong": round(amount / (area / 3.3058)) if area else 0,
        "build_year": get("buildYear"),
        "deal_type": get("dealingGbn"),
    }


def fetch_api_region_month(service_key, region_code, region_name, year_month):
    rows = []
    page_no = 1
    while True:
        root = ET.fromstring(api_request(service_key, region_code, year_month, page_no))
        result_code = root.findtext(".//resultCode")
        if result_code not in (None, "00", "000"):
            message = root.findtext(".//resultMsg")
            raise RuntimeError(f"API 오류 {result_code}: {message}")
        for item in root.findall(".//item"):
            parsed = parse_api_item(item, region_name)
            if parsed:
                rows.append(parsed)
        total_count = int(root.findtext(".//totalCount", default="0"))
        if page_no * 1000 >= total_count:
            return rows
        page_no += 1


def fetch_nationwide_api(today, service_key, workers=4):
    regions = json.loads(REGION_CODES_PATH.read_text(encoding="utf-8"))
    jobs = [(code, name, month) for code, name in regions.items() for month in api_months(today)]
    rows = []
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_api_region_month, service_key, code, name, month): (code, month)
            for code, name, month in jobs
        }
        for future in as_completed(futures):
            code, month = futures[future]
            try:
                rows.extend(future.result())
            except Exception as exc:
                errors.append(f"{code}/{month}: {exc}")
    if errors:
        preview = "; ".join(errors[:3])
        raise RuntimeError(f"전국 API 일부 지역 실패 {len(errors)}/{len(jobs)}: {preview}")
    if not rows:
        raise RuntimeError("국토부 전국 API에 정상 거래가 없습니다")
    return rows


def base_signature(row):
    fields = [
        row.get("region_name"),
        row.get("year"),
        row.get("month"),
        row.get("day"),
        row.get("dong"),
        row.get("jibun"),
        row.get("building_name"),
        round(float(row.get("area") or 0), 4),
        str(row.get("floor") or ""),
        int(row.get("deal_amount") or 0),
    ]
    raw = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def tokenized_rows(rows):
    """내용이 완전히 같은 복수 거래도 개수를 잃지 않도록 번호를 붙인다."""
    ordered = sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True))
    counts = Counter()
    result = {}
    for row in ordered:
        signature = base_signature(row)
        counts[signature] += 1
        result[f"{signature}:{counts[signature]}"] = row
    return result


def complex_area_key(row):
    area = round(float(row.get("area") or 0), 2)
    raw = "|".join(
        [
            str(row.get("region_name") or ""),
            str(row.get("dong") or ""),
            str(row.get("building_name") or ""),
            f"{area:.2f}",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def classify_records(new_rows, history_max):
    classified = []
    for row in new_rows:
        item = dict(row)
        prior_max = history_max.get(complex_area_key(row))
        price = int(row.get("deal_amount") or 0)
        # 기준일 이전에 본 동일 단지·동일 면적 거래가 있어야만 신고가로 판정한다.
        item["is_record"] = prior_max is not None and price > int(prior_max)
        classified.append(item)
    return classified


def update_history_max(history_max, rows):
    result = dict(history_max)
    for row in rows:
        key = complex_area_key(row)
        price = int(row.get("deal_amount") or 0)
        result[key] = max(int(result.get(key, 0)), price)
    return result


def short_region(row):
    full = str(row.get("region_name") or "")
    province = full.split()[0] if full else "기타"
    return PROVINCE_SHORT.get(province, province)


def district_name(row):
    parts = str(row.get("region_name") or "").split()
    # CSV의 시군구 값 끝에는 법정동이 붙을 수 있으므로 먼저 제거한다.
    if len(parts) >= 3 and parts[-1].endswith(("동", "읍", "면", "리", "가")):
        parts = parts[:-1]
    if len(parts) >= 3 and parts[1].endswith("시") and parts[2].endswith("구"):
        city = parts[1].removesuffix("시")
        district = parts[2].removesuffix("구")
        return f"{city}{district}"
    return parts[1] if len(parts) >= 2 else (parts[-1] if parts else str(row.get("dong") or ""))


def format_eok(amount_manwon):
    amount = int(amount_manwon or 0)
    if amount >= 10000:
        eok = amount / 10000
        text = f"{eok:.2f}".rstrip("0").rstrip(".")
        return f"{text}억"
    return f"{amount:,}만"


def format_per_pyeong(value):
    value = int(value or 0)
    if value >= 1000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}천/평"
    return f"{value:,}만/평"


def format_transaction(row):
    area_pyeong = round(float(row.get("area") or 0) / 3.3058)
    record = " 신고가" if row.get("is_record") else ""
    return (
        f"{district_name(row):<6}  {row.get('building_name', '')} "
        f"{area_pyeong}평 {format_eok(row.get('deal_amount'))}{record} "
        f"{format_per_pyeong(row.get('price_per_pyeong'))}"
    )


def build_digest(today, records):
    records = list(records)
    record_highs = [row for row in records if row.get("is_record")]
    lines = [
        f"{today.month}/{today.day}({WEEKDAY_KR_SHORT[today.weekday()]}) 신규 등록 실거래가",
        "",
        f"전국 {len(records):,}건 (🔥{len(record_highs):,})",
    ]
    if not records:
        lines.extend(["", "전날 저장본과 비교해 새로 추가된 거래가 없습니다."])
        return "\n".join(lines)

    by_region = defaultdict(list)
    for row in records:
        by_region[short_region(row)].append(row)
    ranked_regions = sorted(
        by_region.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    lines.extend(["", "[지역별 실거래가]"])
    for region, region_rows in ranked_regions:
        highs = sum(1 for row in region_rows if row.get("is_record"))
        lines.append(f"{region} {len(region_rows):,}건 (🔥{highs:,})")

    if record_highs:
        lines.extend(["", "[주요 신고가]"])
        for row in sorted(record_highs, key=lambda x: int(x.get("deal_amount") or 0), reverse=True)[:3]:
            lines.append(format_transaction(row))

    featured = sorted(
        (row for row in records if not row.get("is_record")),
        key=lambda x: (int(x.get("price_per_pyeong") or 0), int(x.get("deal_amount") or 0)),
        reverse=True,
    )[:3]
    if featured:
        lines.extend(["", "[눈에 띄는 거래]"])
        lines.extend(format_transaction(row) for row in featured)
    return "\n".join(lines)


def write_outputs(today, content):
    weekday = WEEKDAY_EN[today.weekday()]
    for path in (
        Path("transactions.txt"),
        Path(f"transactions-{weekday}.txt"),
        Path(f"transactions-{today.isoformat()}.txt"),
    ):
        path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main():
    now = datetime.now(KST)
    today = now.date()
    service_key = os.environ.get("MOLIT_API_KEY", "").strip()
    if service_key:
        rows = fetch_nationwide_api(today, service_key)
        source_name = "국토교통부 공공데이터 API"
    else:
        rows = fetch_nationwide_transactions(today)
        source_name = "국토교통부 실거래가 공개시스템 전국 CSV"
    current = tokenized_rows(rows)

    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        state = {}
    if state.get("version") != 4:
        state = {}
    previous_tokens = set(state.get("seen_tokens", []))
    history_max = state.get("history_max", {})
    bootstrap_preserve_date = state.get("bootstrap_preserve_date")

    if previous_tokens:
        newly_seen = [current[token] for token in current.keys() - previous_tokens]
        classified = classify_records(newly_seen, history_max)
        if bootstrap_preserve_date == today.isoformat():
            # 첫날 사용자가 확인한 집계를 그날의 추가 실행이 0건으로 덮지 않는다.
            today_records = []
            print("첫날 검증 집계를 유지하고 비교 기준만 갱신합니다")
        elif state.get("last_output_date") == today.isoformat():
            existing = state.get("today_new_records", [])
            merged = tokenized_rows([*existing, *classified])
            today_records = list(merged.values())
            write_outputs(today, build_digest(today, today_records))
        else:
            today_records = classified
            write_outputs(today, build_digest(today, today_records))
    else:
        # 첫날은 기준점만 만든다. 이미 오늘 검증된 수동 집계가 있으면 덮어쓰지 않는다.
        today_records = []
        existing_path = Path("transactions.txt")
        expected_title = f"{today.month}/{today.day}({WEEKDAY_KR_SHORT[today.weekday()]})"
        if not existing_path.exists() or expected_title not in existing_path.read_text(encoding="utf-8"):
            content = "\n".join(
                [
                    f"{expected_title} 신규 등록 실거래가",
                    "",
                    "전국 비교 기준 데이터 저장을 완료했습니다.",
                    "다음 수집부터 새로 등록된 거래만 자동 집계합니다.",
                ]
            )
            write_outputs(today, content)
        print(f"첫 수집 기준점 저장: {len(current):,}건")
        bootstrap_preserve_date = today.isoformat()

    state = {
        "version": 4,
        "source": source_name,
        "collected_at": now.isoformat(timespec="seconds"),
        "contract_date_range": [
            (today - timedelta(days=30)).isoformat(),
            today.isoformat(),
        ],
        "seen_tokens": sorted(current),
        "history_max": update_history_max(history_max, rows),
        "last_output_date": today.isoformat(),
        "today_new_records": today_records,
        "bootstrap_preserve_date": bootstrap_preserve_date,
    }
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"전국 아파트 실거래 수집 완료: {len(rows):,}건, 신규 {len(today_records):,}건")


if __name__ == "__main__":
    main()
