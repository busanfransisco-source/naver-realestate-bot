# -*- coding: utf-8 -*-
"""
다음뉴스 간추린 숏뉴스 생성 (GitHub Actions용)
------------------------------------------------
1. 다음뉴스 섹션별(정치/경제/사회/국제) 주요 기사를 가져옴
2. 기자 표기와 사진 설명을 정리한 뒤, 인용문을 자르지 않고 완결된 리드 1~2문장 사용
3. 오늘의 명언(quotes.txt에서 날짜 기준 순환) + 주요 경제 지표를 붙임
4. shortnews-{요일}.txt / shortnews.txt 로 저장 (커밋은 워크플로우가 처리)

어떤 단계가 실패해도 스크립트는 절대 죽지 않고, 모을 수 있는 것만 모아서
반드시 결과 파일을 만든다.
"""

import re
import sys
import time
from difflib import SequenceMatcher
from functools import lru_cache
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote, urlparse

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

WEATHER_KEYWORDS = re.compile(r"폭염|한파|장마|태풍|폭우|폭설|호우|무더위|열대야|미세먼지|황사|찜통|맹추위|눈 소식|눈이|첫눈|대설|비바람")

ARTICLE_LINK_RE = re.compile(r"https://v\.daum\.net/v/\d+")


def get(url, timeout=12):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    # 섹션 페이지의 text/html 응답에는 charset이 없는 경우가 있다.
    # requests의 기본 ISO-8859-1 해석으로 한글 제목이 깨지지 않게 한다.
    if urlparse(url).hostname in {"news.daum.net", "v.daum.net"}:
        resp.encoding = "utf-8"
    return resp


def link_title(anchor):
    """제목만 추출한다. 카드 전체 텍스트에는 리드·매체·상대시각도 들어 있다."""
    encoded = anchor.get("data-title")
    if encoded:
        return unquote(encoded).strip()
    heading = anchor.select_one(".tit_txt, .tit_g, strong, h2, h3")
    return (heading or anchor).get_text(" ", strip=True)


def recent_article(url, now=None):
    """섹션의 추천 영역에 섞인 오래된 기사는 오늘 뉴스 후보에서 제외."""
    match = re.search(r"/v/(20\d{6})\d+", url)
    if not match:
        return True
    try:
        day = datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return False
    age = ((now or datetime.now(KST)).date() - day).days
    return 0 <= age <= 1


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
            title = link_title(a)
            if href in seen or not title or len(title) < 10 or not recent_article(href):
                continue
            seen.add(href)
            items.append((title, href))
            if len(items) >= want * 5:
                break
        if items:
            return items
    return []


JUNK_RE = re.compile(r"무단\s*전재|재배포\s*금지|저작권|@[\w.]+|▶|☞|사진\s*=|영상\s*=|그래픽\s*=")
BROADCAST_RE = re.compile(r"■\s*(?:방송|진행|대담)|☏|(?:진행자|앵커|기자|출연자)\s*>|\[(?:앵커|리포트|기자)\]|◀\s*(?:앵\s*커|리포트|INT)\s*▶")
ORPHAN_RE = re.compile(r"^(?:임|김|이|박|최|정|한|윤|장|오|유|서|조|강|권|신)\s+(?:청장|장관|의원|대표|대통령|교수|회장|시장|지사|최고위원|위원장)(?:은|는|이|가)\s|^(?:그는|그녀는|이들은|이곳은|해당 업체는)\s")
OPINION_RE = re.compile(r"칼럼|사설|기고|기자수첩|취재수첩")


def clean_paragraph(text):
    text = re.sub(r"\s+", " ", text).strip()
    # 기자명이 있다는 이유로 첫 문단 전체를 버리면 주어와 사건이 사라진다.
    text = re.sub(r"^[\[【][^\]】]{1,100}[\]】]\s*", "", text)
    text = re.sub(r"^\([^)]{1,60}(?:=|연합뉴스|뉴시스)[^)]*\)\s*", "", text)
    text = re.sub(r"^(?:[가-힣A-Za-z· /]+\s+)?[가-힣]{2,5}\s*(?:특파원|기자)\s*=\s*", "", text)
    text = re.sub(r"^[가-힣A-Za-z]+\s*=\s*[가-힣]{2,5}\s*(?:기자|특파원)\s*", "", text)
    return text.strip()


def complete_sentences(text):
    """소수점은 유지하고, 큰따옴표 안의 마침표에서는 문장을 끊지 않는다."""
    sentences, start, quote = [], 0, None
    pairs = {'“': '”', '‘': '’', '「': '」', '『': '』', '"': '"', "'": "'"}
    for index, char in enumerate(text):
        if quote and char == quote:
            quote = None
        elif (not quote and char in pairs
              and not (char == "'" and 0 < index < len(text)-1
                       and text[index-1].isalnum() and text[index+1].isalnum())):
            quote = pairs[char]
        if char not in '.!?' or quote:
            continue
        if index + 1 < len(text) and not text[index + 1].isspace():
            continue
        sentence = text[start:index + 1].strip()
        if sentence:
            sentences.append(sentence)
        start = index + 1
    # 불완전한 꼬리 문장은 내보내지 않는다.
    return sentences


@lru_cache(maxsize=1)
def korean_inflector():
    from kiwipiepy import Kiwi
    return Kiwi(num_workers=1)


@lru_cache(maxsize=1024)
def polite_sentence(sentence):
    """Change only the narrator's final ending; quoted speech stays verbatim."""
    match = re.search(r'([가-힣]+)([.!?])$', sentence)
    if not match:
        return ''
    word, punctuation = match.groups()
    if word.endswith(('요', '죠')) or (
            word.endswith('니다') and len(word) >= 3
            and (ord(word[-3]) - 0xAC00) % 28 == 17):
        return sentence
    if word.endswith('다'):
        # Distinguish verbs from omitted copulas: 사례다 -> 사례입니다,
        # not 사롑니다. Recompose only the final word, never the whole article.
        kiwi = korean_inflector()
        tokens = kiwi.tokenize(word)
        if not tokens or tokens[-1].tag != 'EF':
            return ''
        replacement = kiwi.join([(t.form, t.tag, False) for t in tokens[:-1]]
                                + [('습니다', 'EF', False)])
    elif word.endswith(('까', '나')):
        replacement = word + '요'
    else:
        return ''  # Unknown fragments are not exported as a polite summary.
    return sentence[:match.start()] + replacement + punctuation


def polite_summary(text, max_sentences=2, max_chars=280, max_words=25):
    """Keep complete sentences and enforce limits after the ending expands."""
    result = []
    for sentence in complete_sentences(text):
        converted = polite_sentence(sentence)
        if not converted:
            break
        candidate = ' '.join(result + [converted])
        if len(candidate) > max_chars or len(candidate.split()) > max_words:
            break
        result.append(converted)
        if len(result) >= max_sentences:
            break
    return ' '.join(result)


def polite_news_body(text):
    """Check only news explanations, not headings, figures, or verbatim quotes."""
    summaries = re.findall(r'^\S+ \((?:톱뉴스|정치|경제|사회|국제|날씨)\) (.*)$', text, re.M)
    return bool(summaries) and all(summary and polite_summary(summary) == summary for summary in summaries)


def polite_digest(text):
    """Reformat saved news only; keep its dates, quotes, indicators and spacing."""
    def replace(match):
        converted = polite_summary(match[2])
        if not converted:
            raise ValueError('뉴스 문장의 높임말 변환을 확인할 수 없습니다.')
        return match[1] + converted
    return re.sub(
        r'^(\S+ \((?:톱뉴스|정치|경제|사회|국제|날씨)\) )(.+)$',
        replace, text, flags=re.M)


def summary_from_html(html, max_sentences=2, max_chars=280, max_words=25):
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("div.article_view")
    if root is None:
        return ""  # 본문 선택 실패 시 메뉴·댓글을 기사로 오인하지 않는다.
    if BROADCAST_RE.search(root.get_text(" ", strip=True)):
        return ""  # 대담 대본은 리드 추출 대상이 아니다.
    paras = []
    for paragraph in root.select('p, div[dmcf-ptype="general"]'):
        if paragraph.select_one('p, div[dmcf-ptype="general"]'):
            continue
        if paragraph.find_parent(["figure", "figcaption"]):
            continue
        if any("caption" in cls or "desc" in cls for cls in paragraph.get("class", [])):
            continue
        text = clean_paragraph(paragraph.get_text(" ", strip=True))
        if len(text) < 20 or JUNK_RE.search(text):
            continue
        bold = paragraph.find(["strong", "b"])
        if bold and bold.get_text(" ", strip=True) == text and not complete_sentences(text):
            continue  # 본문 앞 굵은 소제목을 다음 문장에 이어 붙이지 않는다.
        paras.append(text)
        if len(paras) >= 6:
            break
    picked = []
    for sentence in complete_sentences(" ".join(paras)):
        if len(sentence) < 15:
            continue
        if not picked and (ORPHAN_RE.search(sentence) or re.match(r"^(반면|하지만|그러나|한편|또한|이에 따라|이어)\s", sentence)):
            return ""  # 맥락을 잃은 리드 대신 다음 기사를 고른다.
        if not picked and (re.search(r"필자|칼럼니스트|이번 칼럼|^우리 동네에 꼭 필요한|^지금 .*논의가 한창", " ".join(paras[:2])) or '이같이 말' in sentence):
            return ""  # 칼럼·수필 도입은 사건 요약에 적합하지 않다.
        if not re.search(r"(?:다|요|죠|까)[.!?]$", sentence):
            if not picked:
                return ""  # '13일 국정감사장.' 같은 현장 스케치 조각은 제외.
            break
        if not picked and (sentence.endswith("?") or sentence[0] in '“"'):
            return ""  # 질문·인용 도입만 떼어내면 사건 설명이 되지 않는다.
        candidate = " ".join(picked + [sentence])
        if len(candidate) > max_chars or len(candidate.split()) > max_words:
            break  # 글자 수 맞추려고 단어나 인용문을 중간 절단하지 않는다.
        picked.append(sentence)
        if len(picked) >= max_sentences:
            break
    return " ".join(picked)


def article_summary(url, max_sentences=2, max_chars=280):
    """새 사실을 생성하지 않고, 독립적으로 읽히는 완결된 리드를 추출."""
    resp = get(url)
    return polite_summary(summary_from_html(resp.text, max_sentences, max_chars),
                          max_sentences, max_chars)


def duplicate_summary(summary, accepted):
    """같은 발표를 여러 매체·섹션이 되풀이하는 경우 한 번만 싣는다."""
    tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", summary))
    for _, _, previous in accepted:
        previous_tokens = set(re.findall(r"[가-힣A-Za-z0-9]+", previous))
        overlap = len(tokens & previous_tokens) / max(1, min(len(tokens), len(previous_tokens)))
        compact = re.sub(r"\s+", " ", summary)
        old_compact = re.sub(r"\s+", " ", previous)
        grams = {compact[i:i + 3] for i in range(len(compact) - 2)}
        old_grams = {old_compact[i:i + 3] for i in range(len(old_compact) - 2)}
        gram_overlap = len(grams & old_grams) / max(1, min(len(grams), len(old_grams)))
        if overlap >= 0.62 or gram_overlap >= 0.48 or SequenceMatcher(None, summary, previous).ratio() >= 0.7:
            return True
    return False


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
            title = link_title(a)
            if href in seen or not title or len(title) < 10 or not recent_article(href):
                continue
            seen.add(href)
            top_candidates.append((title, href))
            if len(top_candidates) >= 5:
                break
    except Exception:
        pass

    for title, href in top_candidates:
        if OPINION_RE.search(title):
            continue
        try:
            summary = article_summary(href)
            if not summary:
                continue
            items.append(("🔥", "톱뉴스", summary))
            used.add(href)
            break
        except Exception:
            pass

    weather_item = None

    for slugs, label, emoji, want in SECTIONS:
        candidates = section_articles(slugs, want)
        count = 0
        for title, href in candidates:
            if href in used:
                continue
            if OPINION_RE.search(title):
                continue
            # 사회 섹션에서 날씨 기사는 따로 빼서 마지막 (날씨) 항목으로
            if label == "사회" and weather_item is None and WEATHER_KEYWORDS.search(title):
                try:
                    summary = article_summary(href)
                    if not summary or duplicate_summary(summary, items):
                        continue
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
            if not summary or duplicate_summary(summary, items + ([weather_item] if weather_item else [])):
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
            summary = polite_summary(summary)
            if not summary:
                continue
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
    if '--polite-existing' in sys.argv:
        from pathlib import Path
        day = WEEKDAY_EN[datetime.now(KST).weekday()]
        for name in ('shortnews.txt', f'shortnews-{day}.txt'):
            path = Path(name)
            original = path.read_text(encoding='utf-8')
            updated = polite_digest(original)
            if not polite_news_body(updated):
                raise SystemExit(f'높임말 검증 실패; 파일 보존: {name}')
            path.write_text(updated, encoding='utf-8')
    else:
        main()
