# -*- coding: utf-8 -*-
"""
저장소 루트에 있는 weather-*.txt / latest-*.json 파일들을 스캔해서
index.html 에 링크 목록을 만든다.

이유: 예약 작업(스케줄러) 쪽 web_fetch 도구가 "링크로 발견되지 않은 URL"은
직접 fetch하지 못하는 제한이 있어서, 루트 페이지(index.html)에 실제 <a href>
링크로 오늘 날짜 파일을 노출해둬야 그 링크를 통해 접근할 수 있다.
"""

import glob

def main():
    weather_files = sorted(glob.glob("weather-*.txt"), reverse=True)
    news_files = sorted(glob.glob("latest-*.json"), reverse=True)

    lines = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>naver-realestate-bot data</title></head><body>",
        "<h1>Data files</h1>",
        "<h2>Weather</h2>",
        "<ul>",
    ]
    for f in weather_files:
        lines.append(f'<li><a href="{f}">{f}</a></li>')
    lines.append("</ul>")
    lines.append("<h2>News</h2>")
    lines.append("<ul>")
    for f in news_files:
        lines.append(f'<li><a href="{f}">{f}</a></li>')
    lines.append("</ul>")
    lines.append("</body></html>")

    with open("index.html", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"index.html 생성 완료: weather 파일 {len(weather_files)}개, news 파일 {len(news_files)}개")


if __name__ == "__main__":
    main()
