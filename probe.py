# -*- coding: utf-8 -*-
"""주간 지수 → 지역별 변동률 계산 테스트"""
import os, requests
KEY = os.environ["RONE_KEY"]
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
out = []

def fetch_tail(statbl, pages=4, psize=500):
    r = requests.get(URL, params={"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 1, "STATBL_ID": statbl, "DTACYCLE_CD": "WK"}, timeout=20)
    total = r.json()["SttsApiTblData"][0]["head"][0]["list_total_count"]
    rows = []
    last_page = (total - 1) // psize + 1
    for p in range(max(1, last_page - pages + 1), last_page + 1):
        r = requests.get(URL, params={"KEY": KEY, "Type": "json", "pIndex": p, "pSize": psize, "STATBL_ID": statbl, "DTACYCLE_CD": "WK"}, timeout=20)
        rows.extend(r.json()["SttsApiTblData"][1]["row"])
    return total, rows

for statbl, label in [("T244183132827305", "매매"), ("T247713133046872", "전세")]:
    try:
        total, rows = fetch_tail(statbl)
        times = sorted({str(x["WRTTIME_IDTFR_ID"]) for x in rows})
        out.append(f"### {label} total={total} tail시점들={times}")
        latest, prev = times[-1], times[-2]
        # 시도급(top-level) = CLS_FULLNM에 '>' 없음
        top_latest = {x["CLS_NM"]: x["DTA_VAL"] for x in rows if str(x["WRTTIME_IDTFR_ID"]) == latest and ">" not in str(x.get("CLS_FULLNM") or "")}
        top_prev = {x["CLS_NM"]: x["DTA_VAL"] for x in rows if str(x["WRTTIME_IDTFR_ID"]) == prev and ">" not in str(x.get("CLS_FULLNM") or "")}
        desc = [x["WRTTIME_DESC"] for x in rows if str(x["WRTTIME_IDTFR_ID"]) == latest][:1]
        out.append(f"최신주={latest} ({desc}) 지역수={len(top_latest)}")
        for name, v in top_latest.items():
            pv = top_prev.get(name)
            chg = f"{(v/pv-1)*100:+.2f}%" if pv else "?"
            out.append(f"  {name}: {chg} (지수 {v:.1f})")
    except Exception as e:
        out.append(f"{label} ERROR: {repr(e)}")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
