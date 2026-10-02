"""Official 82-place catalogue (2026-04-14), XLSX column C, read without edits.

Source: https://data.seoul.go.kr/dataList/OA-22385/A/1/datasetView.do
"""
SEOUL_COMMERCE_CODES = tuple(f"POI{number:03d}" for number in (
    1, 2, 3, 4, 5, 6, 7, 9, 10, 13, 14, 15, 16, 17, 18, 19, 20, 21,
    23, 24, 25, 26, 27, 29, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
    41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56,
    58, 59, 60, 61, 63, 64, 66, 67, 68, 70, 71, 72, 73, 74, 76, 77,
    78, 79, 80, 81, 82, 83, 84, 114, 115, 116, 117, 118, 119, 120, 121, 122,
))
