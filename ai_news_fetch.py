# -*- coding: utf-8 -*-
"""
AI타임스 최신뉴스 -> ai.txt 로 저장 (GitHub Actions용)
------------------------------------------------------------------------
1. AI타임스 전체기사 목록 페이지(HTML)를 직접 읽어옴
2. 기사 제목 + 링크를 최대 10개까지 뽑음
3. ai.txt / ai-{요일}.txt 파일로 저장 (커밋/푸시는 워크플로우 쪽에서 처리)
naver_realestate_fetch.py / world_news_fetch.py / finance_news_fetch.py 와 같은 방식.
"""

import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

SECTION_URL = "https://www.aitimes.com/news/articleList.html?box_idxno=10&view_type=sm"
MAX_ARTICLES = 10
OUTPUT_PREFIX = "ai"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

ARTICLE_RE = re.compile(r"/news/articleView\.html\?idxno=\d+")


def fetch_ai_headlines(url, max_articles=10):
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_links = set()

    for a_tag in soup.find_all("a", href=ARTICLE_RE):
        href = a_tag.get("href", "").strip()
        if href.startswith("/"):
            href = "https://www.aitimes.com" + href
        if href in seen_links:
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        articles.append({"title": title, "url": href})
        seen_links.add(href)

        if len(articles) >= max_articles:
            break

    return articles


def main():
    print("AI 뉴스를 가져오는 중...")
    articles = fetch_ai_headlines(SECTION_URL, MAX_ARTICLES)

    if not articles:
        print("기사를 하나도 못 찾았어요. 사이트가 페이지 구조를 바꿨을 수 있습니다.")
        sys.exit(1)

    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    weekday_kr = WEEKDAY_KR[now.weekday()]
    headline = f"🤖 {now.strftime('%y')}년 {now.month}월 {now.day}일 {weekday_kr} AI 뉴스"

    report_lines = [headline, ""]
    for art in articles:
        report_lines.append(art["title"])
        report_lines.append(art["url"])
        report_lines.append("")
    report_text = "\n".join(report_lines).rstrip() + "\n"

    report_dated = f"{OUTPUT_PREFIX}-{today}.txt"
    report_weekday = f"{OUTPUT_PREFIX}-{WEEKDAY_EN[now.weekday()]}.txt"
    for fname in (f"{OUTPUT_PREFIX}.txt", report_dated, report_weekday):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report_text)

    print(f"{len(articles)}개 기사를 {OUTPUT_PREFIX}.txt, {report_dated}, {report_weekday} 에 저장했습니다.")


if __name__ == "__main__":
    main()
