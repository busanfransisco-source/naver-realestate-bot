# -*- coding: utf-8 -*-
"""R-ONE 주간 매매/전세 지수 데이터 구조 확인"""
import os
import requests

KEY = os.environ["RONE_KEY"]
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
out = []

for statbl, label in [("T244183132827305", "매매"), ("T247713133046872", "전세")]:
    try:
        r = requests.get(URL, params={"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 1, "STATBL_ID": statbl}, timeout=20)
        js = r.json()
        head = js["SttsApiTblData"][0]["head"]
        total = head[0]["list_total_count"]
        out.append(f"### {label} total={total}")
        last_page = total // 500 + 1
        r = requests.get(URL, params={"KEY": KEY, "Type": "json", "pIndex": last_page, "pSize": 500, "STATBL_ID": statbl}, timeout=20)
        rows = r.json()["SttsApiTblData"][1]["row"]
        out.append(f"마지막 페이지 rows={len(rows)}")
        out.append("샘플 row 전체 필드: " + str(rows[-1]))
        times = sorted({str(x.get("WRTTIME_IDTF_ID")) for x in rows})
        out.append(f"시점들: {times[-4:]}")
        latest = times[-1]
        latest_rows = [x for x in rows if str(x.get("WRTTIME_IDTF_ID")) == latest]
        out.append(f"최신 시점 {latest} row수={len(latest_rows)}")
        for x in latest_rows[:40]:
            out.append(f"  CLS={x.get('CLS_NM')} | ITM={x.get('ITM_NM')} | VAL={x.get('DTA_VAL')}")
    except Exception as e:
        out.append(f"{label} ERROR: {repr(e)}")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
