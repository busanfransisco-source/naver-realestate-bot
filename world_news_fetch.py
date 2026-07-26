# -*- coding: utf-8 -*-
"""
네이버뉴스 세계(월드) 섹션 -> world.txt 로 저장 (GitHub Actions용)
------------------------------------------------------------------------
1. 네이버뉴스 세계 섹션 페이지(HTML)를 직접 읽어옴
2. 기사 제목 + 링크를 최대 10개까지 뽑음
3. world.txt / world-{요일}.txt 파일로 저장 (커밋/푸시는 워크플로우 쪽에서 처리)
naver_realestate_fetch.py 와 같은 방식.
"""

import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

SECTION_URLS = [
    "https://news.naver.com/section/104",  # 세계 (기본)
    "https://news.naver.com/breakingnews/section/104",  # 혹시 위가 막히면 예비로 시도
]
MAX_ARTICLES = 10
OUTPUT_PREFIX = "world"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def fetch_world_headlines(urls, max_articles=10):
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
        except Exception:
            continue
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        seen_links = set()

        candidates = soup.select("a.sa_text_title, a.sa_thumb_link, a.cluster_text_headline")
        if not candidates:
            candidates = soup.find_all("a", href=re.compile(r"/article/"))

        for a_tag in candidates:
            href = a_tag.get("href", "").strip()
            if not href or href in seen_links:
                continue

            title = a_tag.get_text(strip=True)
            if not title:
                strong = a_tag.find("strong")
                if strong:
                    title = strong.get_text(strip=True)

            if not title:
                continue

            if href.startswith("/"):
                href = "https://news.naver.com" + href

            articles.append({"title": title, "url": href})
            seen_links.add(href)

            if len(articles) >= max_articles:
                break

        if articles:
            return articles

    return []


def main():
    print("세계 뉴스를 가져오는 중...")
    articles = fetch_world_headlines(SECTION_URLS, MAX_ARTICLES)

    if not articles:
        print("기사를 하나도 못 찾았어요. 네이버가 페이지 구조를 바꿨을 수 있습니다.")
        sys.exit(1)

    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    weekday_kr = WEEKDAY_KR[now.weekday()]
    headline = f"🌏 {now.strftime('%y')}년 {now.month}월 {now.day}일 {weekday_kr} 세계 뉴스"

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
