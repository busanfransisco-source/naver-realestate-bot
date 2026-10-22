"""KB Datahub market survey indices. Read-only public source; never sends messages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import time

import requests

KST = timezone(timedelta(hours=9))
BASE = 'https://data-api.kbland.kr/bfmstat/weekMnthlyHuseTrnd/maktTrnd'
CACHE = Path('supply-demand-cache.json')
TABLES = {
    'weekly_jeonse': ('weekRentSupInx', '02', '03', '전세수급지수', ('공급충분', '공급적절', '공급부족')),
    'monthly_jeonse': ('monthRentSupInx', '01', '03', '전세수급지수', ('공급충분', '공급적절', '공급부족')),
}
REGION_CODES = {
    '전국': '0000000000', '수도권': '1T0000', '기타지방': '4A0000',
    '서울': '1100000000', '경기': '4100000000', '인천': '2800000000',
    '부산': '2600000000', '대구': '2700000000', '광주': '1200000000',
    '대전': '3000000000', '울산': '3100000000', '세종': '3600000000',
    '강원': '5100000000', '충북': '4300000000', '충남': '4400000000',
    '전북': '5200000000', '경북': '4700000000', '경남': '4800000000', '제주': '5000000000',
}
REGIONS = tuple(REGION_CODES)
REGION_EMOJI = {
    '전국': '🇰🇷', '수도권': '🏘️', '기타지방': '🗺️',
    '서울': '🏙️', '경기': '🏘️', '인천': '🌉', '부산': '🌊',
    '대구': '🍎', '광주': '🎨', '대전': '🔬', '울산': '🏭', '세종': '🏢',
    '강원': '🏔️', '충북': '⛰️', '충남': '🌅', '전북': '🍚',
    '경북': '🏛️', '경남': '⚓', '제주': '🍊',
}
PENDING = '🔑 KB부동산 전세수급지수\n\n집계 대기 · KB 원자료 확인 후 업데이트됩니다.'
DELAY_NOTICE = '🕒 최근 확보 자료 · 원자료 또는 수집 갱신 지연\n아래 주간 기준일·월간 기준월을 확인해 주세요.'


def month_shift(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def number_valid(value, maximum):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and 0 <= value <= maximum)


def period_from_source(value, weekly):
    if not isinstance(value, str) or len(value) != (8 if weekly else 6) or not value.isdigit():
        raise ValueError('KB source period format changed')
    parsed = datetime.strptime(value, '%Y%m%d' if weekly else '%Y%m').date()
    return parsed.isoformat() if weekly else parsed.strftime('%Y-%m')


def parse_series(payload, name):
    """Validate KB's actual index against its three survey response shares."""
    if str(payload.get('dataHeader', {}).get('resultCode')) != '10000':
        raise ValueError('KB source rejected request')
    data = payload['dataBody']['data']
    weekly = name.startswith('weekly')
    periods = [period_from_source(p, weekly) for p in data['날짜리스트']]
    if len(periods) < (4 if weekly else 2) or periods != sorted(set(periods)):
        raise ValueError('KB source dates missing or duplicated')
    raw_regions = {}
    for region in data['데이터리스트']:
        label = region['지역명']
        if label not in REGION_CODES:
            continue
        if label in raw_regions or str(region['지역코드']) != REGION_CODES[label]:
            raise ValueError('KB region name/code mismatch')
        raw_regions[label] = region['dataList']
    if set(raw_regions) != set(REGIONS):
        raise ValueError('KB region coverage incomplete')
    _, _, _, value_column, component_columns = TABLES[name]
    series = {}
    for region, rows in raw_regions.items():
        row_periods = [period_from_source(r['기준날짜'], weekly) for r in rows]
        if row_periods != periods:
            raise ValueError('KB region/date coverage mismatch')
        keep = 4 if weekly else 2
        series[region] = [dict(period=p, value=r[value_column],
                               components=[r[column] for column in component_columns])
                          for p, r in zip(row_periods[-keep:], rows[-keep:])]
    update = period_from_source(data['업데이트일자'], True)
    if (update != periods[-1] if weekly else update[:7] != periods[-1]):
        raise ValueError('KB update clock differs from latest source period')
    return series, update


def fetch_snapshot(now, session=requests):
    def query(name):
        _, cycle, menu, _, _ = TABLES[name]
        response = session.get(BASE, params={'월간주간구분코드': cycle, '메뉴코드': menu, '기간': '2'},
                               headers={'osType': 'HUB', 'Referer': 'https://data.kbland.kr/'}, timeout=25)
        response.raise_for_status()
        return name, parse_series(response.json(), name)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(query, TABLES))
    snapshot = {'schemaVersion': 2, 'providerId': 'kb', 'provider': 'KB부동산',
                'housingType': '중개업소 시장동향 설문', 'checkedAtKst': now.isoformat(),
                'accessMode': 'public_kb_datahub', 'tableIds': {k: v[0] for k, v in TABLES.items()},
                'regionCodes': REGION_CODES, 'sourceUpdates': {k: v[1] for k, v in results.items()},
                'series': {k: v[0] for k, v in results.items()}}
    if not valid_snapshot(snapshot, now):
        raise ValueError('KB snapshot failed identity/period/formula validation')
    return snapshot


def valid_snapshot(snapshot, now):
    try:
        if (snapshot['schemaVersion'] != 2 or snapshot['providerId'] != 'kb'
                or snapshot['provider'] != 'KB부동산' or snapshot['housingType'] != '중개업소 시장동향 설문'
                or snapshot['accessMode'] != 'public_kb_datahub'
                or any(snapshot['tableIds'].get(name) != spec[0] for name, spec in TABLES.items())
                or snapshot['regionCodes'] != REGION_CODES
                or not set(TABLES).issubset(snapshot['sourceUpdates'])
                or not set(TABLES).issubset(snapshot['series'])
                or any(set(snapshot[field]) - (set(TABLES) | {'weekly_sale', 'monthly_sale'})
                       for field in ('tableIds', 'sourceUpdates', 'series'))):
            return False
        stamp = datetime.fromisoformat(snapshot['checkedAtKst'])
        if stamp.tzinfo is None or stamp > now + timedelta(minutes=5):
            return False
        # Read legacy four-series caches, but never depend on buying data.
        for name in TABLES:
            entries = snapshot['series'][name]
            if set(entries) != set(REGIONS):
                return False
            periods_by_region = []
            update = date.fromisoformat(snapshot['sourceUpdates'][name])
            if update > stamp.date() or update > now.date():
                return False
            for values in entries.values():
                if not 2 <= len(values) <= 4:
                    return False
                for row in values:
                    components = row['components']
                    if (not number_valid(row['value'], 200) or not isinstance(components, list)
                            or len(components) != 3 or any(not number_valid(c, 100) for c in components)
                            or abs(sum(components) - 100) > 0.001
                            or abs(row['value'] - (100 + components[2] - components[0])) > 0.001):
                        return False
                periods = [r['period'] for r in values]
                if periods != sorted(set(periods)):
                    return False
                parsed = [date.fromisoformat(p if name.startswith('weekly') else p + '-01') for p in periods]
                if any(p > stamp.date() or p > now.date() for p in parsed):
                    return False
                if name.startswith('weekly'):
                    gaps = [(b-a).days for a, b in zip(parsed, parsed[1:])]
                    if (any(p.weekday() != 0 for p in parsed) or any(g not in (7, 14) for g in gaps)
                            or update.isoformat() != periods[-1]):
                        return False
                elif (any(month_shift(a, 1) != b for a, b in zip(parsed, parsed[1:]))
                      or parsed[-1] > month_shift(stamp.date(), 0)
                      or update.strftime('%Y-%m') != periods[-1]):
                    return False
                periods_by_region.append(periods)
            if any(p != periods_by_region[0] for p in periods_by_region):
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, IndexError):
        return False


def source_period(snapshot, prefix):
    return snapshot['series'][prefix + '_jeonse']['전국'][-1]['period']


def freshness_issues(snapshot, now):
    if not valid_snapshot(snapshot, now):
        return ['KB 수급지수 공급자·지역·기간·산식 검증 실패']
    issues = []
    if now - datetime.fromisoformat(snapshot['checkedAtKst']) > timedelta(days=2):
        issues.append('KB 원자료를 2일 넘게 재확인하지 못했습니다')
    if (now.date() - date.fromisoformat(source_period(snapshot, 'weekly'))).days > 14:
        issues.append('주간 원자료가 14일보다 오래됐습니다')
    if date.fromisoformat(source_period(snapshot, 'monthly') + '-01') < month_shift(now.date(), -2):
        issues.append('월간 원자료가 최근 2개 완료 월 범위를 벗어났습니다')
    return issues


def delta_text(delta):
    if delta == 0:
        return '변동 없음'
    if abs(delta) < 0.005:
        return '0.01p 미만 ' + ('상승' if delta > 0 else '하락')
    return f'{delta:+.2f}p'


def value_line(snapshot, series, region):
    previous, current = snapshot['series'][series][region][-2:]
    return f"{REGION_EMOJI[region]} {region} {current['value']:.2f} ({delta_text(current['value'] - previous['value'])})"


def format_digest(snapshot, now):
    weekly = source_period(snapshot, 'weekly')
    monthly = source_period(snapshot, 'monthly').split('-')
    previous_week = snapshot['series']['weekly_jeonse']['전국'][-2]['period']
    weekly_compare = ('전주 대비' if date.fromisoformat(weekly)-date.fromisoformat(previous_week) == timedelta(days=7)
                      else f'직전 발표 기준일 {previous_week} 대비')
    jeonse = snapshot['series']['weekly_jeonse']['전국'][-1]['value']
    lines = ['🔑 KB부동산 전세수급지수', '공인중개사무소 시장동향 설문', '']
    if freshness_issues(snapshot, now):
        lines += [DELAY_NOTICE, '']
    lines += [f'📅 주간 기준일: {weekly}', f'🗓️ 월간 기준월: {monthly[0]}년 {int(monthly[1])}월', '',
              f'💡 전국 주간 전세수급지수: {jeonse:.2f}', '']
    for name, title in [('weekly_jeonse', '🔑 주간 전세수급지수'),
                        ('monthly_jeonse', '🗓️ 월간 전세수급지수')]:
        compare = weekly_compare if name.startswith('weekly') else '전월 대비'
        lines += [title, f'괄호는 {compare} · 단위: 포인트(p)', '']
        lines += [value_line(snapshot, name, region) for region in REGIONS]
        lines += ['']
    lines += ['📈 최근 4회 전국 주간 흐름']
    for key, label in [('weekly_jeonse', '전세수급')]:
        values = snapshot['series'][key]['전국'][-4:]
        lines.append(label + '  ' + ' → '.join(f"{r['period'][5:]} {r['value']:.2f}" for r in values))
    lines += ['', '📖 읽는 법', '지수 범위: 0~200 · 기준: 100',
              '전세수급 100 초과: 공급부족 · 100 미만: 공급충분',
              '100: 공급부족·공급충분 응답 비중이 같음', '증감 단위: 포인트(p)', '', '출처: KB부동산 데이터허브']
    return '\n'.join(lines)


def read_snapshot(path=CACHE):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def load_digest(path=CACHE, now=None):
    now = now or datetime.now(KST)
    snapshot = read_snapshot(path)
    return format_digest(snapshot, now) if valid_snapshot(snapshot, now) else PENDING


def collect(path=CACHE, now=None, force=False, fetcher=None):
    now = now or datetime.now(KST)
    old = read_snapshot(path)
    if (not force and not freshness_issues(old, now)
            and now - datetime.fromisoformat(old['checkedAtKst']) < timedelta(hours=2)):
        print('KB 수급지수: 최근 2시간 내 확인 완료, 저장 자료 유지')
        return True
    for attempt in range(2):
        try:
            new = (fetcher or fetch_snapshot)(now)
            if not valid_snapshot(new, now):
                raise ValueError('invalid snapshot')
            if valid_snapshot(old, now) and any(source_period(new, p) < source_period(old, p) for p in ('weekly', 'monthly')):
                raise ValueError('source period regression')
            target = Path(path)
            temporary = target.with_suffix(target.suffix + '.tmp')
            temporary.write_text(json.dumps(new, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(target)
            print(f"KB 수급지수 확인 완료: 주간 {source_period(new, 'weekly')} / 월간 {source_period(new, 'monthly')} · {len(REGIONS)}개 지역")
            return not freshness_issues(new, now)
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
            print(f'KB 수급지수 조회·검증 실패 ({attempt + 1}/2), 이전 자료·기준일 보존')
            if attempt == 0:
                time.sleep(2)
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    raise SystemExit(0 if collect(force=args.force) else 1)
