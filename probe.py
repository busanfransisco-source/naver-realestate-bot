# -*- coding: utf-8 -*-
"""데이터 출처 프로브: 상태코드 + 응답 앞부분을 probe-result.txt에 기록"""
import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

targets = [
    ("청약홈 캘린더뷰 GET", "GET", "https://www.applyhome.co.kr/ai/aib/selectMonthCalenderView.do", None),
    ("청약홈 APT목록 GET", "GET", "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do", None),
    ("청약홈 APT목록 POST", "POST", "https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancListView.do", {}),
    ("네이버검색 청약캘린더", "GET", "https://search.naver.com/search.naver?query=%EC%B2%AD%EC%95%BD%EC%BA%98%EB%A6%B0%EB%8D%94", None),
    ("네이버검색 분양캘린더", "GET", "https://search.naver.com/search.naver?query=%EB%B6%84%EC%96%91%EC%BA%98%EB%A6%B0%EB%8D%94", None),
    ("네이버뉴스검색 주간동향", "GET", "https://search.naver.com/search.naver?where=news&query=%EC%A3%BC%EA%B0%84+%EC%95%84%ED%8C%8C%ED%8A%B8%EA%B0%80%EA%B2%A9+%EB%8F%99%ED%96%A5", None),
    ("다음뉴스검색 주간동향", "GET", "https://search.daum.net/search?w=news&q=%EC%A3%BC%EA%B0%84+%EC%95%84%ED%8C%8C%ED%8A%B8%EA%B0%80%EA%B2%A9", None),
    ("부동산원 보도자료 목록", "GET", "https://www.reb.or.kr/reb/na/ntt/selectNttList.do?mi=9564&bbsId=1113", None),
    ("부동산원 메인", "GET", "https://www.reb.or.kr/reb/", None),
]

out = []
for name, method, url, data in targets:
    try:
        if method == "POST":
            r = requests.post(url, headers=H, data=data or {}, timeout=12)
        else:
            r = requests.get(url, headers=H, timeout=12)
        body = r.text.replace("\n", " ").replace("\r", " ")
        out.append(f"### {name}\nstatus={r.status_code} len={len(r.text)}\n{body[:700]}\n")
    except Exception as e:
        out.append(f"### {name}\nERROR: {e}\n")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("probe done")
