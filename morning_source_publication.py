"""Website-only morning source publication; never a sender-ready snapshot.

The nine-box sender contract remains fail-closed. This separate artifact lets
independently verified source bodies reach the website when another box fails.
"""
import argparse
from datetime import datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import time as clock

from bs4 import BeautifulSoup
import requests

from morning_briefing_contract import (
    BOX_KEYS, KST, MAX_AGE, _aware, _body_issues, body_sha256,
)

KIND = 'morning-website-sources'
OUTPUT = 'morning-website-sources.json'
BASE = 'https://busanfransisco-source.github.io/naver-realestate-bot/'
EVIDENCE_KEYS = ('trendCheckedAtKst', 'booksPeriodStart', 'booksPeriodEnd')


def publication_sha256(value):
    signed = {key: entry for key, entry in value.items() if key != 'publicationSha256'}
    raw = json.dumps(signed, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def source_issues(key, body, evidence, now):
    """Validate daily bodies strictly; retain only genuinely fresh weekly books."""
    now = _aware(now, 'now')
    issues = _body_issues(key, body, now.date(), evidence)
    if key == 'books':
        from yes24_books import digest_info, valid_period
        info = digest_info(body) if isinstance(body, str) else None
        valid_weekly = bool(info and info[0] <= now.date()
                            and valid_period(info[1], info[2], now.date()))
        if valid_weekly:
            # The header stays at its real collection date. The sales period
            # remains the source clock; revalidation does not mean recollection.
            issues = [issue for issue in issues if issue != 'books: report date is not today']
        else:
            issues.append('books: verified weekly source missing or stale')
    if key == 'trend':
        try:
            stamp = _aware(evidence.get('trendCheckedAtKst'), 'trend source check')
            if not timedelta(0) <= now-stamp <= timedelta(days=8):
                issues.append('trend: weekly source check stale or future')
        except ValueError:
            issues.append('trend: weekly source check missing')
    return issues


def _source_mode(key, body, now):
    if key == 'books':
        from yes24_books import digest_info
        info = digest_info(body)
        if info and info[0] < now.date():
            return 'retained_weekly'
    return 'validated_current'


def website_body_issues(key, body, now, evidence):
    """Collector-facing argument order; no collection or file writes."""
    return source_issues(key, body, evidence, now)


def build_publication(bodies, now, *, evidence, eligible_keys=None):
    """Select independently valid, approved boxes without changing any body."""
    now = _aware(now, 'now')
    if not isinstance(bodies, list) or len(bodies) != len(BOX_KEYS) or not isinstance(evidence, dict):
        raise ValueError('nine source slots and source evidence required')
    selected = set(BOX_KEYS if eligible_keys is None else eligible_keys)
    if selected - set(BOX_KEYS):
        raise ValueError('unknown morning source key')
    safe_evidence = {key: evidence[key] for key in EVIDENCE_KEYS if key in evidence}
    boxes = []
    for number, (key, body) in enumerate(zip(BOX_KEYS, bodies), 1):
        if key not in selected or source_issues(key, body, safe_evidence, now):
            continue
        boxes.append(dict(number=number, key=key, body=body,
                          sha256=body_sha256(body), checkedAtKst=now.isoformat(),
                          sourceMode=_source_mode(key, body, now)))
    artifact = dict(schemaVersion=1, kind=KIND, deliveryDateKst=now.date().isoformat(),
                    generatedAtKst=now.isoformat(),
                    expiresAtKst=datetime.combine(now.date()+timedelta(days=1), time(), KST).isoformat(),
                    boxes=boxes, evidence=safe_evidence)
    artifact['publicationSha256'] = publication_sha256(artifact)
    validate_publication(artifact, now)
    return artifact


def validate_publication(artifact, now):
    """Reject corruption, unknown keys, stale data and unsafe source metadata."""
    now = _aware(now, 'now')
    if (not isinstance(artifact, dict) or type(artifact.get('schemaVersion')) is not int
            or artifact.get('schemaVersion') != 1 or artifact.get('kind') != KIND
            or artifact.get('deliveryDateKst') != now.date().isoformat()):
        raise ValueError('invalid website-only morning artifact identity or date')
    generated = _aware(artifact.get('generatedAtKst'), 'generation')
    expiry = _aware(artifact.get('expiresAtKst'), 'expiry')
    midnight = datetime.combine(now.date()+timedelta(days=1), time(), KST)
    if (generated.date() != now.date() or not timedelta(0) <= now-generated <= MAX_AGE
            or expiry != midnight or expiry <= now):
        raise ValueError('website-only morning artifact clock invalid')
    evidence = artifact.get('evidence')
    if not isinstance(evidence, dict) or set(evidence)-set(EVIDENCE_KEYS):
        raise ValueError('website source evidence invalid')
    boxes = artifact.get('boxes')
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= len(BOX_KEYS):
        raise ValueError('one to nine independently validated source boxes required')
    numbers = []
    for box in boxes:
        if not isinstance(box, dict):
            raise ValueError('invalid source box')
        key = box.get('key')
        number = box.get('number')
        if key not in BOX_KEYS or type(number) is not int or number != BOX_KEYS.index(key)+1:
            raise ValueError('source box identity or number invalid')
        numbers.append(number)
        body = box.get('body')
        if (source_issues(key, body, evidence, now)
                or box.get('sha256') != body_sha256(body)
                or box.get('sourceMode') != _source_mode(key, body, now)):
            raise ValueError('source body, checksum or weekly mode invalid')
        checked = _aware(box.get('checkedAtKst'), 'source check')
        if checked.date() != now.date() or not timedelta(0) <= now-checked <= MAX_AGE:
            raise ValueError('source check stale or future')
    if numbers != sorted(set(numbers)):
        raise ValueError('source boxes duplicated or out of order')
    if artifact.get('publicationSha256') != publication_sha256(artifact):
        raise ValueError('website source artifact checksum mismatch')
    return boxes


def apply_publication(publication_path, trend_path=None, *, root='.', now=None):
    """Apply approved source filenames only; do not touch the sender snapshot."""
    now = _aware(now or datetime.now(KST), 'now')
    root = Path(root)
    artifact = json.loads(Path(publication_path).read_text(encoding='utf-8'))
    boxes = validate_publication(artifact, now)
    payloads = {}
    if any(box['key'] == 'trend' for box in boxes):
        from neonet_trend import format_digest
        if trend_path is None:
            raise ValueError('weekly source cache required for trend publication')
        trend = json.loads(Path(trend_path).read_text(encoding='utf-8'))
        body = next(box['body'] for box in boxes if box['key'] == 'trend')
        if (trend.get('checkedAtKst') != artifact['evidence'].get('trendCheckedAtKst')
                or format_digest(trend).strip() != body.strip()):
            raise ValueError('weekly body and actual source cache differ')
        payloads['neonet-trend-cache.json'] = json.dumps(trend, ensure_ascii=False, indent=2)+'\n'
    target = root/OUTPUT
    if target.is_file():
        try:
            old = json.loads(target.read_text(encoding='utf-8'))
            validate_publication(old, now)
            if _aware(old['generatedAtKst'], 'old generation') >= _aware(artifact['generatedAtKst'], 'generation'):
                return False
        except (OSError, ValueError, KeyError, TypeError):
            pass
    weekday = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[now.weekday()]
    for box in boxes:
        key, body = box['key'], box['body']
        for name in (f'{key}.txt', f'{key}-{weekday}.txt'):
            payloads[name] = body
        if key in ('fortune', 'weather', 'realestate'):
            payloads[f'{key}-{now.date().isoformat()}.txt'] = body
    payloads[OUTPUT] = json.dumps(artifact, ensure_ascii=False, indent=2)+'\n'
    # Validate the complete artifact and weekly cache before touching any source.
    for name, content in payloads.items():
        temporary = root/(name+'.morning-web-tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(root/name)
    return True


def verify_publication_page(artifact, html, now):
    """Check each published source's textarea, displayed number and copy body."""
    boxes = validate_publication(artifact, now)
    soup = BeautifulSoup(html, 'html.parser')
    for box in boxes:
        key, body, number = box['key'], box['body'], box['number']
        nodes = soup.select(f'textarea#ta-{key}')
        if len(nodes) != 1 or nodes[0].get_text().strip() != body.strip():
            raise ValueError('website source textarea mismatch')
        section = nodes[0].find_parent('section', class_='card')
        if not section or str(section.get('data-slot')) != str(number):
            raise ValueError('website source slot mismatch')
        button = section.select_one('button.copy-btn')
        if not button or f"copySection('{key}'," not in button.get('onclick', ''):
            raise ValueError('website source copy target mismatch')
        prefix = f'window.__content_{key} = '
        script = next((node.get_text() for node in soup.select('script')
                       if node.get_text().startswith(prefix)), None)
        if script is None or json.loads(script[len(prefix):].rstrip(';')) != body:
            raise ValueError('website source copy body mismatch')
    return artifact['publicationSha256']


def verify_publication(expected, *, get=requests.get, now_fn=None,
                       timeout=120, sleep=clock.sleep):
    """Wait boundedly for the public source artifact and its actual copy bodies."""
    if not 0 <= timeout <= 120:
        raise ValueError('public verification timeout outside bounded range')
    now_fn = now_fn or (lambda: datetime.now(KST))
    deadline = clock.monotonic()+timeout
    while True:
        try:
            now = now_fn()
            expected_boxes = validate_publication(expected, now)
            params = {'morningSourceVerify': clock.time_ns()}
            responses = [get(BASE+name, params=params, timeout=12,
                             headers={'Cache-Control': 'no-cache'})
                         for name in (OUTPUT, 'briefing.html')]
            for response in responses:
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError('unexpected public response size')
                response.encoding = 'utf-8'
            actual = responses[0].json()
            actual_boxes = validate_publication(actual, now)
            if (_aware(actual['generatedAtKst'], 'public generation')
                    < _aware(expected['generatedAtKst'], 'expected generation')):
                raise ValueError('public website sources older than expected')
            if not {box['key'] for box in expected_boxes}.issubset({box['key'] for box in actual_boxes}):
                raise ValueError('public website sources lack expected boxes')
            return verify_publication_page(actual, responses[1].text, now)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            if clock.monotonic() >= deadline:
                raise ValueError('Public morning website source verification did not complete before deadline') from None
            sleep(min(10, max(0, deadline-clock.monotonic())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publication', required=True)
    parser.add_argument('--trend-cache')
    parser.add_argument('--verify', action='store_true', help='Read and verify public deployment only')
    args = parser.parse_args()
    if args.verify:
        expected = json.loads(Path(args.publication).read_text(encoding='utf-8'))
        print('Published morning website sources and copy bodies MATCH:', verify_publication(expected))
    else:
        changed = apply_publication(args.publication, args.trend_cache)
        print('Validated morning website sources applied' if changed else 'Newer website sources already published')
