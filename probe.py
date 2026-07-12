# -*- coding: utf-8 -*-
import os, requests
KEY = os.environ["RONE_KEY"]
URL = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
out = []
tests = [
    ("기본", {"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 3, "STATBL_ID": "T244183132827305"}),
    ("cycle 포함", {"KEY": KEY, "Type": "json", "pIndex": 1, "pSize": 3, "STATBL_ID": "T244183132827305", "DTACYCLE_CD": "WK"}),
]
for name, params in tests:
    try:
        r = requests.get(URL, params=params, timeout=20)
        out.append(f"### {name} status={r.status_code}")
        out.append(r.text[:1200])
    except Exception as e:
        out.append(f"{name} ERROR: {repr(e)}")
with open("probe-result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("done")
