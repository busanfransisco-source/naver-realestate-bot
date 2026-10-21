"""Pure, fail-closed contract for the nine morning briefing boxes.

No collection, filesystem access, network calls or delivery happens here.
Dates in the report and weekly source periods are deliberately separate.
"""
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9))
BOX_KEYS = ('fortune', 'weather', 'shortnews', 'subs', 'trend', 'fuelfx',
            'metalcoin', 'books', 'realestate')
WEATHER_CITIES = ('서울', '인천', '수원', '춘천', '강릉', '청주', '대전', '세종',
                  '전주', '광주', '대구', '부산', '울산', '창원', '제주')
MAX_AGE = timedelta(hours=4)
FAILURE = re.compile(
    r'가져오기 실패|가져오지 못했습니다|파일을 찾을 수 없습니다|수집 실패|'
    r'수집에 실패|집계 대기|수집 중입니다|준비되지 않았습니다|확인 불가|'
    r'직전 정상값|아직 찾지 못했습니다|추출하지 못했습니다|\ufffd')


def _aware(value, name):
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
        return stamp.astimezone(KST)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name}: invalid timezone-aware timestamp') from exc


def _hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def body_sha256(body):
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def snapshot_sha256(snapshot):
    return _hash({key: value for key, value in snapshot.items() if key != 'snapshotSha256'})


def _body_date(key, body, today):
    if key == 'fortune':
        match = re.search(r'오늘의 운세,\s*(\d{1,2})월\s*(\d{1,2})일', body[:100])
        return date(today.year, *map(int, match.groups())) if match else None
    match = re.search(r'(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일', body[:150])
    if not match:
        return None
    year, month, day = map(int, match.groups())
    return date(year + 2000 if year < 100 else year, month, day)


def _body_issues(key, body, today, evidence):
    issues = []
    # The collector's complete, verified zero-subscription digest is naturally
    # only ~70 characters; do not confuse this explicit zero with missing data.
    verified_empty = (key == 'subs' and isinstance(body, str)
                      and '청약 접수 단지 (전국, 2주 이내)' in body
                      and '(2주 이내 접수 예정인 단지가 없습니다)' in body)
    if not isinstance(body, str) or len(body.strip()) < (60 if verified_empty else 80):
        return [f'{key}: body missing or shorter than 80 characters']
    if FAILURE.search(body):
        issues.append(f'{key}: incomplete or cached-fallback marker')
    if key != 'trend':
        try:
            if _body_date(key, body, today) != today:
                issues.append(f'{key}: report date is not today')
        except ValueError:
            issues.append(f'{key}: invalid report date')
    if key == 'fortune':
        animals = re.findall(r'^〈([^〉]+띠)〉$', body, re.M)
        if len(animals) != 12 or len(set(animals)) != 12 or len(re.findall(r'^운세지수\s*\d+%', body, re.M)) != 12:
            issues.append('fortune: twelve complete zodiac sections required')
    elif key == 'weather':
        cities = re.findall(r'^✫([^\s(]+)\(', body, re.M)
        if len(cities) != 15 or set(cities) != set(WEATHER_CITIES):
            issues.append('weather: all fifteen cities required')
        if len(re.findall(r'^✫[^\n]+-?\d+℃\s*~\s*-?\d+℃$', body, re.M)) != 15:
            issues.append('weather: complete temperature ranges required')
    elif key == 'shortnews':
        summaries = re.findall(r'^\S+ \((톱뉴스|정치|경제|사회|국제|날씨)\) (.+)$', body, re.M)
        labels = {label for label, _ in summaries}
        if len(summaries) < 8 or not {'정치', '경제', '사회', '국제'}.issubset(labels):
            issues.append('shortnews: insufficient news coverage')
        if any(not re.search(r'(?:니다|요|죠)[.!?][\"\u201d\u2019\u0027)]*$', summary)
               for _, summary in summaries):
            issues.append('shortnews: explanations must use complete polite sentences')
    elif key == 'subs':
        if ('청약 접수 단지' not in body or
                not (re.search(r'^\[[^\n]+\].*\| 접수 \d+/\d+~\d+/\d+', body, re.M)
                     or '(2주 이내 접수 예정인 단지가 없습니다)' in body)):
            issues.append('subs: verified subscription rows or explicit zero result required')
    elif key == 'trend':
        for token in ('전국 아파트', '지역별 매매가 변동률', '지역별 전세가 변동률'):
            if token not in body:
                issues.append(f'trend: missing {token}')
    elif key == 'fuelfx':
        for token in ('휘발유', '경유', '미국 달러', '일본 엔'):
            if not re.search(re.escape(token) + r'[^\n]*\d[\d,.]*원', body):
                issues.append(f'fuelfx: missing priced {token}')
    elif key == 'metalcoin':
        for token in ('국제 금', '국내 금', '국제 은'):
            if not re.search(re.escape(token) + r'[^\n]*\d[\d,.]*', body):
                issues.append(f'metalcoin: missing priced {token}')
        coin_section = body.split('🪙')[-1] if '🪙' in body else ''
        coins = re.findall(r'^(\S+) [\d,]+(?:\.\d+)?원(?:\s|$)', coin_section, re.M)
        if len(coins) != 10 or len(set(coins)) != 10 or '비트코인' not in coins:
            issues.append('metalcoin: ten distinct coins including bitcoin required')
    elif key == 'books':
        ranks = re.findall(r'^(\d+)\.\s+(.+)$', body, re.M)
        if ([int(number) for number, _ in ranks] != list(range(1, 11))
                or 'YES24 국내도서 주간 베스트 TOP 10' not in body):
            issues.append('books: YES24 domestic weekly top ten required')
        period = re.search(r'^📅 집계 기간: (\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2})$', body, re.M)
        if not period or list(period.groups()) != [evidence.get('booksPeriodStart'), evidence.get('booksPeriodEnd')]:
            issues.append('books: body and source period differ')
    elif key == 'realestate':
        urls = re.findall(r'^https://\S+$', body, re.M)
        if len(set(urls)) < 2:
            issues.append('realestate: at least two distinct article links required')
    return issues


def snapshot_issues(snapshot, now):
    """Return safe diagnostic reasons. No untrusted report body is echoed."""
    now = _aware(now, 'now')
    today = now.date()
    if not isinstance(snapshot, dict):
        return ['snapshot must be an object']
    issues = []
    if snapshot.get('schemaVersion') != 1 or isinstance(snapshot.get('schemaVersion'), bool):
        issues.append('unsupported snapshot schema')
    if snapshot.get('deliveryDateKst') != today.isoformat():
        issues.append('snapshot delivery date is not today')
    midnight = datetime.combine(today + timedelta(days=1), time(), KST)
    try:
        generated = _aware(snapshot.get('generatedAtKst'), 'generatedAtKst')
        expires = _aware(snapshot.get('expiresAtKst'), 'expiresAtKst')
        if generated.date() != today or not timedelta(0) <= now - generated <= MAX_AGE:
            issues.append('snapshot generation is future, stale or not today')
        if expires != midnight or expires <= now:
            issues.append('snapshot expiry must be next KST midnight')
    except ValueError as exc:
        issues.append(str(exc))
    evidence = snapshot.get('evidence')
    if not isinstance(evidence, dict):
        evidence = {}
        issues.append('source evidence missing')
    try:
        trend_stamp = _aware(evidence.get('trendCheckedAtKst'), 'trend source check')
        if not timedelta(0) <= now - trend_stamp <= timedelta(days=8):
            issues.append('weekly trend source check outside eight days')
    except ValueError as exc:
        issues.append(str(exc))
    try:
        start = date.fromisoformat(evidence.get('booksPeriodStart'))
        end = date.fromisoformat(evidence.get('booksPeriodEnd'))
        if start.weekday() != 0 or end - start != timedelta(days=6) or not 1 <= (today - end).days <= 8:
            issues.append('YES24 weekly source period invalid or stale')
    except (ValueError, TypeError):
        issues.append('YES24 weekly source period missing')
    boxes = snapshot.get('boxes')
    if not isinstance(boxes, list) or len(boxes) != 9:
        issues.append('exactly nine morning boxes required')
        boxes = []
    for number, (key, box) in enumerate(zip(BOX_KEYS, boxes), 1):
        if not isinstance(box, dict):
            issues.append(f'{key}: invalid box object')
            continue
        if box.get('number') != number or isinstance(box.get('number'), bool) or box.get('key') != key:
            issues.append(f'{key}: box number or identity mismatch')
        body = box.get('body')
        issues.extend(_body_issues(key, body, today, evidence))
        if not isinstance(body, str) or box.get('sha256') != body_sha256(body):
            issues.append(f'{key}: body checksum mismatch')
        try:
            checked = _aware(box.get('checkedAtKst'), f'{key} check')
            if checked.date() != today or not timedelta(0) <= now - checked <= MAX_AGE:
                issues.append(f'{key}: check is future, stale or not today')
        except ValueError as exc:
            issues.append(str(exc))
    try:
        if snapshot.get('snapshotSha256') != snapshot_sha256(snapshot):
            issues.append('snapshot checksum mismatch')
    except (ValueError, TypeError, OverflowError):
        issues.append('snapshot is not canonical JSON')
    return issues


def validate_snapshot(snapshot, now):
    """Return nine report bodies on success; raise ValueError on any problem."""
    issues = snapshot_issues(snapshot, now)
    if issues:
        raise ValueError('; '.join(issues))
    return [box['body'] for box in snapshot['boxes']]


def build_snapshot(bodies, now, *, evidence, checked_at=None):
    """Construct and immediately revalidate a complete morning snapshot."""
    now = _aware(now, 'now')
    if not isinstance(bodies, list) or len(bodies) != 9:
        raise ValueError('exactly nine report bodies required')
    if not isinstance(evidence, dict) or checked_at is not None and not isinstance(checked_at, dict):
        raise ValueError('source evidence and checked_at must be objects')
    checks = checked_at or {}
    boxes = []
    for number, (key, body) in enumerate(zip(BOX_KEYS, bodies), 1):
        if not isinstance(body, str):
            raise ValueError(f'{key}: body must be text')
        boxes.append(dict(number=number, key=key, body=body, sha256=body_sha256(body),
                          checkedAtKst=checks.get(key, now.isoformat())))
    snapshot = dict(schemaVersion=1, deliveryDateKst=now.date().isoformat(),
                    generatedAtKst=now.isoformat(),
                    expiresAtKst=datetime.combine(now.date() + timedelta(days=1), time(), KST).isoformat(),
                    boxes=boxes, evidence=dict(evidence))
    snapshot['snapshotSha256'] = snapshot_sha256(snapshot)
    validate_snapshot(snapshot, now)
    return snapshot
