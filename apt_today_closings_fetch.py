# -*- coding: utf-8 -*-
"""apt.today의 당일 05시 실거래 집계를 링크 없이 브리핑 문장으로 만든다."""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR_SHORT = ["월", "화", "수", "목", "금", "토", "일"]
SOURCE_URL = "https://apt.today/closings"
READER_URL = "https://r.jina.ai/https://apt.today/closings"


def fetch_page_html():
    errors = []

    # apt.today 원본을 크롬과 같은 방식으로 직접 읽는다. 일반 urllib 요청은
    # 사이트 보호 장치에서 429/403으로 차단될 수 있어 브라우저 지문을 사용한다.
    try:
        from curl_cffi import requests

        response = requests.get(SOURCE_URL, impersonate="chrome", timeout=90)
        response.raise_for_status()
        payload = response.text
        if "todaySummary" in payload:
            return payload
        errors.append("원본 페이지에 todaySummary 없음")
    except Exception as exc:
        errors.append(f"원본 직접 수집 실패: {exc}")

    # 원본 직접 수집이 일시적으로 막힐 때만 Reader를 보조 경로로 사용한다.
    request = urllib.request.Request(
        READER_URL,
        headers={
            "User-Agent": "Mozilla/5.0 naver-realestate-bot/1.0",
            "X-Return-Format": "html",
            "X-Timeout": "60",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read().decode("utf-8")
        if "todaySummary" in payload:
            return payload
        errors.append("Reader 페이지에 todaySummary 없음")
    except Exception as exc:
        errors.append(f"Reader 수집 실패: {exc}")

    raise RuntimeError("당일 실거래 집계를 읽지 못했습니다: " + " | ".join(errors))


def decode_next_payloads(page_html):
    decoded = []
    pattern = re.compile(
        r"self\.__next_f\.push\(\[1,(\"(?:\\.|[^\"\\])*\")\]\)",
        re.DOTALL,
    )
    for match in pattern.finditer(html_lib.unescape(page_html)):
        try:
            decoded.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    return decoded


def extract_json_object(text, key):
    marker = f'"{key}":'
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start + len(marker))
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise RuntimeError(f"{key} 데이터의 끝을 찾지 못했습니다")


def parse_today_summary(page_html):
    for payload in decode_next_payloads(page_html):
        summary = extract_json_object(payload, "todaySummary")
        if summary is not None:
            return summary
    raise RuntimeError("당일 실거래 집계 원자료를 해석하지 못했습니다")


def format_eok(amount_manwon):
    amount = int(amount_manwon or 0)
    if amount >= 10000:
        text = f"{amount / 10000:.2f}".rstrip("0").rstrip(".")
        return f"{text}억"
    return f"{amount:,}만원"


def format_per_pyeong(amount_manwon, supply_pyeong):
    if not supply_pyeong:
        return "평당가 확인 중"
    value = round(int(amount_manwon or 0) / float(supply_pyeong))
    if value >= 10000:
        text = f"{value / 10000:.2f}".rstrip("0").rstrip(".")
        return f"{text}억/평"
    if value >= 1000:
        text = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{text}천/평"
    return f"{value / 1000:.1f}".rstrip("0").rstrip(".") + "천/평"


def district_label(transaction):
    sido = (transaction.get("sido") or {}).get("shortName", "")
    sigungu = transaction.get("sigungu") or {}
    short = sigungu.get("shortName") or sigungu.get("name") or ""
    parent = (sigungu.get("parentSigungu") or {}).get("name", "").removesuffix("시")
    if sido == "서울":
        return sigungu.get("name") or short
    if parent:
        return f"{parent}{short}"
    if sido in {"부산", "대구", "인천", "광주", "대전", "울산"}:
        return f"{sido}{short}"
    return short or sido


def format_transaction(transaction):
    supply_pyeong = (transaction.get("type") or {}).get("supplyPY")
    if not supply_pyeong:
        area = float(transaction.get("exclusiveArea") or 0)
        supply_pyeong = round(area / 3.3058) if area else 0
    marker = ""
    if transaction.get("isPYAllTimeHigh"):
        marker = " 신고가"
    elif transaction.get("isAllTimeHigh"):
        marker = " 타입 신고가⭐"
    return (
        f"{district_label(transaction):<7} "
        f"{transaction.get('danjiName', '')} {supply_pyeong}평 "
        f"{format_eok(transaction.get('amount'))}{marker} "
        f"{format_per_pyeong(transaction.get('amount'), supply_pyeong)}"
    )


def summary_date(summary):
    since = str(summary.get("since") or "").replace("Z", "+00:00")
    return datetime.fromisoformat(since).astimezone(KST).date()


def build_digest(summary):
    target_date = summary_date(summary)
    total = int(summary.get("totalCount") or 0)
    record_count = int(summary.get("allTimeHighCount") or 0)
    presale_count = int(summary.get("preconstructedSaleCount") or 0)
    lines = [
        f"{target_date.month}/{target_date.day}({WEEKDAY_KR_SHORT[target_date.weekday()]}) 신규 등록 실거래가",
        "",
        f"전국 {total:,}건 (🔥{record_count:,})",
        f"분양권/입주권 {presale_count:,}건",
        f"🚀 1억클럽 신고가 {int(summary.get('oneHundredMillionClubAllTimeHighCount') or 0):,}건",
        f"💎 1억클럽 {int(summary.get('oneHundredMillionClubCount') or 0):,}건",
        "",
        "[지역별 실거래가]",
    ]
    for region in summary.get("sidoStats") or []:
        name = region.get("sidoShortName") or region.get("sidoName") or "기타"
        if name == "전남광주통합":
            name = "광주·전남"
        lines.append(
            f"{name} {int(region.get('count') or 0):,}건 "
            f"(🔥{int(region.get('allTimeHighCount') or 0):,})"
        )

    highlights = summary.get("highlightTransactions") or []
    # 화면용 하이라이트 일부가 아니라, 당일 전국 신고가 전체 목록을 사용한다.
    # 신고가가 많아도 잘라내지 않고 모두 브리핑 박스에 표시한다.
    record_highs = summary.get("allTimeHighTransactions") or [
        row for row in highlights if row.get("isPYAllTimeHigh")
    ]
    if record_highs:
        lines.extend(["", "[주요 신고가]"])
        lines.extend(format_transaction(row) for row in record_highs)

    record_ids = {row.get("id") for row in record_highs}
    featured = [
        row
        for row in highlights
        if row.get("id") not in record_ids and not row.get("isPYAllTimeHigh")
    ][:7]
    if featured:
        lines.extend(["", "[눈에 띄는 거래]"])
        lines.extend(format_transaction(row) for row in featured)
    return target_date, "\n".join(lines) + "\n"


def write_outputs(target_date, content):
    weekday = WEEKDAY_EN[target_date.weekday()]
    for path in (
        Path("transactions.txt"),
        Path(f"transactions-{weekday}.txt"),
        Path(f"transactions-{target_date.isoformat()}.txt"),
    ):
        path.write_text(content, encoding="utf-8")


def main():
    summary = parse_today_summary(fetch_page_html())
    target_date, content = build_digest(summary)
    today = datetime.now(KST).date()
    if target_date != today:
        raise RuntimeError(
            f"당일 05시 집계가 아직 갱신되지 않았습니다: 화면 {target_date}, 오늘 {today}"
        )
    write_outputs(target_date, content)
    print(
        f"05시 실거래 집계 완료: 전국 {summary.get('totalCount', 0):,}건, "
        f"신고가 {summary.get('allTimeHighCount', 0):,}건, "
        f"분양권/입주권 {summary.get('preconstructedSaleCount', 0):,}건"
    )


if __name__ == "__main__":
    main()
