# -*- coding: utf-8 -*-
"""
지역별 아침 날씨전망 -> weather.txt 로 저장 (GitHub Actions용)
------------------------------------------------------------
Open-Meteo(무료, API 키 불필요)에서 도시별 오전/오후 하늘상태와 최저/최고기온을
가져와 사용자가 원하는 고정 포맷의 텍스트로 저장한다.
"""

import sys
from collections import Counter
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))

WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# (표시이름, 위도, 경도)
CITIES = [
    ("서울", 37.5665, 126.9780),
    ("인천", 37.4563, 126.7052),
    ("수원", 37.2636, 127.0286),
    ("춘천", 37.8813, 127.7298),
    ("강릉", 37.7519, 128.8761),
    ("청주", 36.6424, 127.4890),
    ("대전", 36.3504, 127.3845),
    ("세종", 36.4801, 127.2891),
    ("전주", 35.8242, 127.1480),
    ("광주", 35.1595, 126.8526),
    ("대구", 35.8714, 128.6014),
    ("부산", 35.1796, 129.0756),
    ("울산", 35.5384, 129.3114),
    ("창원", 35.2281, 128.6811),
    ("제주", 33.4996, 126.5312),
]

# WMO weather code -> 이모지
def code_to_emoji(code):
    if code == 0:
        return "☀️"
    if code == 1:
        return "🌤️"
    if code == 2:
        return "⛅"
    if code == 3:
        return "☁️"
    if code in (45, 48):
        return "🌫️"
    if code in (51, 53, 55, 56, 57):
        return "🌦️"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "🌧️"
    if code in (71, 73, 75, 77, 85, 86):
        return "❄️"
    if code in (95, 96, 99):
        return "⛈️"
    return "☁️"


def most_common_code(codes):
    if not codes:
        return 3
    return Counter(codes).most_common(1)[0][0]


def fetch_city_weather(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=weathercode"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&timezone=Asia%2FSeoul&forecast_days=1"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    hourly_codes = data["hourly"]["weathercode"]  # 24 values, local hour 0~23
    am_codes = hourly_codes[6:12]   # 06시~11시
    pm_codes = hourly_codes[12:18]  # 12시~17시

    am_emoji = code_to_emoji(most_common_code(am_codes))
    pm_emoji = code_to_emoji(most_common_code(pm_codes))

    tmax = round(data["daily"]["temperature_2m_max"][0])
    tmin = round(data["daily"]["temperature_2m_min"][0])

    return am_emoji, pm_emoji, tmin, tmax


def build_report():
    now = datetime.now(KST)
    weekday_kr = WEEKDAY_KR[now.weekday()]
    date_line = f"{now.year}년 {now.month}월 {now.day}일 {weekday_kr}"

    lines = [date_line, "", "❒ 지역별 날씨전망 ❒", ""]

    for name, lat, lon in CITIES:
        try:
            am_emoji, pm_emoji, tmin, tmax = fetch_city_weather(lat, lon)
        except Exception as e:
            lines.append(f"✫{name}(?)➠(?)  가져오기 실패: {e}")
            continue
        lines.append(f"✫{name}({am_emoji})➠({pm_emoji})  {tmin}℃ ~ {tmax}℃")

    return "\n".join(lines)


def main():
    report = build_report()
    with open("weather.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
