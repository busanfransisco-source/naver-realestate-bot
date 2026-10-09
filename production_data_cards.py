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
    previous_day = re.search(r'기준일: (\d{4}-\d{2}-\d{2}) \(전날 · KST\)', body) if key == 'seoulcommerce' else None
    if previous_day:
        day = datetime.fromisoformat(previous_day[1]).replace(tzinfo=KST)
        result.update(sourceDate=previous_day[1], sourceWindow=previous_day[1]+' 12:00 / 18:00',
                      expiresAtKst=(day+timedelta(days=2)).isoformat(),
                      ready='미수집' not in body and '자동공유 비활성' not in body
                      and '🕛 전날 정오 기준' in body and '🌆 전날 오후 6시 기준' in body)
        return result
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
            if '기준일:' in entry['body'] and '(전날 · KST)' in entry['body']:
                return source_day == now.astimezone(KST).date()-timedelta(days=1)
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


def daily_seoul_snapshot(entry, now):
    """A verified first snapshot stays fixed and distributable on its KST date."""
    if isinstance(entry, dict) and '(전날 · KST)' in entry.get('body', ''):
        return valid_card('seoulcommerce', entry, now)
    return (stored_seoul_snapshot(entry, now)
            and entry.get('sourceDate') == now.astimezone(KST).date().isoformat())


def load_contents(path=CACHE, *, now=None):
    now = now or datetime.now(KST)
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        cards = data.get('cards', {})
    except (OSError, ValueError, AttributeError):
        cards = {}
    if not isinstance(cards, dict):
        cards = {}
    contents = {key: cards[key]['body'] if (valid_card(key, cards.get(key), now)
            or key == 'seoulcommerce' and stored_seoul_snapshot(cards.get(key), now))
            else pending_body(key, (cards.get(key) if isinstance(cards.get(key), dict) else {}).get('failureReason')
                              or '자료가 없거나 원자료 유효시간이 지났습니다') for key in KEYS}
    from seoul_previous_day import ARCHIVE, read_archive, render_previous_day
    if Path(path).resolve() == CACHE.resolve() and ARCHIVE.exists():
        contents['seoulcommerce'] = render_previous_day(now, read_archive())
    return contents


def collect(path=CACHE, *, only=None):
    # Lazy import avoids the preview renderer's dependency on gen_briefing.
    from preview_daily_data_cards import preview_contents
    diagnostics = {}
    selected = tuple(only) if only is not None else KEYS
    if not selected or set(selected) - set(KEYS):
        raise ValueError('Unknown data card selection')
    now = datetime.now(KST)
    try:
        previous = json.loads(Path(path).read_text(encoding='utf-8')).get('cards', {})
    except (OSError, ValueError, AttributeError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    frozen = 'seoulcommerce' in selected and daily_seoul_snapshot(previous.get('seoulcommerce'), now)
    requested = tuple(key for key in selected if not (key == 'seoulcommerce' and frozen))
    bodies = preview_contents(diagnostics=diagnostics, only=requested) if requested else {}
    now = datetime.now(KST)
    if frozen and not daily_seoul_snapshot(previous.get('seoulcommerce'), now):
        raise RuntimeError('수집 중 날짜 변경: 당일 고정본 재확인이 필요합니다')
    entries = {key: card_metadata(key, bodies[key]) if key in selected else
               (previous[key] if isinstance(previous.get(key), dict) else card_metadata(key, pending_body(key)))
               for key in KEYS if not (key == 'seoulcommerce' and frozen)}
    if frozen:
        entries['seoulcommerce'] = dict(previous['seoulcommerce'])
        entries['seoulcommerce'].update(ready=True, refreshStatus='fixed_daily_snapshot', failureReason=None)
    # Other APIs can take time after Seoul's call. Recheck at collection completion.
    for key, entry in entries.items():
        if key not in selected:
            continue
        if key == 'seoulcommerce' and frozen:
            continue
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
    print('Refresh status:', ', '.join(f"{key}={data['cards'][key].get('refreshStatus', 'unchanged') if key in selected else 'unchanged'}" for key in KEYS))
    return data


def refresh_succeeded(data, selected, now=None):
    now = now or datetime.now(KST)
    return all((key == 'seoulcommerce'
                and data['cards'][key].get('refreshStatus') == 'fixed_daily_snapshot'
                and daily_seoul_snapshot(data['cards'][key], now))
               or (data['cards'][key].get('refreshStatus') == 'collected'
                   and valid_card(key, data['cards'][key], now)) for key in selected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--card', choices=KEYS)
    parser.add_argument('--require-fresh', action='store_true')
    args = parser.parse_args()
    if args.collect:
        selected = (args.card,) if args.card else KEYS
        seoul_ok = True
        if 'seoulcommerce' in selected:
            from seoul_previous_day import main as update_seoul
            seoul_ok = update_seoul()
            selected = tuple(key for key in selected if key != 'seoulcommerce')
        result = collect(only=selected) if selected else json.loads(CACHE.read_text(encoding='utf-8'))
        if args.require_fresh and (not seoul_ok or not refresh_succeeded(result, selected)):
            raise SystemExit('Requested source refresh failed; retained data is not a new successful refresh.')
