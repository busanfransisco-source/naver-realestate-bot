# -*- coding: utf-8 -*-
"""
청약 소식(subs) + 부동산 주간 시세동향(trend) 수집 (GitHub Actions용)
- subs-{요일}.txt : 청약홈 전국 접수중/접수예정(2주) 단지
- trend-{요일}.txt : 부동산원 R-ONE 주간 아파트 매매/전세 지역별 변동률
어떤 단계가 실패해도 죽지 않고 모을 수 있는 것만 담는다.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

APPLYHOME_URL = "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do"
DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
REGION_RE = re.compile(r"^[가-힣]{2}$")

RONE_URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
RONE_KEY = os.environ.get("RONE_KEY", "")
STATBL_SALE = "T244183132827305"   # (주) 매매가격지수
STATBL_JEONSE = "T247713133046872" # (주) 전세가격지수
REGION_ORDER = ["전국", "수도권", "지방권", "서울", "경기", "인천", "부산", "대구", "광주",
                "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
REGION_LABEL = {"지방권": "지방"}


def parse_d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------- 청약 ----------------

def fetch_subscriptions(today):
    # 국민(공공)분양은 접수 시작 1~2개월 전에 공고가 나는 경우가 많아서,
    # 조회 시작월을 이번달이 아니라 두 달 전으로 넉넉히 잡아야 놓치지 않는다.
    # (한 페이지에 10건씩만 나오므로 여러 페이지를 넘기면서 모은다.)
    begin_month = (today.replace(day=1) - timedelta(days=60)).strftime("%Y%m")
    end_month = (today.replace(day=1) + timedelta(days=32)).strftime("%Y%m")
    rows = []
    page = 1
    while page <= 15:
        try:
            resp = requests.post(
                APPLYHOME_URL, headers=HEADERS,
                data={"beginPd": begin_month, "endPd": end_month, "pageIndex": str(page)},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception:
            if page == 1:
                raise
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        page_rows = []
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(cells) < 9 or not REGION_RE.match(cells[0]):
                    continue
                page_rows.append(cells)
        if not page_rows:
            break
        for cells in page_rows:
            m = DATE_RANGE_RE.search(cells[7])
            if not m:
                continue
            start, end = parse_d(m.group(1)), parse_d(m.group(2))
            if end < today or start > today + timedelta(days=14):
                continue
            am = DATE_RE.search(cells[8])
            kind_raw = cells[1]
            kind = "공공" if "국민" in kind_raw else ("민간" if "민영" in kind_raw else kind_raw)
            rows.append({"region": cells[0], "name": cells[3], "kind": kind,
                         "start": start, "end": end,
                         "announce": parse_d(am.group(0)) if am else None})
        page += 1
        time.sleep(0.5)
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["start"], r["region"])):
        key = (r["region"], r["name"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq[:20]


# ---------------- 시세동향 (R-ONE) ----------------

def rone_call(params, tries=6):
    for i in range(tries):
        try:
            r = requests.get(RONE_URL, params=params, headers=HEADERS, timeout=25)
            return r.json()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def rone_weekly_changes(statbl):
    """최신 2주 지수로 시도별 변동률 계산. 반환: (기준일, {지역: 변동률})"""
    js = rone_call({"KEY": RONE_KEY, "Type": "json", "pIndex": 1, "pSize": 1, "STATBL_ID": statbl, "DTACYCLE_CD": "WK"})
    total = js["SttsApiTblData"][0]["head"][0]["list_total_count"]
    psize = 250
    last_page = (total - 1) // psize + 1
    rows = []
    for p in range(max(1, last_page - 2), last_page + 1):
        time.sleep(2)
        js = rone_call({"KEY": RONE_KEY, "Type": "json", "pIndex": p, "pSize": psize, "STATBL_ID": statbl, "DTACYCLE_CD": "WK"})
        rows.extend(js["SttsApiTblData"][1]["row"])
    times = sorted({str(x["WRTTIME_IDTFR_ID"]) for x in rows})
    latest, prev = times[-1], times[-2]
    top = lambda t: {x["CLS_NM"]: x["DTA_VAL"] for x in rows
                     if str(x["WRTTIME_IDTFR_ID"]) == t and ">" not in str(x.get("CLS_FULLNM") or "")}
    cur, before = top(latest), top(prev)
    date_desc = next((str(x["WRTTIME_DESC"]) for x in rows if str(x["WRTTIME_IDTFR_ID"]) == latest), "")
    changes = {}
    for name in REGION_ORDER:
        if name in cur and name in before and before[name]:
            changes[name] = (cur[name] / before[name] - 1) * 100
    return date_desc, changes


def format_changes(changes):
    lines, buf = [], []
    for name in REGION_ORDER:
        if name not in changes:
            continue
        label = REGION_LABEL.get(name, name)
        buf.append(f"{label} {changes[name]:+.2f}%")
        if len(buf) == 3:
            lines.append(" | ".join(buf))
            buf = []
    if buf:
        lines.append(" | ".join(buf))
    return lines


def main():
    now = datetime.now(KST)
    today = now.date()
    weekday_en = WEEKDAY_EN[now.weekday()]
    weekday_kr = WEEKDAY_KR[now.weekday()]
    date_head = f"{now.year % 100}년 {now.month}월 {now.day}일 {weekday_kr}"

    # ---- 청약 소식 ----
    lines = [f"{date_head} 청약 소식", "", "🏗️ 청약 접수 단지 (전국, 2주 이내)", ""]
    try:
        subs = fetch_subscriptions(today)
    except Exception:
        subs = None
    if subs:
        for r in subs:
            status = " ◀ 접수중" if r["start"] <= today <= r["end"] else ""
            announce = f" | 발표 {r['announce'].month}/{r['announce'].day}" if r["announce"] else ""
            lines.append(f"[{r['region']}·{r['kind']}] {r['name']} | 접수 {r['start'].month}/{r['start'].day}~{r['end'].month}/{r['end'].day}{announce}{status}")
    elif subs is None:
        lines.append("(청약 정보를 가져오지 못했습니다)")
    else:
        lines.append("(2주 이내 접수 예정인 단지가 없습니다)")
    subs_content = "\n".join(lines).strip() + "\n"

    # ---- 주간 시세동향 ----
    tlines = [f"{date_head} 부동산 주간 시세동향", ""]
    import json as _json
    try:
        with open("rone-cache.json", "r", encoding="utf-8") as f:
            cache = _json.load(f)
    except Exception:
        cache = {}

    def get_with_cache(statbl, key):
        try:
            d, ch = rone_weekly_changes(statbl)
            cache[key] = {"date": d, "changes": ch}
            return d, ch
        except Exception:
            c = cache.get(key)
            if c and c.get("changes"):
                return c["date"], c["changes"]
            return None

    sale = get_with_cache(STATBL_SALE, "sale")
    time.sleep(3)
    jeonse = get_with_cache(STATBL_JEONSE, "jeonse")
    try:
        with open("rone-cache.json", "w", encoding="utf-8") as f:
            _json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass

    if sale:
        d, ch = sale
        base = f" ({int(d[5:7])}/{int(d[8:10])} 기준)" if len(d) >= 10 else ""
        tlines.append(f"📈 주간 아파트 매매가격 변동률{base}")
        tlines.append("")
        tlines.extend(format_changes(ch))
        tlines.append("")
    if jeonse:
        d, ch = jeonse
        tlines.append("🔑 주간 아파트 전세가격 변동률")
        tlines.append("")
        tlines.extend(format_changes(ch))
        tlines.append("")
    if sale or jeonse:
        tlines.append("* 한국부동산원 주간 아파트가격 동향 (전주 대비)")
    else:
        tlines.append("(주간 시세 데이터를 가져오지 못했습니다)")
    trend_content = "\n".join(tlines).strip() + "\n"

    for prefix, content in (("subs", subs_content), ("trend", trend_content)):
        for fname in (f"{prefix}.txt", f"{prefix}-{weekday_en}.txt"):
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)

    print(f"완료: 청약 {len(subs) if subs else 0}건, 매매 {'O' if sale else 'X'}, 전세 {'O' if jeonse else 'X'}")


if __name__ == "__main__":
    main()
