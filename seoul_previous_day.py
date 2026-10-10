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
        return (target-timedelta(hours=3) <= source_min <= source_max <= target+timedelta(hours=3)
                and source_max-source_min <= timedelta(minutes=30)
                and captured.date() == target.date()
                and captured-timedelta(minutes=30) <= source_min
                and source_max <= captured+timedelta(minutes=5)
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
            target = datetime.fromisoformat(day).replace(hour=hour, tzinfo=KST)
            if not (target-timedelta(minutes=30) <= datetime.fromisoformat(snapshot['sourceMinKst'])
                    <= datetime.fromisoformat(snapshot['sourceMaxKst']) <= target+timedelta(minutes=20)):
                lines.append('🔄 기준시각 자료 누락 · 가장 가까운 시간대의 대체 자료입니다.\n')
            lines.append(snapshot['body'])
    lines.extend(['', '읽는 법: 최근 4주 같은 요일·시간대 대비 신한카드 내국인 소비 상태입니다.',
                  '', '활용: 전날 점심·저녁 시간대에 평소보다 소비가 활발했던 상권과 업종을 함께 살펴보세요.'])
    if not complete:
        lines.extend(['', '자동공유 비활성 · 두 시간대 자료 확보 후 공유 가능합니다.'])
    return '\n'.join(lines)


def snapshot_quality(snapshot):
    low = datetime.fromisoformat(snapshot['sourceMinKst'])
    high = datetime.fromisoformat(snapshot['sourceMaxKst'])
    hour = snapshot.get('targetHour', 12 if high.hour < 15 else 18)
    target = high.replace(hour=hour, minute=0, second=0, microsecond=0)
    distance = max(abs((low-target).total_seconds()), abs((high-target).total_seconds()))
    return (-distance, snapshot['placeCount'], snapshot['sourceMaxKst'])


def active_hour(now):
    if 9 <= now.hour < 15:
        return 12
    if 15 <= now.hour < 21 or now.hour == 21 and now.minute <= 30:
        return 18
    return None


def capture_slot(now, days, fetch_rows):
    """Keep the closest genuine same-day sample, including explicit fallback times."""
    now = now.astimezone(KST)
    hour = active_hour(now)
    if hour is None:
        return False
    day = now.date().isoformat()
    previous = days.get(day, {}).get(str(hour))
    if valid_snapshot(previous, day, hour) and snapshot_quality(previous)[0] == 0:
        return False
    from daily_data_card_sources import build_seoul_commerce_digest
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    rows = [row for row in fetch_rows()
            if target.replace(tzinfo=None)-timedelta(hours=3)
            <= row['observed_at_kst'] <= target.replace(tzinfo=None)+timedelta(hours=3)
            and now.replace(tzinfo=None)-timedelta(minutes=30)
            <= row['observed_at_kst'] <= now.replace(tzinfo=None)+timedelta(minutes=5)]
    body = build_seoul_commerce_digest(rows, now_kst=now.replace(tzinfo=None))
    # Remove live-time interpretation and duplicate explanation from each block.
    body = body[body.index('📊 한눈에 보는 상권 분위기'):]
    body = body.split('💡 이렇게 읽으세요')[0].rstrip()
    body = re.sub(r'전체 82곳 중 .*?제외했습니다\.',
                  f'전체 82곳 중 {len(rows)}곳 반영 · 기준 시간대 자료가 없거나 수집되지 않은 {82-len(rows)}곳 제외', body)
    low = min(row['observed_at_kst'] for row in rows)
    high = max(row['observed_at_kst'] for row in rows)
    body = f'원자료 시각: {day} {low:%H:%M}~{high:%H:%M} (KST)\n\n'+body
    snapshot = {'targetHour': hour, 'sourceMinKst': low.replace(tzinfo=KST).isoformat(),
                'sourceMaxKst': high.replace(tzinfo=KST).isoformat(),
                'collectedAtKst': now.isoformat(), 'placeCount': len(rows), 'body': body}
    if not valid_snapshot(snapshot, day, hour):
        raise ValueError('Invalid Seoul time-slot snapshot')
    if valid_snapshot(previous, day, hour) and snapshot_quality(snapshot) <= snapshot_quality(previous):
        return False
    days.setdefault(day, {})[str(hour)] = snapshot
    return True


def save_archive(days):
    ARCHIVE.write_text(json.dumps({'schemaVersion': 1, 'days': days}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def merge_archive(days, incoming):
    for day, slots in incoming.items():
        for hour, _ in SLOTS:
            item = slots.get(str(hour))
            if not valid_snapshot(item, day, hour):
                continue
            old = days.get(day, {}).get(str(hour))
            if not valid_snapshot(old, day, hour) or snapshot_quality(item) > snapshot_quality(old):
                days.setdefault(day, {})[str(hour)] = item
    return days


def watch_slot(hour, *, clock=None, sleeper=None, fetch_rows=None):
    import time
    import requests
    from daily_data_card_sources import fetch_seoul_commerce_rows, SourceUnavailable
    from local_api_secrets import load_secret
    clock = clock or (lambda: datetime.now(KST))
    sleeper = sleeper or time.sleep
    fetch_rows = fetch_rows or (lambda: fetch_seoul_commerce_rows(requests, load_secret('seoul')))
    started = clock().astimezone(KST)
    target = started.replace(hour=hour, minute=0, second=0, microsecond=0)
    end = target+timedelta(minutes=20)
    days = read_archive()
    print('Seoul collector target:', target.isoformat(), '| runner started:', started.isoformat(), flush=True)
    if started > end:
        if active_hour(started) == hour:
            try:
                if capture_slot(started, days, fetch_rows):
                    save_archive(days)
            except (SourceUnavailable, requests.RequestException, ValueError):
                pass
        return valid_snapshot(days.get(target.date().isoformat(), {}).get(str(hour)), target.date().isoformat(), hour)
    attempt_after = target-timedelta(hours=3)
    while clock() <= end:
        now = clock().astimezone(KST)
        if now >= attempt_after:
            try:
                if capture_slot(now, days, fetch_rows):
                    save_archive(days)
                    print('SAVED:', days[target.date().isoformat()][str(hour)]['sourceMaxKst'], flush=True)
            except (SourceUnavailable, requests.RequestException, ValueError):
                print('Source sample unavailable; retrying within the real target window', flush=True)
            item = days.get(target.date().isoformat(), {}).get(str(hour))
            if valid_snapshot(item, target.date().isoformat(), hour) and datetime.fromisoformat(item['sourceMinKst']) >= target:
                return True
            attempt_after = min(now+timedelta(minutes=3), target) if now < target else now+timedelta(minutes=3)
        sleeper(60)
    return valid_snapshot(days.get(target.date().isoformat(), {}).get(str(hour)), target.date().isoformat(), hour)


def main(publish_only=False):
    import requests
    from local_api_secrets import load_secret
    from daily_data_card_sources import fetch_seoul_commerce_rows, SourceUnavailable
    from production_data_cards import CACHE, card_metadata
    now = datetime.now(KST)
    days = read_archive()
    try:
        changed = False if publish_only else capture_slot(now, days, lambda: fetch_seoul_commerce_rows(requests, load_secret('seoul')))
    except (SourceUnavailable, requests.RequestException, ValueError):
        changed = False
        print('Seoul target-time source unavailable; no later-time substitution')
    if changed:
        save_archive(days)
    data = json.loads(CACHE.read_text(encoding='utf-8'))
    entry = card_metadata('seoulcommerce', render_previous_day(now, days))
    entry.update(refreshStatus='previous_day_two_slots', checkedAtKst=now.isoformat())
    data['cards']['seoulcommerce'] = entry
    data['generatedAtKst'] = now.isoformat()
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Seoul previous-day display ready:', entry['ready'], '| captured target slot:', changed)
    target_hour = active_hour(now)
    return publish_only or target_hour is None or valid_snapshot(days.get(now.date().isoformat(), {}).get(str(target_hour)), now.date().isoformat(), target_hour)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch-hour', type=int, choices=(12, 18))
    parser.add_argument('--merge')
    parser.add_argument('--publish-only', action='store_true')
    args = parser.parse_args()
    if args.merge:
        save_archive(merge_archive(read_archive(), read_archive(args.merge)))
    success = watch_slot(args.watch_hour) if args.watch_hour else main(publish_only=args.publish_only)
    if not success:
        raise SystemExit('Seoul target slot missing; no substitute source was saved')
