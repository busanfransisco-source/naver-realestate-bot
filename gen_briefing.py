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
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        if path.startswith("analysis"):
            return "(오늘의 분석이 아직 준비되지 않았습니다)"
        return f"(파일을 찾을 수 없습니다: {path})"


FAILURE_PATTERN = re.compile(r"가져오기 실패|가져오지 못했습니다|파일을 찾을 수 없습니다")


def has_fetch_failure(content):
    return bool(FAILURE_PATTERN.search(content or ""))


def read_section_text(prefix, weekday):
    """실패 문구를 발행하지 않고, 직전 정상 파일이 있으면 그대로 유지한다."""
    current = read_text(f"{prefix}-{weekday}.txt")
    if not has_fetch_failure(current):
        return current

    # 당일 수집이 실패했더라도 기존 정상 prefix.txt나 직전 요일 자료를 재사용한다.
    # 같은 실행에서 current/prefix가 모두 실패 문구로 바뀐 과거 파일도 건너뛴다.
    weekday_index = WEEKDAY_EN.index(weekday) if weekday in WEEKDAY_EN else 0
    previous_weekdays = [
        WEEKDAY_EN[(weekday_index - offset) % len(WEEKDAY_EN)]
        for offset in range(1, len(WEEKDAY_EN))
    ]
    fallback_paths = [Path(f"{prefix}.txt")]
    fallback_paths.extend(Path(f"{prefix}-{day}.txt") for day in previous_weekdays)
    fallback_paths.extend(sorted(Path(".").glob(f"{prefix}-20??-??-??.txt"), reverse=True))

    seen = set()
    for path in fallback_paths:
        if path in seen:
            continue
        seen.add(path)
        candidate = read_text(str(path))
        if not has_fetch_failure(candidate):
            print(f"{prefix}: 수집 실패 파일 대신 직전 정상 파일 사용 ({path.name})")
            return candidate

    print(f"{prefix}: 정상 대체 파일이 없어 이번 발행에서 비움")
    return ""


def is_fresh_analysis(content, today):
    """analysis 파일 안에 적힌 날짜가 오늘 날짜와 일치하는지 확인 (방마다 날짜 형식이 달라 여러 패턴을 시도)"""
    first_lines = "\n".join(content.split("\n")[:2])
    m = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", first_lines)
    if not m:
        m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", first_lines)
    if not m:
        return False
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (y, mo, d) == (today.year, today.month, today.day)


SECTIONS = [
    ("fortune", "🔮 오늘의 운세", "fortune"),
    ("weather", "☀️ 날씨", "weather"),
    ("shortnews", "⚡ 오늘의 퀵뉴스", "shortnews"),
    ("subs", "🏗️ 청약 소식", "subs"),
    ("trend", "📈 부동산 주간 시세동향", "trend"),
    ("fuelfx", "⛽ 기름값·환율", "fuelfx"),
    ("metalcoin", "🥇 금·은·코인", "metalcoin"),
    ("books", "📚 주간 베스트셀러", "books"),
    ("realestate", "🏠 부동산 뉴스", "realestate"),
    ("world", "🌏 세계 뉴스", "world"),
    ("finance", "🏦 금융 뉴스", "finance"),
    ("ai", "🤖 AI 뉴스", "ai"),
    ("analysis3", "📰 대한민국 정책분석", "analysis3"),
    ("analysis4", "📰 여러분의 부동산 정책분석", "analysis4"),
    ("analysis5", "📰 월부길 정책분석", "analysis5"),
    ("analysis2", "📰 부알남 정책분석", "analysis2"),
    ("analysis6", "📰 부부투 정책분석", "analysis6"),
    ("analysis1", "📰 비밀노트 정책 분석", "analysis1"),
]


FIREBASE_CONFIG = {
    "apiKey": "AIzaSyBL3jjmzmNrYjqSc5jzt1F0kcaLLS55bEY",
    "authDomain": "naver-realestate-briefing.firebaseapp.com",
    "projectId": "naver-realestate-briefing",
    "storageBucket": "naver-realestate-briefing.firebasestorage.app",
    "messagingSenderId": "515367104622",
    "appId": "1:515367104622:web:c746a72e7fa0090663767f",
}


GATE_HTML = """<div id="auth-gate" style="position:fixed;inset:0;background:#f4f4f5;z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;">
  <div style="background:#fff;border-radius:14px;padding:24px;max-width:340px;width:100%;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    <h2 style="margin:0 0 16px;font-size:18px;text-align:center;">🏠 오늘의 브리핑</h2>
    <div id="gate-loading" style="text-align:center;color:#999;font-size:14px;">확인 중...</div>
    <div id="gate-login" style="display:none;">
      <input id="gate-email" type="email" placeholder="이메일" style="width:100%;padding:10px;margin-bottom:8px;border:1px solid #e5e5e5;border-radius:8px;font-size:14px;box-sizing:border-box;">
      <input id="gate-password" type="password" placeholder="비밀번호" style="width:100%;padding:10px;margin-bottom:12px;border:1px solid #e5e5e5;border-radius:8px;font-size:14px;box-sizing:border-box;">
      <div id="gate-error" style="color:#e11d48;font-size:12px;margin-bottom:8px;display:none;"></div>
      <button id="gate-login-btn" style="width:100%;padding:10px;border:none;border-radius:8px;background:#3b82f6;color:#fff;font-size:14px;font-weight:600;margin-bottom:8px;">로그인</button>
      <button id="gate-signup-btn" style="width:100%;padding:10px;border:1px solid #3b82f6;border-radius:8px;background:#fff;color:#3b82f6;font-size:14px;font-weight:600;">회원가입 신청</button>
    </div>
    <div id="gate-pending" style="display:none;text-align:center;">
      <p style="font-size:14px;color:#555;line-height:1.6;">⏳ 승인 대기중입니다.<br>관리자 승인 후 이용하실 수 있어요.</p>
      <button id="gate-logout-btn" style="margin-top:8px;padding:8px 16px;border:1px solid #ccc;border-radius:8px;background:#fff;color:#555;font-size:13px;">로그아웃</button>
    </div>
  </div>
</div>
"""


GATE_SCRIPT_TEMPLATE = """<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-auth-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.7.1/firebase-firestore-compat.js"></script>
<script>
(function() {
  var firebaseConfig = __FIREBASE_CONFIG__;
  firebase.initializeApp(firebaseConfig);
  var auth = firebase.auth();
  var db = firebase.firestore();

  function show(id) {
    ['gate-loading', 'gate-login', 'gate-pending'].forEach(function(x) {
      document.getElementById(x).style.display = (x === id) ? 'block' : 'none';
    });
  }

  function revealContent(isAdmin) {
    document.getElementById('auth-gate').style.display = 'none';
    document.getElementById('main-content').style.display = 'block';
    var bar = document.createElement('div');
    bar.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#fff;border-bottom:1px solid #eee;padding:8px 16px;display:flex;justify-content:flex-end;gap:8px;z-index:100;font-size:12px;';
    if (isAdmin) {
      var a = document.createElement('a');
      a.href = 'admin.html';
      a.textContent = '🔑 관리자 승인 페이지';
      a.style.cssText = 'color:#3b82f6;text-decoration:none;font-weight:600;';
      bar.appendChild(a);
    }
    var out = document.createElement('button');
    out.textContent = '로그아웃';
    out.style.cssText = 'border:1px solid #ddd;border-radius:12px;background:#fff;padding:4px 10px;color:#888;';
    out.onclick = function() { auth.signOut(); };
    bar.appendChild(out);
    document.body.insertBefore(bar, document.body.firstChild);
    document.body.style.paddingTop = '40px';
  }

  auth.onAuthStateChanged(function(user) {
    if (!user) { show('gate-login'); return; }
    db.collection('users').doc(user.uid).get().then(function(doc) {
      if (doc.exists && doc.data().approved === true) {
        revealContent(doc.data().isAdmin === true);
      } else {
        show('gate-pending');
      }
    }).catch(function() { show('gate-pending'); });
  });

  document.getElementById('gate-login-btn').addEventListener('click', function() {
    var email = document.getElementById('gate-email').value.trim();
    var pw = document.getElementById('gate-password').value;
    var err = document.getElementById('gate-error');
    err.style.display = 'none';
    auth.signInWithEmailAndPassword(email, pw).catch(function(e) {
      err.textContent = '로그인 실패: 이메일 또는 비밀번호를 확인해주세요.';
      err.style.display = 'block';
    });
  });

  document.getElementById('gate-signup-btn').addEventListener('click', function() {
    var email = document.getElementById('gate-email').value.trim();
    var pw = document.getElementById('gate-password').value;
    var err = document.getElementById('gate-error');
    err.style.display = 'none';
    if (!email || !pw || pw.length < 6) {
      err.textContent = '이메일과 6자 이상 비밀번호를 입력해주세요.';
      err.style.display = 'block';
      return;
    }
    auth.createUserWithEmailAndPassword(email, pw).then(function(cred) {
      return db.collection('users').doc(cred.user.uid).set({
        email: email,
        approved: false,
        isAdmin: false,
        createdAt: firebase.firestore.FieldValue.serverTimestamp()
      });
    }).then(function() {
      show('gate-pending');
    }).catch(function(e) {
      err.textContent = (e.code === 'auth/email-already-in-use') ? '이미 가입된 이메일입니다.' : ('가입 실패: ' + e.message);
      err.style.display = 'block';
    });
  });

  document.getElementById('gate-logout-btn').addEventListener('click', function() {
    auth.signOut();
  });
})();
</script>
"""


def build_html():
    now = datetime.now(KST)
    weekday_en = WEEKDAY_EN[now.weekday()]
    weekday_kr = WEEKDAY_KR[now.weekday()]
    date_line = f"{now.year}년 {now.month}월 {now.day}일 {weekday_kr}"
    build_date = now.strftime("%Y-%m-%d")

    section_blocks = []
    for number, (key, label, fname_prefix) in enumerate(SECTIONS, start=1):
        content = read_section_text(fname_prefix, weekday_en)
        if key.startswith("analysis") and not is_fresh_analysis(content, now):
            content = "(오늘의 분석이 아직 준비되지 않았습니다)"
        content_json = json.dumps(content, ensure_ascii=False)
        content_escaped = html.escape(content)
        section_blocks.append(f"""
<section class="card">
  <div class="card-head">
    <h2>{number}. {label}</h2>
    <button class="copy-btn" onclick="copySection('{key}', this)">복사</button>
  </div>
  <textarea id="ta-{key}" class="preview" readonly>{content_escaped}</textarea>
  <script>window.__content_{key} = {content_json};</script>
</section>""")

    sections_html = "\n".join(section_blocks)
    firebase_config_json = json.dumps(FIREBASE_CONFIG)
    gate_script = GATE_SCRIPT_TEMPLATE.replace("__FIREBASE_CONFIG__", firebase_config_json)

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
.update-time {{
  text-align: center;
  font-size: 12px;
  color: #999;
  margin: -12px 0 16px;
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
{GATE_HTML}
<div id="main-content" style="display:none;">
<h1>📅 {date_line}</h1>
<p class="update-time">🕐 마지막 업데이트: {now.month}월 {now.day}일 {now.strftime('%H:%M')}</p>
{sections_html}
</div>

<script>
// 홈 화면/사파리가 옛 사본을 보여줄 때: 페이지 날짜가 오늘과 다르면 캐시를 우회해 1회 다시 불러온다
var BUILD_DATE = '{build_date}';
(function() {{
  var d = new Date();
  var today = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  if (today !== BUILD_DATE && location.search.indexOf('r=') === -1) {{
    location.replace(location.pathname + '?r=' + Date.now());
  }}
}})();

function markCopied(btn) {{
  const original = btn.textContent;
  btn.textContent = '복사됨';
  btn.classList.add('copied');
  setTimeout(() => {{
    btn.textContent = original;
    btn.classList.remove('copied');
  }}, 1200);
}}

function copySection(key, btn) {{
  // execCommand는 동기적으로 바로 결과가 나오고 권한 프롬프트로 멈추는 일이
  // 없어서 이걸 기본으로 쓴다. navigator.clipboard는 일부 브라우저(특히
  // 자동화/인앱 웹뷰 환경)에서 권한 대기 상태로 무한정 멈출 수 있어서
  // 보조 수단으로만 쓴다.
  const ta = document.getElementById('ta-' + key);
  let copied = false;
  try {{
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    copied = document.execCommand('copy');
  }} catch (e) {{
    copied = false;
  }}

  if (copied) {{
    markCopied(btn);
    return;
  }}

  const text = window['__content_' + key];
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(() => markCopied(btn)).catch(() => {{
      alert('복사에 실패했습니다. 아래 미리보기 텍스트를 직접 길게 눌러 복사해주세요.');
    }});
  }} else {{
    alert('복사에 실패했습니다. 아래 미리보기 텍스트를 직접 길게 눌러 복사해주세요.');
  }}
}}
</script>

{gate_script}
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
