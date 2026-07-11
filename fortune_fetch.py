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
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

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

    return best_srl, title_needle


def fetch_document_text(srl, title_needle):
    url = f"{BASE}?mid=today&document_srl={srl}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    # 구분자를 넣지 않고(빈 문자열) 이어붙인다. 이 사이트는 숫자/기호를
    # 낱개 태그로 쪼개서 렌더링하는데(스크래핑 방지 목적으로 보임), 실제
    # 단어 사이 공백은 원본에 이미 별도 텍스트 노드로 존재한다. 여기서
    # 구분자로 공백을 넣으면 오히려 "84년생" 같은 것이 "84 년생"처럼
    # 없던 공백이 낱개 태그 경계마다 끼어들어 버린다.
    full_text = soup.get_text("")
    full_text = re.sub(r"[ \t]+", " ", full_text)

    # 대신 실제 본문(띠별 운세)은 항상 "〈...띠〉" 로 시작하므로 그
    # 첫 등장 지점을 본문 시작으로 삼는다.
    start_idx = full_text.find("〈")
    end_idx = full_text.find("이 게시물을")

    # 본문(〈) 바로 앞에 있는 "[음력 N월 N일] 일진: OO(한자)" 줄을
    # 헤드라인 2번째 줄로 쓰기 위해 별도로 뽑아둔다. 혹시라도 공백이
    # 남아있는 경우까지 대비해 공백을 다 지운 뒤 매칭하고, 자리표시자로
    # 다시 정갈하게 조립한다.
    lunar_line = ""
    if start_idx != -1:
        window = full_text[max(0, start_idx - 300):start_idx]
        compact = re.sub(r"\s+", "", window)
        m = re.search(r"\[음력(\d+)월(\d+)일\]일진:?([^\(\)\[\]]+?)(?:\(([^)]*)\))?(?=\[|$)", compact)
        if m:
            lm, ld, ganji, hanja = m.groups()
            lunar_line = f"[음력 {lm}월 {ld}일] 일진: {ganji.strip()}" + (f"({hanja})" if hanja else "")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        body = full_text[start_idx:end_idx]
    else:
        body = full_text

    # 띠별 문단 앞에서 줄바꿈을 넣어 보기 좋게 정리
    body = re.sub(r"\s*(〈[^〉]+〉)\s*", r"\n\n\1\n", body)
    # "운세지수 NN%. 금전 NN 건강 NN 애정 NN" 뒤에도 문단 구분
    body = re.sub(r"(애정\s*\d+)\s*", r"\1\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)

    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    return lunar_line, "\n".join(lines)


def build_report():
    now = datetime.now(KST)
    # 사용자 레퍼런스 포맷: "오늘의 운세, 7월 12일" + "[음력 5월 28일] 일진: 정해(丁亥)"
    header_line1 = f"오늘의 운세, {now.month}월 {now.day}일"

    try:
        srl, title_needle = find_today_document_srl(now.month, now.day)
        if not srl:
            return header_line1 + "\n\n(오늘 날짜의 운세 글을 아직 찾지 못했습니다.)"
        lunar_line, body = fetch_document_text(srl, title_needle)
        if not body:
            return header_line1 + "\n\n(오늘 날짜의 운세 글을 찾았지만 본문을 추출하지 못했습니다.)"
        header = header_line1 + ("\n" + lunar_line if lunar_line else "")
        return header + "\n\n" + body
    except Exception as e:
        return header_line1 + f"\n\n(운세 데이터를 가져오지 못했습니다: {e})"


def main():
    report = build_report()
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    dated_file = f"fortune-{today}.txt"
    weekday_file = f"fortune-{WEEKDAY_EN[now.weekday()]}.txt"
    # 요일별 고정 파일명으로 저장: 매일 URL이 안 바뀌면서도(provenance 문제 없음),
    # 같은 URL을 일주일에 한 번만 재사용하므로 캐시가 오래 굳어버리는 문제를 피한다.
    for fname in ("fortune.txt", dated_file, weekday_file):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
    print(report)


if __name__ == "__main__":
    main()
