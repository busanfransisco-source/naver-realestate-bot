# -*- coding: utf-8 -*-
"""
briefing.html 생성 (GitHub Actions용)
------------------------------------
weather-{요일}.txt / fortune-{요일}.txt / realestate-{요일}.txt 를 읽어서,
폰 홈 화면에 즐겨찾기 해두고 매일 아침 열어 버튼 3번만 누르면 카톡에 붙여넣을
텍스트가 바로 클립보드에 복사되는 정적 페이지를 만든다.

버튼 순서: 오늘의 운세 -> 날씨 -> 부동산 뉴스 (사용자가 카톡방에 공유하는 순서)
"""

import html
import json
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return f"(파일을 찾을 수 없습니다: {path})"


SECTIONS = [
    ("fortune", "🔮 오늘의 운세", "fortune"),
    ("weather", "☀️ 날씨", "weather"),
    ("realestate", "🏠 부동산 뉴스", "realestate"),
]


def build_html():
    now = datetime.now(KST)
    weekday_en = WEEKDAY_EN[now.weekday()]
    weekday_kr = WEEKDAY_KR[now.weekday()]
    date_line = f"{now.year}년 {now.month}월 {now.day}일 {weekday_kr}"

    section_blocks = []
    for key, label, fname_prefix in SECTIONS:
        content = read_text(f"{fname_prefix}-{weekday_en}.txt")
        content_json = json.dumps(content, ensure_ascii=False)
        content_escaped = html.escape(content)
        section_blocks.append(f"""
    <section class="card">
      <div class="card-head">
        <h2>{label}</h2>
        <button class="copy-btn" onclick="copySection('{key}', this)">복사</button>
      </div>
      <textarea id="ta-{key}" class="preview" readonly>{content_escaped}</textarea>
      <script>window.__content_{key} = {content_json};</script>
    </section>""")

    sections_html = "\n".join(section_blocks)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>오늘의 브리핑</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 16px;
    font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    background: #f4f4f5;
    color: #1a1a1a;
  }}
  h1 {{
    font-size: 18px;
    margin: 4px 0 16px;
    text-align: center;
    color: #444;
  }}
  .card {{
    background: #fff;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .card-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }}
  .card-head h2 {{
    font-size: 17px;
    margin: 0;
  }}
  .copy-btn {{
    font-size: 15px;
    font-weight: 600;
    padding: 10px 20px;
    border: none;
    border-radius: 10px;
    background: #3b82f6;
    color: #fff;
    cursor: pointer;
    min-width: 76px;
  }}
  .copy-btn.copied {{
    background: #22c55e;
  }}
  .preview {{
    width: 100%;
    height: 130px;
    resize: vertical;
    font-size: 13px;
    line-height: 1.5;
    color: #555;
    border: 1px solid #e5e5e5;
    border-radius: 8px;
    padding: 8px;
    background: #fafafa;
    white-space: pre-wrap;
  }}
</style>
</head>
<body>
  <h1>📅 {date_line}</h1>
  {sections_html}

<script>
function copySection(key, btn) {{
  const text = window['__content_' + key];
  const done = () => {{
    const original = btn.textContent;
    btn.textContent = '복사됨';
    btn.classList.add('copied');
    setTimeout(() => {{
      btn.textContent = original;
      btn.classList.remove('copied');
    }}, 1200);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(key, done));
  }} else {{
    fallbackCopy(key, done);
  }}
}}
function fallbackCopy(key, done) {{
  const ta = document.getElementById('ta-' + key);
  ta.style.position = 'fixed';
  ta.style.top = '0';
  ta.focus();
  ta.select();
  try {{
    document.execCommand('copy');
    done();
  }} catch (e) {{
    alert('복사에 실패했습니다. 아래 미리보기 텍스트를 직접 길게 눌러 복사해주세요.');
  }}
}}
</script>
</body>
</html>
"""


def main():
    html_content = build_html()
    with open("briefing.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("briefing.html 생성 완료")


if __name__ == "__main__":
    main()
