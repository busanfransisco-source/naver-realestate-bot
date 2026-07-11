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
    fortune_files = sorted(glob.glob("fortune-*.txt"), reverse=True)

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
    lines.append("<h2>Fortune</h2>")
    lines.append("<ul>")
    for f in fortune_files:
        lines.append(f'<li><a href="{f}">{f}</a></li>')
    lines.append("</ul>")
    lines.append("</body></html>")

    content = "\n".join(lines)

    # index.html은 사람이 보기 위한 용도로 계속 유지.
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(content)

    # hub.html: 예약 작업(스케줄러)이 매일 여는 "진입점" 전용 파일.
    # index.html은 예전에 이미 여러 번 조회된 적이 있어 캐시가 오래된 채로
    # 굳어버릴 수 있으므로, 한 번도 조회된 적 없는 새 파일명을 진입점으로 쓴다.
    with open("hub.html", "w", encoding="utf-8") as f:
        f.write(content)

    print(
        f"index.html/hub.html 생성 완료: weather 파일 {len(weather_files)}개, "
        f"news 파일 {len(news_files)}개, fortune 파일 {len(fortune_files)}개"
    )


if __name__ == "__main__":
    main()
