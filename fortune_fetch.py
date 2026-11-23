# -*- coding: utf-8 -*-
"""
askjiyun.com 오늘의 운세 -> fortune.txt / fortune-YYYY-MM-DD.txt (GitHub Actions용)
------------------------------------------------------------------------------
이 게시판은 "업로드 날짜"가 아니라 "글 제목에 적힌 날짜"가 그 날의 운세다.
운영자가 여러 날짜치를 미리 몰아서 올려두기 때문에, 게시판 맨 위 글이 항상
오늘 날짜인 것은 아니다. 그래서 제목("M월 D일")으로 직접 검색해서 오늘
날짜와 정확히 일치하는 글을 찾는다. 같은 제목이 매년 반복되므로
(예: "7월 11일"은 2013~2026년에 각각 존재) 그 중 document_srl이 가장 큰
(=가장 최근 연도) 글을 선택한다.
"""

import re
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from pathlib import Path

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

BASE = "https://askjiyun.com/"
ANIMAL_HEADING_RE = re.compile(r"^〈[^〉]+띠〉$")
SCORE_LINE_RE = re.compile(r"^운세지수\s*\d+%")
ANIMALS = ("쥐", "소", "범", "토끼", "용", "뱀", "말", "양", "원숭이", "닭", "개", "돼지")
FALLBACK_BASE = "https://www.news2day.co.kr"
UNAVAILABLE = "당일 운세 자료를 확보하지 못했습니다. 갱신을 기다리고 있습니다."


def valid_report(report, day):
    from morning_briefing_contract import _body_issues
    if _body_issues("fortune", report, day, {}):
        return False
    blocks = re.split(r"(?=^〈[^〉]+띠〉$)", report, flags=re.M)[1:]
    if len(blocks) != len(ANIMALS):
        return False
    for block, animal in zip(blocks, ANIMALS):
        match = re.fullmatch(
            r"〈" + animal + r"띠〉\s*\n(.+?)\n\s*운세지수\s*(\d+)%\.\s*"
            r"금전\s*(\d+)\s+건강\s*(\d+)\s+애정\s*(\d+)\s*",
            block, re.S)
        if not match or not match[1].strip() or any(not 0 <= int(value) <= 100 for value in match.groups()[1:]):
            return False
    return True


def saved_report(now=None, root="."):
    now = now or datetime.now(KST)
    root = Path(root)
    for name in (f"fortune-{now.date().isoformat()}.txt",
                 f"fortune-{WEEKDAY_EN[now.weekday()]}.txt", "fortune.txt"):
        try:
            body = (root / name).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if valid_report(body, now.date()):
            return body
    return ""


def load_report(now=None, root="."):
    return saved_report(now, root) or UNAVAILABLE


def format_animal_blocks(lines):
    """띠 제목·본문·운세지수를 사용자가 정한 고정 줄바꿈으로 조립한다."""
    blocks = []
    current = None

    for line in lines:
        if ANIMAL_HEADING_RE.fullmatch(line):
            if current:
                blocks.append(current)
            current = {"heading": line, "body": [], "score": ""}
        elif current is not None and SCORE_LINE_RE.match(line):
            current["score"] = line
        elif current is not None:
            current["body"].append(line)

    if current:
        blocks.append(current)

    # 구조가 깨진 원문을 억지로 재조립하지 않는다.
    if not blocks or any(not block["body"] or not block["score"] for block in blocks):
        return "\n".join(lines)

    formatted = []
    for block in blocks:
        body = " ".join(block["body"])
        # 제목 뒤 빈 줄 1개, 본문 뒤 빈 줄 2개를 항상 고정한다.
        formatted.append(
            f'{block["heading"]}\n\n{body}\n\n\n{block["score"]}'
        )
    # 한 띠의 지수와 다음 띠 제목 사이는 빈 줄 1개로 고정한다.
    return "\n\n".join(formatted)


def find_today_document_srl(month, day):
    keyword = f"{month}월 {day}일"
    url = BASE + "?mid=today&search_target=title&search_keyword=" + quote(keyword)
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    best_srl = None
    title_needle = f"오늘의 운세, {keyword}"

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text != title_needle:
            continue
        m = re.search(r"document_srl=(\d+)", a["href"])
        if not m:
            continue
        srl = int(m.group(1))
        if best_srl is None or srl > best_srl:
            best_srl = srl

    return best_srl, title_needle


def fetch_document_text(srl, title_needle, now=None):
    url = f"{BASE}?mid=today&document_srl={srl}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    article = soup.select_one(".xe_content")
    if article is None or title_needle not in article.get_text(" ", strip=True):
        raise ValueError("운세 원문 제목 또는 본문 불일치")
    posted = soup.select_one('.date[title="등록일"] strong')
    if posted is None:
        raise ValueError("운세 원문 게시일 누락")
    posted_day = datetime.strptime(posted.get_text(strip=True), "%Y.%m.%d").date()
    if not 0 <= ((now or datetime.now(KST)).date() - posted_day).days <= 21:
        raise ValueError("운세 원문 게시일이 오래되었거나 미래입니다")

    # 구분자를 넣지 않고(빈 문자열) 이어붙인다.
    full_text = article.get_text("")
    full_text = re.sub(r"[ \t]+", " ", full_text)

    # 이 사이트는 숫자/기호를 낱개 텍스트 노드로 쪼개서 서버가 내려주고,
    # 실제로는 브라우저에서 JS가 화면 표시용으로 공백을 정리해준다.
    # requests로 받는 원본 HTML(=JS 실행 전)에는 그 공백이 그대로 남아있으므로
    # 자주 나타나는 패턴을 규칙 기반으로 후처리해서 정리한다.
    full_text = re.sub(r"\s+년생", "년생", full_text)
    full_text = re.sub(r"\s+([.%,)])", r"\1", full_text)
    full_text = re.sub(r"([(〈])\s+", r"\1", full_text)
    full_text = re.sub(r"\s+([〉])", r"\1", full_text)

    # 실제 본문(띠별 운세)은 항상 "〈...띠〉" 로 시작하므로 그
    # 첫 등장 지점을 본문 시작으로 삼는다.
    start_idx = full_text.find("〈")
    end_idx = full_text.find("이 게시물을")

    # 본문(〈) 바로 앞에 있는 "[음력 N월 N일] 일진: OO(한자)" 줄을
    # 헤드라인 2번째 줄로 쓰기 위해 별도로 뽑아둔다. 혹시라도 공백이
    # 남아있는 경우까지 대비해 공백을 다 지운 뒤 매칭하고, 자리표시자로
    # 다시 정갈하게 조립한다.
    lunar_line = ""
    if start_idx != -1:
        # 거리 제한 없이 본문(〈) 앞부분 전체에서 찾는다 (사이트가 랜덤하게
        # 더 잘게 쪼개서 내려줄 때 고정 길이 윈도우로는 놓칠 수 있어서).
        window = full_text[:start_idx]
        compact = re.sub(r"\s+", "", window)
        m = re.search(r"\[음력(\d+)월(\d+)일\]일진:?([^\(\)\[\]]+?)(?:\(([^)]*)\))?(?=\[|$)", compact)
        if m:
            lm, ld, ganji, hanja = m.groups()
            lunar_line = f"[음력 {lm}월 {ld}일] 일진: {ganji.strip()}" + (f"({hanja})" if hanja else "")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        body = full_text[start_idx:end_idx]
    else:
        body = full_text[start_idx:] if start_idx != -1 else ""

    # "...받는다.운세지수" 처럼 마지막 문장 뒤 공백까지 같이 지워진 경우 복원
    body = re.sub(r"\.(운세지수)", r". \1", body)

    # 띠별 문단 앞에서 줄바꿈을 넣어 보기 좋게 정리
    body = re.sub(r"\s*(〈[^〉]+〉)\s*", r"\n\n\1\n", body)
    # "운세지수 NN%. 금전 NN 건강 NN 애정 NN" 뒤에도 문단 구분
    body = re.sub(r"(애정\s*\d+)\s*", r"\1\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)

    lines = [ln.strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    body = format_animal_blocks(lines)
    return lunar_line, body


def fetch_syndicated_report(now):
    """Read the same Ji-yun forecast from its independently hosted publisher."""
    response = requests.get(
        FALLBACK_BASE + "/rest/search",
        params={"searchText": "지윤철학원", "searchType": "all",
                "from": (now.date() - timedelta(days=1)).isoformat(),
                "to": now.date().isoformat(), "page": 1, "sort": "date"},
        headers=HEADERS, timeout=12)
    response.raise_for_status()
    title_day = f"{now.year}년 {now.month}월 {now.day}일"
    data = response.json()
    rows = data.get("list") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("예비 제공처 검색 응답 불일치")
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("title"), str):
            continue
        title = BeautifulSoup(row.get("title", ""), "html.parser").get_text(" ", strip=True)
        if (f"[지윤철학원의 오늘의 운세] {title_day} " not in title
                or not re.fullmatch(r"\d{14}", str(row.get("id", "")))):
            continue
        try:
            released = datetime.fromisoformat(row["releaseDate"])
        except (KeyError, TypeError, ValueError):
            continue
        if released.tzinfo is not None and released <= now:
            candidates.append(row)
    if not candidates:
        raise ValueError("예비 제공처의 당일 운세 없음")
    # This is the article URL mapping used by the publisher's own search page.
    row = max(candidates, key=lambda entry: entry["releaseDate"])
    response = requests.get(FALLBACK_BASE + "/article/" + row["id"], headers=HEADERS, timeout=12)
    response.raise_for_status()
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    article = soup.select_one(".view_con")
    if not soup.title or title_day not in soup.title.get_text() or article is None:
        raise ValueError("예비 제공처 원문 날짜/본문 불일치")
    text = article.get_text(" ", strip=True)
    match = re.search(re.escape(title_day) + r"\s*[^()]*\(음력\s*(\d+)월\s*(\d+)일\)\s*일진:\s*(\S+)", text)
    if not match:
        raise ValueError("예비 제공처 원문 날짜/음력 누락")
    lunar = f"[음력 {match[1]}월 {match[2]}일] 일진: {match[3]}"
    lines = []
    for paragraph in article.find_all("p"):
        text = re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True))
        match = re.fullmatch(r"오늘의\s*(쥐|소|호랑이|범|토끼|용|뱀|말|양|원숭이|닭|개|돼지)\([^()]+\)띠 운세\s*->\s*(.+?)\s*(운세지수\s*\d+%.*)", text)
        if match:
            animal = "범" if match[1] == "호랑이" else match[1]
            lines.extend([f"〈{animal}띠〉", match[2], match[3]])
    return f"오늘의 운세, {now.month}월 {now.day}일\n{lunar}\n\n" + format_animal_blocks(lines)


def build_report(now=None):
    now = now or datetime.now(KST)
    header = f"오늘의 운세, {now.month}월 {now.day}일"
    try:
        srl, title = find_today_document_srl(now.month, now.day)
        if srl:
            lunar, body = fetch_document_text(srl, title, now)
            report = header + ("\n" + lunar if lunar else "") + "\n\n" + body
            if valid_report(report, now.date()):
                return report
    except (requests.RequestException, ValueError, TypeError, KeyError):
        pass
    report = fetch_syndicated_report(now)
    if not valid_report(report, now.date()):
        raise ValueError("당일 12개 띠 운세 검증 실패")
    return report


def main():
    now = datetime.now(KST)
    existing = saved_report(now)
    if existing:
        print(existing)
        return 0
    try:
        report = build_report(now)
        if datetime.now(KST).date() != now.date() or not valid_report(report, now.date()):
            raise ValueError("운세 수집 날짜/본문 불일치")
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"운세 수집 실패: {type(exc).__name__}; 기존 원자료 보존", file=sys.stderr)
        return 1
    for name in ("fortune.txt", f"fortune-{now.date().isoformat()}.txt",
                 f"fortune-{WEEKDAY_EN[now.weekday()]}.txt"):
        target = Path(name)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(report, encoding="utf-8")
        temporary.replace(target)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
