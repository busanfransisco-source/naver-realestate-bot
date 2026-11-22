# -*- coding: utf-8 -*-
"""
지역별 아침 날씨전망 -> weather.txt 로 저장 (GitHub Actions용)
------------------------------------------------------------
Open-Meteo(무료, API 키 불필요)에서 도시별 오전/오후 하늘상태와 최저/최고기온을
한 번의 API 호출(다중 좌표)로 가져와 사용자가 원하는 고정 포맷의 텍스트로 저장한다.
"""

import sys
import json
import math
import re
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))

WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

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


def fetch_all_cities():
    """모든 도시를 한 번의 요청(다중 좌표)으로 가져온다."""
    lats = ",".join(str(lat) for _, lat, _ in CITIES)
    lons = ",".join(str(lon) for _, _, lon in CITIES)

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lons}"
        "&hourly=weather_code"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&timezone=Asia%2FSeoul&forecast_days=1"
    )

    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


UNAVAILABLE = "당일 날씨 자료를 확보하지 못했습니다. 갱신을 기다리고 있습니다."
DELAY_NOTICE = "[날씨 갱신 지연 · 당일 마지막 정상 예보 유지 · 최신 조회 실패]"
STATUS_PATH = Path("weather-status.txt")
RETRY_COOLDOWN = timedelta(minutes=10)
VALID_CODES = {0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65,
               66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}


def valid_report(report, day):
    """파일명/수정시각 대신 실제 본문 날짜와 15개 완성 행을 검사한다."""
    header = f"{day.year}년 {day.month}월 {day.day}일 {WEEKDAY_KR[day.weekday()]}"
    if not report.startswith(header + "\n") or "❒ 지역별 날씨전망 ❒" not in report:
        return False
    rows = [line for line in report.splitlines() if line.startswith("✫")]
    if len(rows) != len(CITIES):
        return False
    icons = "|".join(re.escape(code_to_emoji(code)) for code in sorted(VALID_CODES))
    for line, (name, _, _) in zip(rows, CITIES):
        match = re.fullmatch(r"✫" + name + r"\((?:" + icons + r")\)➠\((?:" + icons
                             + r")\)  (-?\d+)℃ ~ (-?\d+)℃", line)
        if not match or not -90 <= int(match[1]) <= int(match[2]) <= 60:
            return False
    return True


def without_source_footer(report):
    """Remove the provenance footer from reports written by the previous collector."""
    return re.sub(
        r"\n\n출처: Open-Meteo · 예보 기준일: \d{4}-\d{2}-\d{2}"
        r"\n실제 조회시각\(KST\): [^\n]+$",
        "",
        report,
    )


def read_status(path=STATUS_PATH):
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        attempt = datetime.fromisoformat(status["attemptedAtKst"])
        finish = datetime.fromisoformat(status.get("failedAtKst", status["attemptedAtKst"]))
        if (attempt.tzinfo is None or finish.tzinfo is None or finish < attempt
                or attempt.astimezone(KST).date().isoformat() != status["forecastDate"]
                or status["status"] not in ("ok", "failed")):
            return None
        return status, finish
    except (OSError, ValueError, KeyError, TypeError):
        return None


def retry_deferred(now, path=STATUS_PATH):
    record = read_status(path)
    return bool(record and record[0]["status"] == "failed"
                and timedelta(0) <= now - record[1] < RETRY_COOLDOWN)


def merge_status(source, target=STATUS_PATH, now=None):
    """Carry only valid, newer attempts into the existing shared publication lock."""
    candidate = read_status(source)
    current = read_status(target)
    now = now or datetime.now(KST)
    if candidate and candidate[1] <= now and (not current or candidate[1] > current[1]):
        target.write_bytes(source.read_bytes())
        return True
    return False


def saved_report(now=None, root=Path(".")):
    """Use a verified same-day forecast for the rest of its KST calendar day."""
    now = now or datetime.now(KST)
    day = now.astimezone(KST).date()
    root = Path(root)
    for name in (f"weather-{day.isoformat()}.txt",
                 f"weather-{WEEKDAY_EN[day.weekday()]}.txt", "weather.txt"):
        try:
            report = (root / name).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        report = without_source_footer(report)
        if valid_report(report, day):
            return report
    return ""


def load_report(now=None):
    return saved_report(now) or UNAVAILABLE


def build_report(now=None):
    now = now or datetime.now(KST)
    day = now.date().isoformat()
    results = fetch_all_cities()
    if not isinstance(results, list) or len(results) != len(CITIES):
        raise ValueError("15개 도시 응답이 필요합니다")
    lines = [f"{now.year}년 {now.month}월 {now.day}일 {WEEKDAY_KR[now.weekday()]}",
             "", "❒ 지역별 날씨전망 ❒", ""]
    expected_hours = [f"{day}T{hour:02d}:00" for hour in range(24)]
    for (name, _, _), data in zip(CITIES, results):
        daily, hourly = data["daily"], data["hourly"]
        if daily["time"] != [day] or hourly["time"] != expected_hours:
            raise ValueError(f"{name}: 원자료 날짜/시간 불일치")
        codes = hourly["weather_code"]
        if len(codes) != 24 or any(type(code) is not int or code not in VALID_CODES for code in codes):
            raise ValueError(f"{name}: 하늘상태 누락/오류")
        temperatures = [daily[key] for key in ("temperature_2m_min", "temperature_2m_max")]
        if any(len(values) != 1 or type(values[0]) not in (int, float)
               or not math.isfinite(values[0]) for values in temperatures):
            raise ValueError(f"{name}: 기온 누락/오류")
        tmin, tmax = (values[0] for values in temperatures)
        if not -90 <= tmin <= tmax <= 60:
            raise ValueError(f"{name}: 기온 범위 오류")
        am = code_to_emoji(most_common_code(codes[6:12]))
        pm = code_to_emoji(most_common_code(codes[12:18]))
        lines.append(f"✫{name}({am})➠({pm})  {round(tmin)}℃ ~ {round(tmax)}℃")
    return "\n".join(lines)


def main():
    now = datetime.now(KST)
    today = now.date().isoformat()
    existing = saved_report(now)
    if existing:
        print(existing)
        return 0
    if retry_deferred(now):
        print("날씨 재조회 보류: 최근 실패 후 10분 이내", file=sys.stderr)
        return 1
    status = {"forecastDate": today, "attemptedAtKst": now.isoformat(timespec="seconds")}
    try:
        report = build_report(now)
        if datetime.now(KST).date() != now.date() or not valid_report(report, now.date()):
            raise ValueError("예보 날짜/본문 검증 실패")
    except Exception as exc:
        # 실패 원문은 정상 파일을 덮어쓰지 않는다. 재조회 성공으로 취급하지 않는다.
        status.update(status="failed", errorType=type(exc).__name__,
                      failedAtKst=datetime.now(KST).isoformat(timespec="seconds"))
        STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"날씨 조회 실패: {type(exc).__name__}; 기존 원자료 보존", file=sys.stderr)
        return 1
    for fname in ("weather.txt", f"weather-{today}.txt", f"weather-{WEEKDAY_EN[now.weekday()]}.txt"):
        Path(fname).write_text(report, encoding="utf-8")
    status.update(status="ok")
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
