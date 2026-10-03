"""Collect three public data cards; persist source clocks, never API credentials."""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
KEYS = ('seoulcommerce', 'cryptofear', 'wikiinterest')
CACHE = Path('data-cards.json')


def pending_body(key, reason=None):
    names = {'seoulcommerce': '서울 주요 상권', 'cryptofear': '비트코인 공포·탐욕',
             'wikiinterest': '경제 주제 읽기 관심도'}
    detail = f'\n보류 사유: {reason}' if reason else ''
    return f"{names[key]}\n\n집계 대기 · 최신 원자료 검증 후 업데이트됩니다.{detail}\n자동공유 비활성"


def card_metadata(key, body):
    """Derive expiry from the source clock, never the regeneration clock."""
    result = {'body': body, 'ready': False, 'sourceDate': None,
              'sourceWindow': None, 'expiresAtKst': None}
    if '집계 대기' in body or '자동공유 비활성' in body:
        return result
    if key == 'seoulcommerce':
        day = re.search(r'조회: (\d{4}-\d{2}-\d{2})', body)
        hours = re.search(r'원자료 시각: (\d{2}:\d{2})~(\d{2}:\d{2})', body)
        if not day or not hours:
            return result
        source = datetime.fromisoformat(day[1] + 'T' + hours[1]).replace(tzinfo=KST)
        expiry = source + timedelta(minutes=30)
        result['sourceDate'] = day[1]
        result['sourceWindow'] = day[1] + ' ' + hours[1] + '~' + hours[2]
    else:
        pattern = r'원자료 기준일: (\d{4}-\d{2}-\d{2}) \(UTC\)' if key == 'cryptofear' else r'집계 마감: (\d{4}-\d{2}-\d{2}) \(UTC\)'
        match = re.search(pattern, body)
        if not match:
            return result
        source = datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc)
        # UTC date ages 0..1 for crypto, 1..3 for Wikipedia.
        expiry = source + timedelta(days=2 if key == 'cryptofear' else 4)
        result['sourceDate'] = match[1]
        result['sourceWindow'] = match[1]
    result.update(ready=True, expiresAtKst=expiry.astimezone(KST).isoformat())
    return result


def valid_card(key, entry, now):
    if not isinstance(entry, dict) or entry.get('ready') is not True:
        return False
    try:
        derived = card_metadata(key, entry['body'])
        if not derived['ready'] or any(entry.get(field) != derived[field]
                                     for field in ('sourceDate', 'sourceWindow', 'expiresAtKst')):
            return False
        expiry = datetime.fromisoformat(entry['expiresAtKst'])
        if expiry.tzinfo is None or not now < expiry:
            return False
        source_day = datetime.fromisoformat(entry['sourceDate']).date()
        if key == 'seoulcommerce':
            source = expiry - timedelta(minutes=30)
            return source_day == now.astimezone(KST).date() and source <= now + timedelta(minutes=5)
        age = (now.astimezone(timezone.utc).date() - source_day).days
        return 0 <= age <= 1 if key == 'cryptofear' else 1 <= age <= 3
    except (KeyError, TypeError, ValueError):
        return False


def stored_seoul_snapshot(entry, now):
    """A dated last-good snapshot can remain visible, but is not send-ready."""
    if not isinstance(entry, dict):
        return False
    try:
        derived = card_metadata('seoulcommerce', entry['body'])
        return (derived['ready'] and all(entry.get(field) == derived[field]
                for field in ('sourceDate', 'sourceWindow', 'expiresAtKst'))
                and datetime.fromisoformat(derived['expiresAtKst']) - timedelta(minutes=30)
                <= now + timedelta(minutes=5))
    except (KeyError, TypeError, ValueError):
        return False


def load_contents(path=CACHE, *, now=None):
    now = now or datetime.now(KST)
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        cards = data.get('cards', {})
    except (OSError, ValueError, AttributeError):
        cards = {}
    if not isinstance(cards, dict):
        cards = {}
    return {key: cards[key]['body'] if (valid_card(key, cards.get(key), now)
            or key == 'seoulcommerce' and stored_seoul_snapshot(cards.get(key), now))
            else pending_body(key, (cards.get(key) if isinstance(cards.get(key), dict) else {}).get('failureReason')
                              or '자료가 없거나 원자료 유효시간이 지났습니다') for key in KEYS}


def collect(path=CACHE):
    # Lazy import avoids the preview renderer's dependency on gen_briefing.
    from preview_daily_data_cards import preview_contents
    diagnostics = {}
    bodies = preview_contents(diagnostics=diagnostics)
    now = datetime.now(KST)
    try:
        previous = json.loads(Path(path).read_text(encoding='utf-8')).get('cards', {})
    except (OSError, ValueError, AttributeError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    entries = {key: card_metadata(key, bodies[key]) for key in KEYS}
    # Other APIs can take time after Seoul's call. Recheck at collection completion.
    for key, entry in entries.items():
        reason = diagnostics.get(key)
        if not valid_card(key, entry, now):
            reason = reason or '원자료 기준일·시각 검증 실패 또는 유효시간 만료'
            if valid_card(key, previous.get(key), now):
                entries[key] = entry = dict(previous[key])
                entry.update(refreshStatus='retained_valid_source', checkedAtKst=now.isoformat(), failureReason=reason)
            elif key == 'seoulcommerce' and stored_seoul_snapshot(previous.get(key), now):
                entries[key] = entry = dict(previous[key])
                entry.update(ready=False, refreshStatus='retained_expired_source',
                             checkedAtKst=now.isoformat(), failureReason=reason)
            else:
                entry.update(ready=False, body=pending_body(key, reason), refreshStatus='pending',
                             checkedAtKst=now.isoformat(), failureReason=reason)
        else:
            entry.update(refreshStatus='collected', collectedAtKst=now.isoformat(),
                         checkedAtKst=now.isoformat(), failureReason=None)
    data = {'schemaVersion': 1, 'generatedAtKst': now.isoformat(),
            'powerExcluded': True,
            'cards': entries}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Source checks:', ', '.join(f"{key}={data['cards'][key]['ready']}" for key in KEYS))
    print('Refresh status:', ', '.join(f"{key}={data['cards'][key]['refreshStatus']}" for key in KEYS))
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    if args.collect:
        collect()
