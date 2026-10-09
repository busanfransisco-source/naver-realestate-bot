"""Archive two real Seoul snapshots; publish yesterday only. Never send messages."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
ARCHIVE = Path(__file__).with_name('seoul-time-snapshots.json')
SLOTS = ((12, '🕛 전날 정오 기준'), (18, '🌆 전날 오후 6시 기준'))


def read_archive(path=ARCHIVE):
    try:
        days = json.loads(Path(path).read_text(encoding='utf-8'))['days']
        return days if isinstance(days, dict) else {}
    except (OSError, ValueError, KeyError):
        return {}


def valid_snapshot(snapshot, day, hour):
    try:
        target = datetime.fromisoformat(day).replace(hour=hour, tzinfo=KST)
        source_min = datetime.fromisoformat(snapshot['sourceMinKst'])
        source_max = datetime.fromisoformat(snapshot['sourceMaxKst'])
        captured = datetime.fromisoformat(snapshot['collectedAtKst'])
        return (target-timedelta(minutes=30) <= source_min <= source_max <= target
                and target <= captured <= target+timedelta(minutes=20)
                and snapshot['placeCount'] >= 62 and snapshot['placeCount'] <= 82
                and isinstance(snapshot['body'], str) and '집계 대기' not in snapshot['body']
                and f'원자료 시각: {day} {source_min:%H:%M}~{source_max:%H:%M} (KST)' in snapshot['body'])
    except (KeyError, TypeError, ValueError):
        return False


def render_previous_day(now, days):
    day = (now.astimezone(KST).date()-timedelta(days=1)).isoformat()
    lines = ['📍 서울 주요 상권', f'기준일: {day} (전날 · KST)']
    complete = True
    for hour, title in SLOTS:
        lines.extend(['', title, ''])
        snapshot = days.get(day, {}).get(str(hour))
        if not valid_snapshot(snapshot, day, hour):
            complete = False
            lines.append('해당 시간대 보관 자료 없음 · 미수집')
        else:
            lines.append(snapshot['body'])
    lines.extend(['', '읽는 법: 최근 4주 같은 요일·시간대 대비 신한카드 내국인 소비 상태입니다.',
                  '', '출처: 서울 열린데이터광장·신한카드'])
    if not complete:
        lines.extend(['', '자동공유 비활성 · 두 시간대 자료 확보 후 공유 가능합니다.'])
    return '\n'.join(lines)


def capture_slot(now, days, fetch_rows):
    """A late run cannot masquerade as noon. Only <=target source clocks qualify."""
    now = now.astimezone(KST)
    hour = next((h for h, _ in SLOTS if now.hour == h and now.minute <= 20), None)
    if hour is None:
        return False
    day = now.date().isoformat()
    if valid_snapshot(days.get(day, {}).get(str(hour)), day, hour):
        return False
    from daily_data_card_sources import build_seoul_commerce_digest
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    rows = [row for row in fetch_rows()
            if target.replace(tzinfo=None)-timedelta(minutes=30)
            <= row['observed_at_kst'] <= target.replace(tzinfo=None)]
    body = build_seoul_commerce_digest(rows, now_kst=target.replace(tzinfo=None))
    # Remove live-time interpretation and duplicate explanation from each block.
    body = body[body.index('📊 한눈에 보는 상권 분위기'):]
    body = body.split('💡 이렇게 읽으세요')[0].rstrip()
    body = re.sub(r'전체 82곳 중 .*?제외했습니다\.',
                  f'전체 82곳 중 {len(rows)}곳 반영 · 기준 시간대 자료가 없거나 수집되지 않은 {82-len(rows)}곳 제외', body)
    low = min(row['observed_at_kst'] for row in rows)
    high = max(row['observed_at_kst'] for row in rows)
    body = f'원자료 시각: {day} {low:%H:%M}~{high:%H:%M} (KST)\n\n'+body
    snapshot = {'sourceMinKst': low.replace(tzinfo=KST).isoformat(),
                'sourceMaxKst': high.replace(tzinfo=KST).isoformat(),
                'collectedAtKst': now.isoformat(), 'placeCount': len(rows), 'body': body}
    if not valid_snapshot(snapshot, day, hour):
        raise ValueError('Invalid Seoul time-slot snapshot')
    days.setdefault(day, {})[str(hour)] = snapshot
    return True


def main():
    import requests
    from local_api_secrets import load_secret
    from daily_data_card_sources import fetch_seoul_commerce_rows, SourceUnavailable
    from production_data_cards import CACHE, card_metadata
    now = datetime.now(KST)
    days = read_archive()
    try:
        changed = capture_slot(now, days, lambda: fetch_seoul_commerce_rows(requests, load_secret('seoul')))
    except (SourceUnavailable, requests.RequestException, ValueError):
        changed = False
        print('Seoul target-time source unavailable; no later-time substitution')
    if changed:
        ARCHIVE.write_text(json.dumps({'schemaVersion': 1, 'days': days}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    data = json.loads(CACHE.read_text(encoding='utf-8'))
    entry = card_metadata('seoulcommerce', render_previous_day(now, days))
    entry.update(refreshStatus='previous_day_two_slots', checkedAtKst=now.isoformat())
    data['cards']['seoulcommerce'] = entry
    data['generatedAtKst'] = now.isoformat()
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Seoul previous-day display ready:', entry['ready'], '| captured target slot:', changed)


if __name__ == '__main__':
    main()
