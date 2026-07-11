# -*- coding: utf-8 -*-
"""
네이버뉴스 경제 > 부동산 섹션 -> latest.json 으로 저장 (GitHub Actions용)
------------------------------------------------------------------------
1. 네이버뉴스 부동산 섹션 페이지(HTML)를 직접 읽어옴
2. 기사 제목 + 링크를 최대 20개까지 뽑음
3. latest.json 파일로 저장 (커밋/푸시는 워크플로우 쪽에서 처리)
"""

import json
import re
import sys
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

SECTION_URL = "https://news.naver.com/breakingnews/section/101/260"  # 경제 > 부동산
MAX_ARTICLES = 20
OUTPUT_FILE = "latest.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

KST = timezone(timedelta(hours=9))


def fetch_real_estate_headlines(url, max_articles=20):
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
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

    return articles


def main():
    print("부동산 뉴스를 가져오는 중...")
    articles = fetch_real_estate_headlines(SECTION_URL, MAX_ARTICLES)

    if not articles:
        print("기사를 하나도 못 찾았어요. 네이버가 페이지 구조를 바꿨을 수 있습니다.")
        sys.exit(1)

    today = datetime.now(KST).strftime("%Y-%m-%d")
    data = {
        "updated_at_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "source": SECTION_URL,
        "articles": articles,
    }

    # 캐시 문제를 피하기 위해 날짜가 들어간 파일명으로도 저장 (매일 새 URL)
    dated_file = f"latest-{today}.json"
    for fname in (OUTPUT_FILE, dated_file):
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"{len(articles)}개 기사를 {OUTPUT_FILE}, {dated_file} 에 저장했습니다.")


if __name__ == "__main__":
    main()
