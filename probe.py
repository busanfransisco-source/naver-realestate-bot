# -*- coding: utf-8 -*-
"""R-ONE API 프로브: 주간 아파트 변동률 통계표 찾기"""
import os
import requests

KEY = os.environ["RONE_KEY"]
BASE = "https://www.reb.or.kr/r-one/openapi"
out = []

# 1) 통계표 목록에서 주간+아파트 관련 표 찾기
try:
    found = []
    for p in range(1, 6):
        r = requests.get(f"{BASE}/SttsApiTbl.do", params={"KEY": KEY, "Type": "json", "pIndex": p, "pSize": 1000}, timeout=20)
        if p == 1:
            out.append("### raw head\n" + r.text[:500])
        try:
            js = r.json()
        except Exception:
            break
        rows = []
        for block in js.get("SttsApiTbl", []):
            if isinstance(block, dict) and "row" in block:
                rows = block["row"]
        if not rows:
            break
        for row in rows:
            nm = str(row.get("STATBL_NM", ""))
            if row.get("DTACYCLE_CD") == "WK" or nm.startswith("(주)"):
                found.append(f"{row.get('STATBL_ID')} | {nm} | cycle={row.get('DTACYCLE_CD')} | {row.get('DATA_START_YY')}~{row.get('DATA_END_YY')}")
    out.append("### 주간 아파트 통계표 후보")
    out.extend(found[:80] or ["(없음)"])
except Exception as e:
    out.append(f"목록 ERROR: {e}")

with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("probe done")
