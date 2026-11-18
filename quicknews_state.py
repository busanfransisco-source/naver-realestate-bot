"""Fail-closed quicknews publication; never relabel preserved source dates."""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

KST = timezone(timedelta(hours=9))
STATUS = 'shortnews-status.txt'
NOTICE = '[퀵뉴스 갱신 실패: 아래 원고는 표시된 원래 날짜의 자료입니다.]'
RETAINED_NEWS_NOTICE = '[이번 갱신은 완료되지 않아 오늘 먼저 확보한 기사를 전합니다.]'
EMPTY = '[퀵뉴스 수집 실패: 검증된 원고가 없습니다.]'
ROWS = re.compile(r'^\S+ \((톱뉴스|정치|경제|사회|국제|날씨)\) (.+)$', re.M)


def body_issues(body, *, require_polite=True):
    from daum_news_fetch import polite_news_body
    from quicknews_sources import source_issues, URL
    rows = ROWS.findall(body)
    issues = []
    if len(rows) < 8 or not {'정치', '경제', '사회', '국제'} <= {label for label, _ in rows}:
        issues.append('quicknews: insufficient news coverage')
    if not rows:
        issues.append('quicknews: no valid news articles')
    elif require_polite and not polite_news_body(body):
        issues.append('quicknews: explanations must use polite endings')
    issues.extend(source_issues(body))
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if ROWS.fullmatch(line) and (i+1 == len(lines) or not URL.fullmatch(lines[i+1])):
            issues.append('quicknews: original article URL missing')
    if not re.search(r'^\d{2,4}년 \d{1,2}월 \d{1,2}일', body):
        issues.append('quicknews: original date missing')
    return list(dict.fromkeys(issues))


def atomic_text(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def commit_candidate(body, now, root=Path('.')):
    root = Path(root)
    issues = body_issues(body)
    stamp = re.match(r'(\d{2,4})년 (\d{1,2})월 (\d{1,2})일', body)
    if stamp:
        y,m,d = map(int,stamp.groups())
        try:
            if datetime(y+2000 if y<100 else y,m,d).date() != now.date():
                issues.append('quicknews: candidate date is not today')
        except ValueError:
            issues.append('quicknews: invalid date')
    status = dict(attemptedAtKst=now.isoformat(), status='failed' if issues else 'ok', issues=issues)
    current = root/'shortnews.txt'
    if issues:
        status['preservedSha256'] = hashlib.sha256(current.read_bytes()).hexdigest() if current.exists() else None
    if not issues:
        for name in ('shortnews.txt','shortnews-'+('mon','tue','wed','thu','fri','sat','sun')[now.weekday()]+'.txt'):
            atomic_text(root/name,body)
    atomic_text(root/STATUS,json.dumps(status,ensure_ascii=False)+'\n')
    return not issues


def load_report(root=Path('.'), now=None):
    root = Path(root)
    now = now or datetime.now(KST)
    failed = False
    status = None
    try:
        status = json.loads((root/STATUS).read_text(encoding='utf-8'))
        if not isinstance(status, dict):
            raise ValueError('invalid status')
        failed = status.get('status') != 'ok'
    except FileNotFoundError:
        pass
    except (ValueError, OSError):
        status = None
        failed = True
    try:
        raw = (root/'shortnews.txt').read_bytes()
        body = raw.decode('utf-8').strip()
    except (OSError, UnicodeError):
        return EMPTY
    # The existing Apps Script backup exports verified headlines, not polite
    # summaries. Preserve its date and URLs; do not apply the collector-only
    # narrative style gate to display an already stored source.
    if body_issues(body, require_polite=False):
        return EMPTY
    stamp = re.match(r'(\d{2,4})년 (\d{1,2})월 (\d{1,2})일', body)
    try:
        y,m,d = map(int,stamp.groups())
        source_day = datetime(y+2000 if y<100 else y,m,d).date()
    except (ValueError, AttributeError):
        return EMPTY
    if source_day > now.date():
        return EMPTY
    if source_day < now.date():
        return NOTICE+'\n'+body
    # The morning publisher already carries a visible same-day retention notice.
    # Do not add a second prefix that would diverge from the signed sender body.
    if failed and body.endswith(RETAINED_NEWS_NOTICE):
        return body
    return NOTICE+'\n'+body if failed else body


def merge_status(source, root=Path('.'), now=None):
    """Carry dawn diagnostics without allowing an older run to erase recovery."""
    now = now or datetime.now(KST)
    root = Path(root)
    def read(path):
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        stamp = datetime.fromisoformat(value['attemptedAtKst'])
        if stamp.tzinfo is None or value['status'] not in ('ok', 'failed'):
            raise ValueError('invalid quicknews status')
        return value, stamp
    try:
        incoming, stamp = read(source)
        if stamp.date() != now.date() or stamp > now:
            return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        _, current = read(root/STATUS)
        if current >= stamp:
            return False
    except (OSError, ValueError, KeyError, TypeError):
        pass
    atomic_text(root/STATUS, json.dumps(incoming, ensure_ascii=False)+'\n')
    return True
