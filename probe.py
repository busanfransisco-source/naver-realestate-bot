# -*- coding: utf-8 -*-
"""기름값/환율/금은/코인 출처 프로브"""
import re
import requests
from bs4 import BeautifulSoup

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
out = []

# 1) 네이버 환율 목록 (전 통화 + 전일대비)
try:
    r = requests.get("https://finance.naver.com/marketindex/exchangeList.naver", headers=H, timeout=15)
    r.encoding = "euc-kr" if "euc-kr" in r.headers.get("Content-Type", "").lower() else r.encoding
    soup = BeautifulSoup(r.text, "html.parser")
    out.append(f"### 환율목록 status={r.status_code} len={len(r.text)}")
    for tr in soup.select("table tbody tr")[:6]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        out.append(" | ".join(cells))
except Exception as e:
    out.append(f"환율 ERROR: {repr(e)}")

# 2) 네이버 시장지표 메인 (유가/금 포함 여부)
try:
    r = requests.get("https://finance.naver.com/marketindex/", headers=H, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    txt = soup.get_text(" ", strip=True)
    out.append("### 시장지표 키워드: " + ",".join(k for k in ["휘발유", "고급휘발유", "경유", "국제 금", "국내 금", "두바이유"] if k in txt))
    # 유가/금 관련 블록 덤프
    for li in soup.select("li"):
        t = li.get_text(" ", strip=True)
        if any(k in t for k in ["휘발유", "경유", "금 ", "두바이유"]) and len(t) < 120:
            out.append("LI: " + t)
except Exception as e:
    out.append(f"시장지표 ERROR: {repr(e)}")

# 3) 국내 금 시세 상세
try:
    r = requests.get("https://finance.naver.com/marketindex/goldDetailKrw.naver", headers=H, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    el = soup.select_one("p.no_today")
    out.append(f"### 국내금 status={r.status_code} no_today={el.get_text(' ', strip=True) if el else None}")
except Exception as e:
    out.append(f"국내금 ERROR: {repr(e)}")

# 4) 코인게코 top10 (원화)
try:
    r = requests.get("https://api.coingecko.com/api/v3/coins/markets", params={"vs_currency": "krw", "order": "market_cap_desc", "per_page": 10, "page": 1, "price_change_percentage": "24h"}, headers=H, timeout=15)
    js = r.json()
    out.append(f"### 코인게코 status={r.status_code} n={len(js)}")
    for c in js[:10]:
        out.append(f"{c['symbol'].upper()} {c['name']} {c['current_price']} {c.get('price_change_percentage_24h')}")
except Exception as e:
    out.append(f"코인게코 ERROR: {repr(e)}")

# 5) 야후 은 선물
try:
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF?range=1d&interval=1d", headers=H, timeout=15)
    out.append(f"### 야후 은 SI=F: {r.json()['chart']['result'][0]['meta']['regularMarketPrice']}")
except Exception as e:
    out.append(f"은 ERROR: {repr(e)}")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
