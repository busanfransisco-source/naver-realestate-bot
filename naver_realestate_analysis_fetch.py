# -*- coding: utf-8 -*-
"""
부동산 정책/규제 뉴스 후보 + 본문을 추출해서 JSON으로 저장 (GitHub Actions용)
------------------------------------------------------------------------------
AI(Claude)가 매일 이 파일을 읽어서 페르소나 분석 글을 작성하는 데 쓴다.
- 제목에 정책/세제/규제/대책 관련 키워드가 있는 기사만 후보로 삼는다.
- 분양/광고성 키워드가 있는 기사는 제외한다.
- 최대 6개, 각 기사의 본문 텍스트도 함께 저장한다.
"""

import json
import re
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

SECTION_URL = "https://news.naver.com/breakingnews/section/101/260"  # 경제 > 부동산
OUTPUT_FILE = "realestate-analysis-candidates.json"
MAX_CANDIDATES = 6
BODY_MAX_CHARS = 3000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

KST = timezone(timedelta(hours=9))

# 제목에 이 키워드가 하나라도 있으면 "정책/중대결정" 뉴스 후보로 취급한다.
POLICY_KEYWORDS = [
    "정부", "정책", "종부세", "종합부동산세", "양도세", "취득세", "보유세",
    "대출", "규제", "세제", "재건축", "재개발", "국토부", "국토교통부",
    "대책", "금리", "법안", "개편", "공급대책", "LTV", "DSR", "DTI",
    "청약제도", "분양가상한제", "토지거래허가", "임대차", "전월세",
    "공시가격", "특별공급", "그린벨트", "용적률", "안전진단",
]

# 제목에 이 키워드가 있으면 광고/분양홍보성으로 보고 제외한다.
PROMO_KEYWORDS = [
    "모델하우스", "견본주택", "이벤트", "특가", "프리미엄 증정",
    "청약 문의", "분양 문의", "홍보관", "사은품",
]


def fetch_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def extract_article_body(url):
    """네이버 뉴스 기사 본문 텍스트를 최대한 추출한다."""
    try:
        html_text = fetch_html(url)
    except Exception:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    body_el = (
        soup.select_one("article#dic_area")
        or soup.select_one("#articleBodyContents")
        or soup.select_one("#newsct_article")
    )
    if body_el:
        text = body_el.get_text("\n", strip=True)
    else:
        meta = soup.select_one('meta[property="og:description"]')
        text = meta["content"].strip() if meta and meta.get("content") else ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:BODY_MAX_CHARS]


def is_policy_title(title):
    return any(kw in title for kw in POLICY_KEYWORDS)


def is_promo_title(title):
    return any(kw in title for kw in PROMO_KEYWORDS)


def fetch_candidates(url, max_candidates=MAX_CANDIDATES):
    html_text = fetch_html(url)
    soup = BeautifulSoup(html_text, "html.parser")

    candidates = soup.select("a.sa_text_title, a.cluster_text_headline")
    if not candidates:
        candidates = soup.find_all("a", href=re.compile(r"/article/"))

    results = []
    seen_links = set()

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

        if "동영상" in title:
            continue
        if is_promo_title(title):
            continue
        if not is_policy_title(title):
            continue

        if href.startswith("/"):
            href = "https://news.naver.com" + href

        seen_links.add(href)
        body = extract_article_body(href)
        if not body:
            continue

        results.append({"title": title, "url": href, "body": body})

        if len(results) >= max_candidates:
            break

    return results


def main():
    print("정책/규제 관련 부동산 뉴스 후보를 찾는 중...")
    candidates = fetch_candidates(SECTION_URL, MAX_CANDIDATES)

    now = datetime.now(KST)
    data = {
        "updated_at_kst": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": SECTION_URL,
        "candidates": candidates,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"{len(candidates)}개 후보를 {OUTPUT_FILE} 에 저장했습니다.")
    if len(candidates) == 0:
        print("오늘은 정책 키워드에 해당하는 부동산 뉴스가 없었습니다.")


if __name__ == "__main__":
    main()
