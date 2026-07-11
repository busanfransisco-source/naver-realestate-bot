# -*- coding: utf-8 -*-
"""
askjiyun.com 오늘의 운세 -> fortune.txt / fortune-YYYY-MM-DD.txt (GitHub Actions용)
------------------------------------------------------------------------------
이 게시판은 "업로드 날짜"가 아니라 "글 제목에 적힌 날짜"가 그 날의 운세다.
운영자가 여러 날짜치를 미리 몰아서 올려두기 때문에, 게시판 맨 위 글이 항상
오늘 날짜인 것은 아니다. 그래서 제목("M월 D일")으로 직접 검색해서 오늘
날짜와 정확히 일치하는 글을 찾는다. 같은 제목이 매년 반복되므로
(예: "7월 11일"은 2013~2026년에 각각 존재) 그 중 document_srl이 가장 큰
(=가장 최근 연도) 글을 선택한다.
"""

import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

BASE = "https://askjiyun.com/"


def find_today_document_srl(month, day):
    keyword = f"{month}월 {day}일"
    url = BASE + "?mid=today&search_target=title&search_keyword=" + quote(keyword)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    best_srl = None
    title_needle = f"오늘의 운세, {keyword}"

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text != title_needle:
            continue
        m = re.search(r"document_srl=(\d+)", a["href"])
        if not m:
            continue
        srl = int(m.group(1))
        if best_srl is None or srl > best_srl:
            best_srl = srl

    return best_srl


def fetch_document_text(srl):
    url = f"{BASE}?mid=today&document_srl={srl}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text("\n")

    # 날짜/조회수 줄 (예: "2026.07.08" ...) 다음부터 "이 게시물을" 전까지가 본문
    date_match = re.search(r"\d{4}\.\d{2}\.\d{2}", full_text)
    end_idx = full_text.find("이 게시물을")

    if date_match and end_idx != -1 and end_idx > date_match.end():
        body = full_text[date_match.end():end_idx]
    else:
        body = full_text

    # 빈 줄 정리
    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def build_report():
    now = datetime.now(KST)
    weekday_kr = WEEKDAY_KR[now.weekday()]
    header = f"{now.year}년 {now.month}월 {now.day}일 {weekday_kr}\n\n❒ 오늘의 운세 ❒\n"

    try:
        srl = find_today_document_srl(now.month, now.day)
        if not srl:
            return header + "\n(오늘 날짜의 운세 글을 아직 찾지 못했습니다.)"
        body = fetch_document_text(srl)
        if not body:
            return header + "\n(오늘 날짜의 운세 글을 찾았지만 본문을 추출하지 못했습니다.)"
        return header + "\n" + body
    except Exception as e:
        return header + f"\n(운세 데이터를 가져오지 못했습니다: {e})"


def main():
    report = build_report()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    dated_file = f"fortune-{today}.txt"
    for fname in ("fortune.txt", dated_file):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
    print(report)


if __name__ == "__main__":
    main()
