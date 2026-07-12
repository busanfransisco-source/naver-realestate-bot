# -*- coding: utf-8 -*-
"""
다음뉴스 간추린 숏뉴스 생성 (GitHub Actions용)
------------------------------------------------
1. 다음뉴스 섹션별(정치/경제/사회/국제) 주요 기사를 가져옴
2. 각 기사 본문의 첫 1~2문장(리드)을 요약으로 사용
3. 오늘의 명언(quotes.txt에서 날짜 기준 순환) + 주요 경제 지표를 붙임
4. shortnews-{요일}.txt / shortnews.txt 로 저장 (커밋은 워크플로우가 처리)

어떤 단계가 실패해도 스크립트는 절대 죽지 않고, 모을 수 있는 것만 모아서
반드시 결과 파일을 만든다.
"""

import re
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# (섹션 slug 후보들, 라벨, 이모지, 기사 수)
SECTIONS = [
    (["politics"], "정치", "🏛️", 3),
    (["economic", "economy"], "경제", "💰", 5),
    (["society"], "사회", "👥", 8),
    (["foreign", "world"], "국제", "🌏", 2),
]

WEATHER_KEYWORDS = re.compile(r"폭염|한파|장마|태풍|폭우|폭설|호우|무더위|열대야|미세먼지|황사|찜통|맹추위|눈|비바람")

ARTICLE_LINK_RE = re.compile(r"https://v\.daum\.net/v/\d+")


def get(url, timeout=12):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp


def section_articles(slugs, want):
    """섹션 페이지에서 (제목, 링크) 목록을 순서대로 최대 want*3개 후보로 수집."""
    for slug in slugs:
        try:
            resp = get(f"https://news.daum.net/{slug}")
        except Exception:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        items, seen = [], set()
        for a in soup.find_all("a", href=ARTICLE_LINK_RE):
            href = ARTICLE_LINK_RE.search(a.get("href", "")).group(0)
            title = a.get_text(" ", strip=True)
            if href in seen or not title or len(title) < 10:
                continue
            seen.add(href)
            items.append((title, href))
            if len(items) >= want * 3:
                break
        if items:
            return items
    return []


JUNK_RE = re.compile(r"무단전재|재배포 금지|저작권|기자 *=|@[\w.]+|▶|☞|【|사진=|영상=|그래픽=")


def article_summary(url, max_sentences=2, max_chars=280):
    """기사 본문에서 리드 1~2문장 추출."""
    resp = get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    root = soup.select_one("div.article_view") or soup
    paras = []
    for p in root.find_all("p"):
        t = p.get_text(" ", strip=True)
        if not t or len(t) < 25 or JUNK_RE.search(t):
            continue
        paras.append(t)
    text = " ".join(paras[:4])
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    # 문장 단위로 자르기
    sentences = re.split(r"(?<=[.!?])\s+", text)
    picked = []
    for s in sentences:
        s = s.strip()
        # 앞머리 군더더기 제거: [헤럴드경제=홍아무개 기자], 【서울=뉴시스】 등
        s = re.sub(r"^\[[^\]]{2,40}\]\s*", "", s)
        s = re.sub(r"^【[^】]{2,40}】\s*", "", s)
        s = re.sub(r"^[가-힣A-Za-z]+=\S*\s*기자\s*", "", s)
        if len(s) < 10:
            continue
        # 첫 문장이 접속사로 시작하면 본문 순서가 꼬인 것 → 건너뜀
        if not picked and re.match(r"^(반면|하지만|그러나|한편|또한|이에 따라|이어)\b", s):
            continue
        picked.append(s)
        if len(picked) >= max_sentences:
            break
    summary = " ".join(picked).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0] + "…"
    return summary


def collect_news():
    """섹션별 뉴스 아이템 수집. 반환: [(이모지, 라벨, 요약)], 사용된 링크 set"""
    items = []
    used = set()

    # 톱뉴스: 홈 첫 기사
    top_candidates = []
    try:
        resp = get("https://news.daum.net")
        soup = BeautifulSoup(resp.text, "html.parser")
        seen = set()
        for a in soup.find_all("a", href=ARTICLE_LINK_RE):
            href = ARTICLE_LINK_RE.search(a.get("href", "")).group(0)
            title = a.get_text(" ", strip=True)
            if href in seen or not title or len(title) < 10:
                continue
            seen.add(href)
            top_candidates.append((title, href))
            if len(top_candidates) >= 5:
                break
    except Exception:
        pass

    for title, href in top_candidates[:1]:
        try:
            summary = article_summary(href) or title
            items.append(("🔥", "톱뉴스", summary))
            used.add(href)
        except Exception:
            pass

    weather_item = None

    for slugs, label, emoji, want in SECTIONS:
        candidates = section_articles(slugs, want)
        count = 0
        for title, href in candidates:
            if href in used:
                continue
            # 사회 섹션에서 날씨 기사는 따로 빼서 마지막 (날씨) 항목으로
            if weather_item is None and WEATHER_KEYWORDS.search(title):
                try:
                    summary = article_summary(href) or title
                    weather_item = ("☀️", "날씨", summary)
                    used.add(href)
                    continue
                except Exception:
                    pass
            if count >= want:
                continue
            try:
                summary = article_summary(href)
            except Exception:
                summary = ""
            if not summary:
                continue
            items.append((emoji, label, summary))
            used.add(href)
            count += 1
            time.sleep(0.2)

    if weather_item:
        items.append(weather_item)
    return items


def todays_quote(now):
    try:
        with open("quotes.txt", "r", encoding="utf-8") as f:
            quotes = [ln.strip() for ln in f if ln.strip()]
        if quotes:
            return quotes[now.timetuple().tm_yday % len(quotes)]
    except Exception:
        pass
    return None


def fmt_num(v, decimals=2):
    return f"{v:,.{decimals}f}" if decimals else f"{int(round(v)):,}"


def get_indicators():
    """주요 경제 지표 수집. 실패한 항목은 건너뜀."""
    rows = []

    def naver_index(code):
        resp = get(f"https://finance.naver.com/sise/sise_index.naver?code={code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.select_one("#now_value")
        return float(el.get_text(strip=True).replace(",", ""))

    for code, name in [("KOSPI", "코스피"), ("KOSDAQ", "코스닥"), ("KPI100", "코스피100")]:
        try:
            rows.append((name, fmt_num(naver_index(code))))
        except Exception:
            pass

    # 달러(원/달러 환율)
    try:
        resp = get("https://finance.naver.com/marketindex/")
        soup = BeautifulSoup(resp.text, "html.parser")
        el = soup.select_one("div.head_info > span.value")
        rows.append(("달러", fmt_num(float(el.get_text(strip=True).replace(",", "")))))
    except Exception:
        pass

    # 해외 지수 + 금 (야후 파이낸스 chart API)
    for sym, name in [("^IXIC", "나스닥"), ("^DJI", "다우지수"), ("^GSPC", "S&P500"), ("GC=F", "GOLD(금)")]:
        try:
            resp = get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}?range=1d&interval=1d"
            )
            price = resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
            rows.append((name, fmt_num(float(price))))
        except Exception:
            pass

    # 비트코인 (업비트, 원화)
    try:
        resp = get("https://api.upbit.com/v1/ticker?markets=KRW-BTC")
        price = resp.json()[0]["trade_price"]
        rows.append(("비트코인", fmt_num(price, 0)))
    except Exception:
        pass

    return rows


def main():
    now = datetime.now(KST)
    weekday_en = WEEKDAY_EN[now.weekday()]
    weekday_kr = WEEKDAY_KR[now.weekday()]

    header = f"{now.year % 100}년 {now.month}월 {now.day}일 {weekday_kr} 오늘의 퀵뉴스⚡"

    try:
        news_items = collect_news()
    except Exception:
        news_items = []

    lines = [header, ""]
    if news_items:
        for emoji, label, summary in news_items:
            lines.append(f"{emoji} ({label}) {summary}")
            lines.append("")
    else:
        lines.append("(오늘 뉴스 수집에 실패했습니다)")
        lines.append("")

    quote = todays_quote(now)
    if quote:
        lines.append("[오늘의 명언]")
        lines.append(quote)
        lines.append("")

    indicators = get_indicators()
    if indicators:
        lines.append("[주요 경제 지표]")
        for name, val in indicators:
            lines.append(f"  - {name} : {val}")

    content = "\n".join(lines).strip() + "\n"

    for fname in ("shortnews.txt", f"shortnews-{weekday_en}.txt"):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(content)

    print(f"shortnews 생성 완료: 뉴스 {len(news_items)}건, 지표 {len(indicators)}개")


if __name__ == "__main__":
    main()
