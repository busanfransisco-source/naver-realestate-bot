# -*- coding: utf-8 -*-
"""
청약 일정 + 주간 아파트 시세 동향 수집 (GitHub Actions용)
---------------------------------------------------------
1. 청약홈에서 전국 APT 분양공고를 가져와 접수중/접수예정(2주 내) 단지를 추림
2. 네이버 뉴스검색에서 최신 '주간 아파트가격 동향' 기사(부동산원 발표)의
   제목 + 리드 문장을 가져옴
3. aptinfo-{요일}.txt / aptinfo.txt 로 저장

어떤 단계가 실패해도 스크립트는 죽지 않고 모을 수 있는 것만 담아 파일을 만든다.
"""

import re
import time
from datetime import datetime, date, timezone, timedelta

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

APPLYHOME_URL = "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do"
DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
REGION_RE = re.compile(r"^[가-힣]{2}$")


def get(url, timeout=15, **kw):
    resp = requests.get(url, headers=HEADERS, timeout=timeout, **kw)
    resp.raise_for_status()
    return resp


def parse_d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def fetch_subscriptions(today):
    """청약홈 목록에서 접수중 + 2주 내 접수예정 단지 추출."""
    this_month = today.strftime("%Y%m")
    next_month = (today.replace(day=1) + timedelta(days=32)).strftime("%Y%m")
    try:
        resp = requests.post(
            APPLYHOME_URL,
            headers=HEADERS,
            data={"beginPd": this_month, "endPd": next_month},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        resp = get(APPLYHOME_URL)

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) < 9 or not REGION_RE.match(cells[0]):
                continue
            m = DATE_RANGE_RE.search(cells[7])
            if not m:
                continue
            start, end = parse_d(m.group(1)), parse_d(m.group(2))
            if end < today or start > today + timedelta(days=14):
                continue
            am = DATE_RE.search(cells[8])
            announce = parse_d(am.group(0)) if am else None
            kind_raw = cells[1]
            kind = "공공" if "국민" in kind_raw else ("민간" if "민영" in kind_raw else kind_raw)
            rows.append({
                "region": cells[0],
                "name": cells[3],
                "kind": kind,
                "start": start,
                "end": end,
                "announce": announce,
            })
    # 중복 제거 + 접수 시작일 순 정렬
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["start"], r["region"])):
        key = (r["region"], r["name"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq[:20]


def fetch_weekly_trend():
    """네이버 뉴스검색에서 최신 주간 아파트가격 동향 기사 요약."""
    resp = get(
        "https://search.naver.com/search.naver?where=news&query="
        "%EC%A3%BC%EA%B0%84%20%EC%95%84%ED%8C%8C%ED%8A%B8%EA%B0%80%EA%B2%A9%20%EB%8F%99%ED%96%A5&sort=1"
    )
    soup = BeautifulSoup(resp.text, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=re.compile(r"https://n\.news\.naver\.com/mnews/article/\d+/\d+")):
        href = a["href"].split("?")[0]
        if href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= 5:
            break

    for href in links:
        try:
            art = get(href)
            asoup = BeautifulSoup(art.text, "html.parser")
            title_el = asoup.select_one("#title_area, .media_end_head_headline, h2.media_end_head_headline")
            body_el = asoup.select_one("#dic_area, #articleBodyContents")
            if not title_el or not body_el:
                continue
            title = title_el.get_text(" ", strip=True)
            if "아파트" not in title and "집값" not in title and "주간" not in title:
                continue
            # 날짜
            date_el = asoup.select_one("span.media_end_head_info_datestamp_time")
            date_str = ""
            if date_el and date_el.get("data-date-time"):
                dt = date_el["data-date-time"][:10]
                date_str = f"{int(dt[5:7])}/{int(dt[8:10])}"
            # 본문 리드
            text = body_el.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            sentences = re.split(r"(?<=[.!?])\s+", text)
            picked = []
            for s in sentences:
                s = s.strip()
                s = re.sub(r"^\[[^\]]{2,40}\]\s*", "", s)
                s = re.sub(r"^【[^】]{2,40}】\s*", "", s)
                s = re.sub(r"^[가-힣A-Za-z]+=\S*\s*기자\s*", "", s)
                if len(s) < 10:
                    continue
                picked.append(s)
                if len(picked) >= 3:
                    break
            if not picked:
                continue
            summary = " ".join(picked)
            if len(summary) > 350:
                summary = summary[:350].rsplit(" ", 1)[0] + "…"
            return title, date_str, summary
        except Exception:
            continue
        finally:
            time.sleep(0.2)
    return None


def main():
    now = datetime.now(KST)
    today = now.date()
    weekday_en = WEEKDAY_EN[now.weekday()]
    weekday_kr = WEEKDAY_KR[now.weekday()]

    lines = [f"{now.year % 100}년 {now.month}월 {now.day}일 {weekday_kr} 청약·시세 동향", ""]

    # 1) 청약 일정
    lines.append("🏗️ 청약 접수 단지 (전국, 2주 이내)")
    lines.append("")
    try:
        subs = fetch_subscriptions(today)
    except Exception:
        subs = None
    if subs:
        for r in subs:
            status = " ◀ 접수중" if r["start"] <= today <= r["end"] else ""
            announce = f" | 발표 {r['announce'].month}/{r['announce'].day}" if r["announce"] else ""
            lines.append(
                f"[{r['region']}·{r['kind']}] {r['name']} | 접수 {r['start'].month}/{r['start'].day}~{r['end'].month}/{r['end'].day}{announce}{status}"
            )
    elif subs is None:
        lines.append("(청약 정보를 가져오지 못했습니다)")
    else:
        lines.append("(2주 이내 접수 예정인 단지가 없습니다)")
    lines.append("")

    # 2) 주간 시세 동향
    lines.append("📈 주간 아파트 시세 (한국부동산원 발표 기준)")
    lines.append("")
    try:
        trend = fetch_weekly_trend()
    except Exception:
        trend = None
    if trend:
        title, date_str, summary = trend
        head = f"{title}" + (f" ({date_str})" if date_str else "")
        lines.append(head)
        lines.append(summary)
    else:
        lines.append("(주간 시세 기사를 가져오지 못했습니다)")

    content = "\n".join(lines).strip() + "\n"
    for fname in ("aptinfo.txt", f"aptinfo-{weekday_en}.txt"):
        with open(fname, "w", encoding="utf-8") as f:
            f.write(content)

    print(f"aptinfo 생성 완료: 청약 {len(subs) if subs else 0}건, 시세기사 {'O' if trend else 'X'}")


if __name__ == "__main__":
    main()
