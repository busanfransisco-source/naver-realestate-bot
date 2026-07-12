# -*- coding: utf-8 -*-
"""2차 프로브: 청약홈 목록 구조 + 네이버 뉴스검색 구조 분석"""
import re
import requests
from bs4 import BeautifulSoup

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
out = []

# 1) 청약홈 APT 분양공고 목록
try:
    r = requests.get("https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do", headers=H, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out.append("### 청약홈 테이블 구조")
    for ti, table in enumerate(soup.find_all("table")[:3]):
        out.append(f"--- table {ti} ---")
        for tr in table.find_all("tr")[:15]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            out.append(" | ".join(cells)[:400])
    # 폼/hidden 파라미터
    out.append("### 청약홈 form/hidden")
    for form in soup.find_all("form")[:3]:
        out.append(f"form action={form.get('action')} method={form.get('method')}")
        for inp in form.find_all("input")[:20]:
            out.append(f"  input name={inp.get('name')} value={str(inp.get('value'))[:40]}")
    for sel in soup.find_all("select")[:8]:
        opts = [o.get("value") for o in sel.find_all("option")[:6]]
        out.append(f"select name={sel.get('name')} options={opts}")
except Exception as e:
    out.append(f"청약홈 ERROR: {e}")

# 2) 네이버 뉴스검색 (주간 아파트가격 동향)
try:
    r = requests.get("https://search.naver.com/search.naver?where=news&query=%EC%A3%BC%EA%B0%84+%EC%95%84%ED%8C%8C%ED%8A%B8%EA%B0%80%EA%B2%A9+%EB%8F%99%ED%96%A5&sort=1", headers=H, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    out.append("### 네이버 뉴스검색 앵커")
    seen = 0
    for a in soup.find_all("a", href=re.compile(r"(n\.news\.naver\.com|news\.naver\.com/main/read)")):
        t = a.get_text(" ", strip=True)
        if t and len(t) > 10:
            out.append(f"[{t[:80]}] {a['href'][:100]}")
            seen += 1
        if seen >= 8:
            break
    if seen == 0:
        # 클래스 기반 탐색
        for a in soup.select("a.news_tit, a[class*=title]")[:8]:
            out.append(f"[{a.get_text(' ', strip=True)[:80]}] {a.get('href','')[:100]}")
except Exception as e:
    out.append(f"네이버뉴스 ERROR: {e}")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("probe2 done")
