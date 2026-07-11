# -*- coding: utf-8 -*-
"""
네이버뉴스 경제 > 부동산 섹션 -> 텔레그램 전송 (GitHub Actions용)
----------------------------------------------------------------
1. 네이버뉴스 부동산 섹션 페이지(HTML)를 직접 읽어옴
2. 기사 제목 + 링크를 최대 20개까지 뽑음
3. 하나의 메시지로 정리해서 텔레그램 전송

GitHub Actions에서 실행하는 걸 전제로, 토큰/챗ID는 하드코딩하지 않고
환경변수(GitHub Secrets)에서 읽어옵니다.

필요한 환경변수:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

로컬에서 테스트하려면:
    pip install requests beautifulsoup4
    TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx python naver_realestate_to_telegram.py
"""

import os
import re
import sys

import requests
from bs4 import BeautifulSoup

# ===================== CONFIG =====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SECTION_URL = "https://news.naver.com/breakingnews/section/101/260"  # 경제 > 부동산
MAX_ARTICLES = 20
# ====================================================

HEADERS = {
    # 네이버가 파이썬 기본 요청은 종종 막기 때문에, 실제 브라우저인 것처럼 위장
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_real_estate_headlines(url, max_articles=20):
    """부동산 섹션 페이지에서 기사 제목+링크 목록을 뽑아온다."""
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_links = set()

    # 1차 시도: 네이버뉴스가 실제 기사 제목에 흔히 쓰는 클래스명들
    candidates = soup.select("a.sa_text_title, a.sa_thumb_link, a.cluster_text_headline")

    # 2차 시도(1차로 못 찾으면): 기사 링크 패턴(article/ 포함)을 가진 모든 <a> 태그 사용
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

        articles.append((title, href))
        seen_links.add(href)

        if len(articles) >= max_articles:
            break

    return articles


def build_message(articles):
    """기사 목록을 텔레그램 메시지 하나로 합침"""
    lines = ["\U0001F3E0 <b>네이버뉴스 경제 · 부동산 최신 기사</b>\n"]
    for i, (title, link) in enumerate(articles, 1):
        lines.append(f"{i}. {title}\n{link}")
    return "\n\n".join(lines)


def send_telegram_message(text):
    """텔레그램으로 메시지 전송 (4096자 넘으면 자동 분할 전송)"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunk_size = 4000

    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 환경변수가 설정되어 있지 않습니다.")
        sys.exit(1)

    print("부동산 뉴스를 가져오는 중...")
    articles = fetch_real_estate_headlines(SECTION_URL, MAX_ARTICLES)

    if not articles:
        print("기사를 하나도 못 찾았어요. 네이버가 페이지 구조를 바꿨을 수 있습니다.")
        sys.exit(1)

    print(f"{len(articles)}개 기사를 찾았습니다. 텔레그램으로 전송합니다...")
    message = build_message(articles)
    send_telegram_message(message)
    print("전송 완료!")


if __name__ == "__main__":
    main()
