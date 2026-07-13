# -*- coding: utf-8 -*-
"""
기름값·환율(fuelfx) / 금·은·코인(metalcoin) / 주간 베스트셀러(books) 수집
어떤 단계가 실패해도 죽지 않고 모을 수 있는 것만 담는다.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

FX_LIST = [
    ("USD", "미국 달러"), ("JPY", "일본 엔(100)"), ("EUR", "유럽 유로"),
    ("CNY", "중국 위안"), ("GBP", "영국 파운드"), ("AUD", "호주 달러"),
    ("CAD", "캐나다 달러"), ("CHF", "스위스 프랑"), ("HKD", "홍콩 달러"),
    ("VND", "베트남 동(100)"),
]

COIN_KR = {"BTC": "비트코인", "ETH": "이더리움", "XRP": "리플", "BNB": "비앤비",
           "SOL": "솔라나", "DOGE": "도지코인", "ADA": "에이다", "TRX": "트론",
           "LINK": "체인링크", "AVAX": "아발란체", "XLM": "스텔라루멘", "SUI": "수이",
           "HYPE": "하이퍼리퀴드", "DOT": "폴카닷", "LTC": "라이트코인",
           "SHIB": "시바이누", "TON": "톤코인", "BCH": "비트코인캐시", "HBAR": "헤데라"}
STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "BUSD", "PYUSD", "USDS"}


def get(url, **kw):
    r = requests.get(url, headers=H, timeout=15, **kw)
    r.raise_for_status()
    return r


def naver_market_items():
    """네이버 시장지표 메인에서 휘발유/국제금/국내금 항목 파싱"""
    r = get("https://finance.naver.com/marketindex/")
    soup = BeautifulSoup(r.text, "html.parser")
    items = {}
    for li in soup.find_all("li"):
        t = li.get_text(" ", strip=True)
        m = re.match(r"^(휘발유|고급휘발유|경유|국제 금|국내 금)\s+([\d,]+\.?\d*)\s*(?:원|달러)\s+([\d,]+\.?\d*)\s+(상승|하락|보합)", t)
        if m and m.group(1) not in items:
            val = float(m.group(2).replace(",", ""))
            chg = float(m.group(3).replace(",", ""))
            if m.group(4) == "하락":
                chg = -chg
            elif m.group(4) == "보합":
                chg = 0.0
            items[m.group(1)] = (val, chg)
    return items


def oil_detail(code):
    """네이버 유가 상세 페이지 (OIL_GSL=휘발유, OIL_LO=경유)"""
    r = get(f"https://finance.naver.com/marketindex/oilDetail.naver?marketindexCd={code}")
    soup = BeautifulSoup(r.text, "html.parser")
    today = soup.select_one("p.no_today")
    ex = soup.select_one("p.no_exday")
    val = float(re.sub(r"[^\d.]", "", today.get_text()))
    chg = None
    if ex:
        t = ex.get_text(" ", strip=True)
        m = re.search(r"([\d,]+\.?\d*)", t)
        if m:
            chg = float(m.group(1).replace(",", ""))
            if "하락" in t:
                chg = -chg
    return val, chg


def fx_rates():
    """환율 목록: {코드: 매매기준율}"""
    r = get("https://finance.naver.com/marketindex/exchangeList.naver")
    soup = BeautifulSoup(r.text, "html.parser")
    rates = {}
    for tr in soup.select("table tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        name = cells[0]
        for code, _ in FX_LIST:
            if code in name and code not in rates:
                try:
                    rates[code] = float(cells[1].replace(",", ""))
                except ValueError:
                    pass
    return rates


def coins_top10():
    r = get("https://api.coingecko.com/api/v3/coins/markets",
            params={"vs_currency": "krw", "order": "market_cap_desc", "per_page": 20,
                    "page": 1, "price_change_percentage": "24h"})
    out = []
    for c in r.json():
        sym = c["symbol"].upper()
        name = c.get("name", "")
        if sym in STABLES or any(w in name for w in ("Staked", "Wrapped", "Bridged", "Heloc")):
            continue
        rank = c.get("market_cap_rank")
        if rank is None or rank > 30:
            continue
        out.append((COIN_KR.get(sym, sym), c["current_price"], c.get("price_change_percentage_24h")))
        if len(out) >= 10:
            break
    return out


def bestsellers():
    r = get("https://www.aladin.co.kr/shop/common/wbest.aspx?BestType=Bestseller&BranchType=1&CID=0")
    soup = BeautifulSoup(r.text, "html.parser")
    titles = []
    for a in soup.select("a.bo3"):
        t = a.get_text(" ", strip=True)
        if t and t not in titles:
            titles.append(t)
        if len(titles) >= 10:
            break
    return titles


def sign_fmt(v, decimals=2, suffix=""):
    return f"{'▲' if v > 0 else ('▼' if v < 0 else '-')}{abs(v):,.{decimals}f}{suffix}"


def main():
    now = datetime.now(KST)
    weekday_en = WEEKDAY_EN[now.weekday()]
    date_head = f"{now.year % 100}년 {now.month}월 {now.day}일 {WEEKDAY_KR[now.weekday()]}"

    # ---------- 카드 1: 기름값·환율 ----------
    lines = [f"{date_head} 기름값·환율", ""]
    lines.append("⛽ 전국 평균 기름값 (오피넷 기준, 전일 대비)")
    lines.append("")
    fuel_rows = []
    try:
        items = naver_market_items()
        if "휘발유" in items:
            v, c = items["휘발유"]
            fuel_rows.append(f"휘발유 {v:,.2f}원/L ({sign_fmt(c)})")
    except Exception:
        items = {}
    for code, label in [("OIL_LO", "경유")]:
        try:
            v, c = oil_detail(code)
            chg_s = f" ({sign_fmt(c)})" if c is not None else ""
            fuel_rows.append(f"{label} {v:,.2f}원/L{chg_s}")
        except Exception:
            pass
    lines.extend(fuel_rows or ["(기름값을 가져오지 못했습니다)"])
    lines.append("")
    lines.append("💱 주요국 환율 (매매기준율, 전일 대비)")
    lines.append("")
    try:
        rates = fx_rates()
    except Exception:
        rates = {}
    try:
        with open("fx-cache.json", "r", encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        prev = {}
    if rates:
        for code, label in FX_LIST:
            if code not in rates:
                continue
            cur = rates[code]
            pct = ""
            if prev.get(code):
                p = (cur / prev[code] - 1) * 100
                pct = f" ({p:+.2f}%)"
            lines.append(f"{label} : {cur:,.2f}원{pct}")
        try:
            with open("fx-cache.json", "w", encoding="utf-8") as f:
                json.dump(rates, f)
        except Exception:
            pass
    else:
        lines.append("(환율을 가져오지 못했습니다)")
    fuelfx = "\n".join(lines).strip() + "\n"

    # ---------- 카드 2: 금·은·코인 ----------
    lines = [f"{date_head} 금·은·코인", ""]
    lines.append("🥇 금·은 시세 (전일 대비)")
    lines.append("")
    metal_rows = []
    if "국제 금" in items:
        v, c = items["국제 금"]
        metal_rows.append(f"국제 금 {v:,.2f}달러/온스 ({sign_fmt(c)})")
    if "국내 금" in items:
        v, c = items["국내 금"]
        metal_rows.append(f"국내 금 {v:,.0f}원/g ({sign_fmt(c, 0)})")
    try:
        r = get("https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF?range=1d&interval=1d")
        si = r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
        metal_rows.append(f"국제 은 {si:,.2f}달러/온스")
    except Exception:
        pass
    lines.extend(metal_rows or ["(금·은 시세를 가져오지 못했습니다)"])
    lines.append("")
    lines.append("🪙 코인 시가총액 상위 10 (24시간 등락)")
    lines.append("")
    try:
        coins = coins_top10()
        for name, price, pct in coins:
            price_s = f"{price:,.0f}원" if price >= 100 else f"{price:,.2f}원"
            pct_s = f" ({pct:+.2f}%)" if pct is not None else ""
            lines.append(f"{name} {price_s}{pct_s}")
    except Exception:
        lines.append("(코인 시세를 가져오지 못했습니다)")
    metalcoin = "\n".join(lines).strip() + "\n"

    # ---------- 카드 3: 주간 베스트셀러 ----------
    lines = [f"{date_head} 주간 베스트셀러", "", "📚 알라딘 주간 베스트셀러 TOP 10", ""]
    try:
        books = bestsellers()
        for i, t in enumerate(books, 1):
            lines.append(f"{i}. {t}")
    except Exception:
        lines.append("(베스트셀러를 가져오지 못했습니다)")
    books_content = "\n".join(lines).strip() + "\n"

    for prefix, content in (("fuelfx", fuelfx), ("metalcoin", metalcoin), ("books", books_content)):
        for fname in (f"{prefix}.txt", f"{prefix}-{weekday_en}.txt"):
            with open(fname, "w", encoding="utf-8") as f:
                f.write(content)
    print("market_fetch 완료")


if __name__ == "__main__":
    main()
