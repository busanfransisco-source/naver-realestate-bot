# -*- coding: utf-8 -*-
"""주간 지수 → 지역별 변동률 계산 테스트 (재시도+간격)"""
import os, time, requests

KEY = os.environ["RONE_KEY"]
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
out = []

def call(params, tries=3):
    for i in range(tries):
        try:
            r = requests.get(URL, params=params, headers=H, timeout=25)
            return r.json()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))

def fetch_tail(statbl, pages=3, psize=250):
    js = call({"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 1, "STATBL_ID": statbl, "DTACYCLE_CD": "WK"})
    total = js["SttsApiTblData"][0]["head"][0]["list_total_count"]
    rows = []
    last_page = (total - 1) // psize + 1
    for p in range(max(1, last_page - pages + 1), last_page + 1):
        time.sleep(1.5)
        js = call({"KEY": KEY, "Type": "json", "pIndex": p, "pSize": psize, "STATBL_ID": statbl, "DTACYCLE_CD": "WK"})
        rows.extend(js["SttsApiTblData"][1]["row"])
    return total, rows

for statbl, label in [("T244183132827305", "매매"), ("T247713133046872", "전세")]:
    try:
        total, rows = fetch_tail(statbl)
        times = sorted({str(x["WRTTIME_IDTFR_ID"]) for x in rows})
        out.append(f"### {label} total={total} tail시점들={times}")
        latest, prev = times[-1], times[-2]
        top_latest = {x["CLS_NM"]: x["DTA_VAL"] for x in rows if str(x["WRTTIME_IDTFR_ID"]) == latest and ">" not in str(x.get("CLS_FULLNM") or "")}
        top_prev = {x["CLS_NM"]: x["DTA_VAL"] for x in rows if str(x["WRTTIME_IDTFR_ID"]) == prev and ">" not in str(x.get("CLS_FULLNM") or "")}
        desc = [x["WRTTIME_DESC"] for x in rows if str(x["WRTTIME_IDTFR_ID"]) == latest][:1]
        out.append(f"최신주={latest} ({desc}) top지역수={len(top_latest)}")
        for name, v in top_latest.items():
            pv = top_prev.get(name)
            chg = f"{(v/pv-1)*100:+.2f}%" if pv else "?"
            out.append(f"  {name}: {chg} (지수 {v:.1f})")
        # 최신주 전체 행 중 CLS_FULLNM 샘플도 (지역 구조 참고용)
        fulls = sorted({str(x.get("CLS_FULLNM")) for x in rows if str(x["WRTTIME_IDTFR_ID"]) == latest})
        out.append("FULLNM 샘플: " + " / ".join(fulls[:25]))
        time.sleep(2)
    except Exception as e:
        out.append(f"{label} ERROR: {repr(e)}")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
