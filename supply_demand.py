"""Official R-ONE apartment supply-demand indices; never sends messages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time

import requests

KST = timezone(timedelta(hours=9))
BASE = 'https://www.reb.or.kr/r-one/'
CACHE = Path('supply-demand-cache.json')
TABLES = {
    'weekly_sale': ('T248163133074619', 'WK'),
    'weekly_jeonse': ('T245423133086632', 'WK'),
    'monthly_sale': ('A_2024_00076', 'MM'),
    'monthly_jeonse': ('A_2024_00077', 'MM'),
}
REGIONS = ('전국', '수도권', '지방권', '서울', '경기', '인천', '부산', '대구',
           '전남광주', '대전', '울산', '세종', '강원', '충북', '충남', '전북',
           '경북', '경남', '제주')
PENDING = '⚖️ 부동산 주간·월간 수급지수\n\n집계 대기 · 한국부동산원 원자료 확인 후 업데이트됩니다.'
DELAY_NOTICE = '🕒 최근 확보 자료 · 원자료 또는 수집 갱신 지연\n아래 주간 기준일·월간 기준월을 확인해 주세요.'


def month_shift(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def get_json(path, params, session=requests):
    # Never log request URLs or exception text: authenticated URLs contain a key.
    response = session.get(BASE + path, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def api_rows(payload):
    blocks = payload.get('SttsApiTblData', [])
    head = next((b['head'] for b in blocks if 'head' in b), [])
    rows = next((b['row'] for b in blocks if 'row' in b), [])
    total = next((h['list_total_count'] for h in head if 'list_total_count' in h), 0)
    if not rows:
        raise ValueError('R-ONE returned no usable rows')
    return rows, int(total)


def request_window(cycle, today):
    if cycle == 'WK':
        first = (today - timedelta(days=28)).isocalendar()
        last = today.isocalendar()
        return f'{first.year}{first.week:02}', f'{last.year}{last.week:02}'
    return month_shift(today, -3).strftime('%Y%m'), month_shift(today, -1).strftime('%Y%m')


def fetch_snapshot(now, key=None, session=requests):
    key = os.environ.get('RONE_KEY', '') if key is None else key

    def metadata(pair):
        name, (table, cycle) = pair
        data = get_json('portal/openapi/selectOpenApiItmCd.do', {'statblId': table}, session)['data']
        regions = {r['itmNm']: r['itmId'] for r in data if r['itmTag'] == '분류'}
        items = [r['itmId'] for r in data if r['itmTag'] == '항목']
        if len(items) != 1 or not set(REGIONS) <= set(regions):
            raise ValueError('R-ONE table classification changed')
        return name, (regions, items[0])

    def query(name, region=None):
        table, cycle = TABLES[name]
        codes, item = metadata_by_name[name]
        start, end = request_window(cycle, now.date())
        params = {'Type': 'json', 'STATBL_ID': table, 'DTACYCLE_CD': cycle,
                  'ITM_ID': str(item), 'START_WRTTIME': start, 'END_WRTTIME': end,
                  'pIndex': 1, 'pSize': 1000}
        if key:
            params['KEY'] = key
        if region:
            params['CLS_ID'] = str(codes[region])
        rows, total = api_rows(get_json('openapi/SttsApiTblData.do', params, session))
        if key and total != len(rows):
            raise ValueError('R-ONE response truncated')
        if not key and (not region or total > 5 or total != len(rows)):
            raise ValueError('Public sample window is incomplete')
        grouped = {r: [] for r in ([region] if region else REGIONS)}
        for row in rows:
            label = row.get('CLS_NM')
            if label not in grouped:
                continue
            if (str(row.get('CLS_ID')) != str(codes[label])
                    or str(row.get('ITM_ID')) != str(item)
                    or row.get('STATBL_ID') != table or row.get('DTACYCLE_CD') != cycle):
                raise ValueError('R-ONE series identity mismatch')
            grouped[label].append({'period': row['WRTTIME_DESC'], 'value': row['DTA_VAL']})
        for values in grouped.values():
            values.sort(key=lambda r: r['period'])
            # Monthly descriptions are not lexically chronological (e.g. 9 vs 10).
            if cycle == 'MM':
                for row in values:
                    year, month = row['period'].replace('년', '').replace('월', '').split()
                    row['period'] = f'{int(year):04}-{int(month):02}'
                values.sort(key=lambda r: r['period'])
        return name, grouped

    with ThreadPoolExecutor(max_workers=4) as pool:
        metadata_by_name = dict(pool.map(metadata, TABLES.items()))
        jobs = [(name, None) for name in TABLES] if key else [
            (name, region) for name in TABLES for region in REGIONS]
        series = {name: {} for name in TABLES}
        for name, grouped in pool.map(lambda job: query(*job), jobs):
            series[name].update(grouped)
    snapshot = {'schemaVersion': 1, 'provider': '한국부동산원 R-ONE',
                'housingType': '아파트', 'checkedAtKst': now.isoformat(),
                'accessMode': 'authenticated' if key else 'public_filtered_samples',
                'tableIds': {name: spec[0] for name, spec in TABLES.items()}, 'series': series}
    if not valid_snapshot(snapshot, now):
        raise ValueError('R-ONE data failed completeness/date validation')
    return snapshot


def valid_snapshot(snapshot, now):
    try:
        if (snapshot['schemaVersion'] != 1 or snapshot['provider'] != '한국부동산원 R-ONE'
                or snapshot['housingType'] != '아파트'
                or snapshot['tableIds'] != {name: spec[0] for name, spec in TABLES.items()}
                or set(snapshot['series']) != set(TABLES)):
            return False
        stamp = datetime.fromisoformat(snapshot['checkedAtKst'])
        if stamp.tzinfo is None or stamp > now + timedelta(minutes=5):
            return False
        for name, entries in snapshot['series'].items():
            if set(entries) != set(REGIONS):
                return False
            periods_by_region = []
            for values in entries.values():
                if len(values) < 2 or any(isinstance(r['value'], bool) or not isinstance(r['value'], (int, float))
                                          or not math.isfinite(r['value']) or not 0 <= r['value'] <= 200 for r in values):
                    return False
                periods = [r['period'] for r in values]
                if periods != sorted(set(periods)):
                    return False
                parsed = [date.fromisoformat(p if name.startswith('weekly') else p + '-01') for p in periods]
                if any(p > stamp.date() or p > now.date() for p in parsed):
                    return False
                if name.startswith('weekly'):
                    if any(p.weekday() != 0 for p in parsed) or parsed[-1] - parsed[-2] != timedelta(days=7):
                        return False
                elif parsed[-1] >= month_shift(stamp.date(), 0) or parsed[-1] != month_shift(parsed[-2], 1):
                    return False
                periods_by_region.append(periods)
            if any(p != periods_by_region[0] for p in periods_by_region):
                return False
        for prefix in ('weekly', 'monthly'):
            if [r['period'] for r in snapshot['series'][prefix + '_sale']['전국']] != [
                    r['period'] for r in snapshot['series'][prefix + '_jeonse']['전국']]:
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError, IndexError):
        return False


def source_period(snapshot, prefix):
    return snapshot['series'][prefix + '_sale']['전국'][-1]['period']


def freshness_issues(snapshot, now):
    if not valid_snapshot(snapshot, now):
        return ['수급지수 캐시 형식·지역·비교기간 검증 실패']
    issues = []
    if now - datetime.fromisoformat(snapshot['checkedAtKst']) > timedelta(days=2):
        issues.append('수급 원자료를 2일 넘게 재확인하지 못했습니다')
    if (now.date() - date.fromisoformat(source_period(snapshot, 'weekly'))).days > 14:
        issues.append('주간 수급 원자료가 14일보다 오래됐습니다')
    if date.fromisoformat(source_period(snapshot, 'monthly') + '-01') < month_shift(now.date(), -2):
        issues.append('월간 수급 원자료가 최근 2개 완료 월 범위를 벗어났습니다')
    return issues


def delta_text(delta):
    if delta == 0:
        return '변동 없음'
    if abs(delta) < 0.005:
        return '0.01p 미만 ' + ('상승' if delta > 0 else '하락')
    return f'{delta:+.2f}p'


def value_line(snapshot, series, region):
    previous, current = snapshot['series'][series][region][-2:]
    label = '지방' if region == '지방권' else region
    return f"{label} {current['value']:.2f} ({delta_text(current['value'] - previous['value'])})"


def format_digest(snapshot, now):
    weekly = source_period(snapshot, 'weekly')
    monthly = source_period(snapshot, 'monthly').split('-')
    sale = snapshot['series']['weekly_sale']['전국'][-1]['value']
    jeonse = snapshot['series']['weekly_jeonse']['전국'][-1]['value']
    lines = ['⚖️ 부동산 주간·월간 수급지수', '아파트 · 한국부동산원', '']
    if freshness_issues(snapshot, now):
        lines += [DELAY_NOTICE, '']
    lines += [f'📅 주간 기준일: {weekly}', f'🗓️ 월간 기준월: {monthly[0]}년 {int(monthly[1])}월', '',
              f'💡 한눈에: 전국 매매 {sale:.2f} · 전세 {jeonse:.2f}',
              '100 초과는 수요 우세 · 100 미만은 공급 우세 · 100은 균형입니다.', '',
              '🏠 주간 매매수급지수', '괄호는 전주 대비 변화 · 단위: 포인트(p)', '']
    lines += [value_line(snapshot, 'weekly_sale', region) for region in REGIONS]
    lines += ['', '🔑 주간 전세수급지수', '괄호는 전주 대비 변화 · 단위: 포인트(p)', '']
    lines += [value_line(snapshot, 'weekly_jeonse', region) for region in REGIONS]
    lines += ['', '📈 최근 4회 전국 흐름']
    for key, label in [('weekly_sale', '매매'), ('weekly_jeonse', '전세')]:
        values = snapshot['series'][key]['전국'][-4:]
        lines.append(label + '  ' + ' → '.join(f"{r['period'][5:]} {r['value']:.2f}" for r in values))
    lines += ['', '🗓️ 월간 주요 지역', '괄호는 전월 대비 변화 · 단위: 포인트(p)', '']
    for region in ('전국', '서울', '경기', '인천'):
        sale_line = value_line(snapshot, 'monthly_sale', region)
        jeonse_line = value_line(snapshot, 'monthly_jeonse', region).split(' ', 1)[1]
        lines += [sale_line.split(' ', 1)[0], '매매 ' + sale_line.split(' ', 1)[1] + ' · 전세 ' + jeonse_line, '']
    lines += ['📖 읽는 법', '지수 범위: 0~200 · 기준: 100',
              '100 초과: 수요 우세', '100 미만: 공급 우세', '100: 수요·공급 균형',
              '증감 단위: 포인트(p)', '',
              '출처: 한국부동산원 R-ONE · 전국주택가격동향조사']
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
        print('수급지수: 최근 2시간 내 원자료 확인 완료, 저장 자료 유지')
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
            print(f"수급지수 확인 완료: 주간 {source_period(new, 'weekly')} / 월간 {source_period(new, 'monthly')} · 19개 지역")
            return not freshness_issues(new, now)
        except (requests.RequestException, ValueError, KeyError, TypeError, OSError):
            print(f'수급지수 조회·검증 실패 ({attempt + 1}/2), 이전 검증 자료·기준일 보존')
            if attempt == 0:
                time.sleep(2)
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    raise SystemExit(0 if collect(force=args.force) else 1)
