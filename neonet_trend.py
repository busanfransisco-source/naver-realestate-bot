"""Box 5: published Neonet weekly rates, never recomputed rounded prices."""
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = 'https://www.neonet.co.kr/novo-rebank/view/market_price/RegionMarketPrice.neo'
CACHE = Path('neonet-trend-cache.json')
KST = timezone(timedelta(hours=9))
REGIONS = ('서울특별시', '신도시', '경기도', '인천광역시', '부산광역시',
           '대구광역시', '전남광주통합특별시', '대전광역시', '울산광역시',
           '세종특별자치시', '경상남도', '경상북도', '전북도', '충청남도',
           '충청북도', '강원도', '제주특별자치도')
LABELS = dict(zip(REGIONS, ('서울', '신도시', '경기', '인천', '부산', '대구',
    '전남광주통합특별시', '대전', '울산', '세종', '경남', '경북', '전북',
    '충남', '충북', '강원', '제주')))


def rate(text):
    text = text.strip()
    if text == '-':
        return None  # Retain the source dash, do not invent a precise zero.
    match = re.fullmatch(r'(\d+(?:\.\d+)?)%\s*(상승|하락)\s*\(([▲▼])\)', text)
    if not match or (match[2] == '상승') != (match[3] == '▲'):
        raise ValueError('부동산뱅크 변동률 형식 또는 방향 불일치')
    value = Decimal(match[1])
    if value > 100:
        raise ValueError('부동산뱅크 변동률 범위 오류')
    return str(value if match[2] == '상승' else -value)


def parse_page(page):
    soup = BeautifulSoup(page, 'html.parser')
    candidates = [table for table in soup.find_all('table')
                  if '전주 대비 매매가격 변동률' in table.get_text(' ', strip=True)
                  and '전주 대비 전세가격 변동률' in table.get_text(' ', strip=True)]
    if len(candidates) != 1:
        raise ValueError('부동산뱅크 전국 주간 변동률 표가 없거나 중복됩니다')
    rows = []
    for tr in candidates[0].find_all('tr'):
        cells = [td.get_text(' ', strip=True) for td in tr.find_all('td')]
        if len(cells) == 3 and cells[0] in REGIONS:
            rows.append({'region': cells[0], 'sale': rate(cells[1]), 'jeonse': rate(cells[2])})
    if len(rows) != len(REGIONS) or {row['region'] for row in rows} != set(REGIONS):
        raise ValueError('부동산뱅크 지역 누락 또는 중복')
    summary = soup.select_one('.dl_box')
    text = summary.get_text(' ', strip=True) if summary else ''
    if not text.startswith('전국') or not re.search(r'전국\s+아파트', text):
        raise ValueError('부동산뱅크 전국 아파트 요약 범위 불일치')
    nation = {}
    for kind, label in (('sale', '매매'), ('jeonse', '전세')):
        match = re.search(r'3\.3㎡당\s*' + label +
                          r'가격\s*([\d,]+)만\s*원\s*\(전주대비\s*(\d+(?:\.\d+)?)%\s*(상승|하락)\)', text)
        if not match:
            raise ValueError('부동산뱅크 전국 요약 값 누락')
        nation[kind] = rate(match[2] + '% ' + match[3] + (' (▲)' if match[3] == '상승' else ' (▼)'))
        nation[kind + 'Price'] = int(match[1].replace(',', ''))
    return {'national': nation, 'regions': rows}


def display(value):
    return '변동 없음' if value is None or Decimal(value) == 0 else f'{Decimal(value):+.2f}%'


def format_digest(snapshot):
    checked = datetime.fromisoformat(snapshot['checkedAtKst'])
    data = snapshot['data']
    national = data['national']
    lines = ['📈 부동산 주간 시세동향', '전국 아파트 · 전주 대비', '',
             '🏠 전국 시세', '',
             f"매매가 {display(national['sale'])}",
             f"전세가 {display(national['jeonse'])}", '',
             f"3.3㎡당 매매가 {national['salePrice']:,}만원",
             f"3.3㎡당 전세가 {national['jeonsePrice']:,}만원"]
    for key, heading in (('sale', '🏘️ 지역별 매매가 변동률'), ('jeonse', '🔑 지역별 전세가 변동률')):
        lines.extend(['', heading, ''])
        lines.extend(f"{LABELS[row['region']]}  {display(row[key])}" for row in data['regions'])
    return '\n'.join(lines)


def load_digest(path=CACHE):
    try:
        saved = json.loads(Path(path).read_text(encoding='utf-8'))
        if saved.get('sourceUrl') != URL or saved.get('schemaVersion') != 1:
            raise ValueError('출처 오류')
        if [row['region'] for row in saved['data']['regions']] != list(REGIONS):
            raise ValueError('지역 오류')
        return format_digest(saved)
    except (OSError, ValueError, KeyError, TypeError):
        return '📈 부동산 주간 시세동향\n\n집계 대기 · 부동산뱅크 주간 통계 확인 후 업데이트됩니다.'


def fetch_snapshot(session=requests):
    for attempt in range(2):
        try:
            response = session.get(URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
            response.raise_for_status()
            response.encoding = 'euc-kr'
            return parse_page(response.text)
        except (requests.RequestException, ValueError):
            if attempt == 1:
                raise
            import time
            time.sleep(3)


def publish(content, now):
    weekday = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[now.weekday()]
    for name in ('trend.txt', f'trend-{weekday}.txt'):
        Path(name).write_text(content + '\n', encoding='utf-8')


def collect(*, now=None, path=CACHE, session=requests):
    now = now or datetime.now(KST)
    try:
        data = fetch_snapshot(session)
        snapshot = {'schemaVersion': 1, 'sourceUrl': URL,
                    'checkedAtKst': now.isoformat(), 'data': data}
        content = format_digest(snapshot)
        Path(path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('부동산뱅크 전국 및 17개 지역 주간 변동률 확인 완료')
    except (requests.RequestException, ValueError):
        content = load_digest(path)
        print('부동산뱅크 수집 실패: 이전 검증 자료와 원래 조회시각 유지')
    publish(content, now)
    return content


if __name__ == '__main__':
    import sys
    if '--check' in sys.argv:
        import time
        observations = []
        for attempt in range(2):
            response = requests.get(URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
            response.raise_for_status()
            response.encoding = 'euc-kr'
            data = parse_page(response.text)
            observations.append(data)
            print(f"Live check {attempt + 1}: 17 regions, nationwide sale={data['national']['sale']}, jeonse={data['national']['jeonse']}")
            if attempt == 0:
                time.sleep(3)
        print('Repeated snapshots match:', observations[0] == observations[1])
    elif '--render' in sys.argv:
        publish(load_digest(), datetime.now(KST))
    else:
        collect()
