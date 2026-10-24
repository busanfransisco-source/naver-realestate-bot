"""YES24 domestic weekly ranking; keep collection day and sales week separate."""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

URL = 'https://www.yes24.com/product/category/weekbestseller?categoryNumber=001'
KST = timezone(timedelta(hours=9))
DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
DAYS_KR = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
SOURCE_LABEL = '📚 YES24 국내도서 주간 베스트 TOP 10'
UNAVAILABLE_DIGEST = ('📚 YES24 주간 베스트셀러\n\n'
                      '오늘 또는 어제 수집한 검증 자료를 가져오지 못했습니다.\n'
                      '이번 아침 공유에서 제외합니다.')
PERIOD_RE = re.compile(r'^📅 집계 기간: (\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2})$', re.M)


class SourceMaintenance(ValueError):
    """The official site returned its maintenance notice, not a ranking."""


def _raise_maintenance():
    # Do not echo response URLs, exception details or invented reopening times.
    raise SourceMaintenance('YES24 공식 서비스 점검 중입니다. 기존 주간 집계 기간을 보존합니다.')


def valid_period(start, end, today):
    # Read the selected source week, never infer it from the collection date.
    return (start.weekday() == 0 and end - start == timedelta(days=6)
            and 0 < (today - end).days <= 8)


def parse_ranking(html, today):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    if (not soup.select_one('#divTitle h3') and soup.title
            and '서비스 이용에 대해 안내' in soup.title.get_text()
            and re.search(r'서비스\s*점검\s*중', text)
            and '사이트 중지' in text and '사이트 재오픈' in text
            and re.search(r'\d{4}\.\d{1,2}\.\d{1,2}', text)):
        _raise_maintenance()
    year_node = soup.select_one('#scope_year option[selected]')
    week_node = soup.select_one('#scope_week option[selected]')
    heading = soup.select_one('#divTitle h3')
    category = heading.select_one('.cate') if heading else None
    if (not category or category.get_text(strip=True) != '국내도서'
            or '주별 베스트' not in heading.get_text(' ', strip=True)):
        raise ValueError('YES24 국내도서 종합 주간 목록이 아닙니다.')
    match = re.fullmatch(r'(\d{1,2})월\s*(\d{1,2})일\s*~\s*(\d{1,2})월\s*(\d{1,2})일',
                         week_node.get_text(' ', strip=True) if week_node else '')
    if not year_node or not match:
        raise ValueError('YES24의 선택된 집계 연도/주차를 확인할 수 없습니다.')
    year = int(year_node['value'])
    sm, sd, em, ed = map(int, match.groups())
    # YES24 saleYear identifies the year of the week's ending Sunday.
    start = date(year - (sm > em), sm, sd)
    end = date(year, em, ed)
    if not valid_period(start, end, today):
        raise ValueError('YES24 집계 기간이 최근 완료된 월~일 주차가 아닙니다.')
    books = []
    ids = set()
    rows = soup.select('#yesBestList > li')
    for expected, row in enumerate(rows[:10], 1):
        rank = row.select_one('.img_upper .ico.rank')
        title = row.select_one('a.gd_name')
        goods_id = row.get('data-goods-no')
        if (not rank or rank.get_text(strip=True) != str(expected)
                or not title or not goods_id or goods_id in ids):
            raise ValueError('YES24 TOP 10 순위 또는 상품 식별자가 불완전합니다.')
        name = ' '.join(title.get_text(' ', strip=True).split())
        if not name or '\ufffd' in name or title.get('href') != f'/product/goods/{goods_id}':
            raise ValueError('YES24 도서 제목 또는 상품 링크가 유효하지 않습니다.')
        ids.add(goods_id)
        books.append(name)
    if len(books) != 10:
        raise ValueError(f'YES24 주간 순위가 {len(books)}권만 확인되었습니다.')
    return dict(start=start, end=end, books=books)


def collect(today=None):
    today = today or datetime.now(KST).date()
    response = requests.get(URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    response.raise_for_status()
    response.encoding = 'utf-8'
    final_url = getattr(response, 'url', None)
    if isinstance(final_url, str):
        location = urlparse(final_url)
        if (location.hostname in {'yes24.com', 'www.yes24.com', 'm.yes24.com'}
                and location.path.lower() == '/notice.html'):
            _raise_maintenance()
    return parse_ranking(response.text, today)


def render(ranking, now):
    head = f'{now.year % 100}년 {now.month}월 {now.day}일 {DAYS_KR[now.weekday()]}'
    return '\n'.join([
        f'{head} 주간 베스트셀러', '', SOURCE_LABEL,
        f"📅 집계 기간: {ranking['start'].isoformat()} ~ {ranking['end'].isoformat()}",
        '국내도서 종합 · 온라인·매장 판매 기준', '',
        *[f'{i}. {title}' for i, title in enumerate(ranking['books'], 1)],
        '', '출처: YES24 주간 베스트', '',
    ])


def digest_info(text):
    """Only accept dated YES24 digests, not legacy Aladin or partial lists."""
    head = re.match(r'(\d{2})년 (\d{1,2})월 (\d{1,2})일', text)
    period = PERIOD_RE.search(text)
    ranks = re.findall(r'^(\d+)\.\s+(.+)$', text, re.M)
    if (not head or not period or SOURCE_LABEL not in text
            or [int(n) for n, _ in ranks] != list(range(1, 11))):
        return None
    try:
        year, month, day = map(int, head.groups())
        checked = date(2000 + year, month, day)
        start, end = map(date.fromisoformat, period.groups())
        if not valid_period(start, end, checked):
            return None
        return checked, start, end
    except ValueError:
        return None


def load_digest(directory=Path('.'), today=None):
    """Use a valid week collected today/yesterday, without relabelling its date."""
    today = today or datetime.now(KST).date()
    candidates = []
    for path in [directory / 'books.txt', *[directory / f'books-{d}.txt' for d in DAYS]]:
        try:
            text = path.read_text(encoding='utf-8').strip()
        except FileNotFoundError:
            continue
        info = digest_info(text)
        if (info and 0 <= (today-info[0]).days <= 1
                and valid_period(info[1], info[2], today)):
            # A newer file check must not outrank a newer actual sales week.
            candidates.append((info[2], info[0], text))
    if candidates:
        # Older verified files can still contain the retired footer link.
        return max(candidates, key=lambda item: item[:2])[2].replace('\n' + URL, '').strip()
    return UNAVAILABLE_DIGEST


def refresh(now=None, collector=None, directory=Path('.')):
    now = now or datetime.now(KST)
    try:
        ranking = (collector or collect)(now.date())
        text = render(ranking, now)
        if not digest_info(text):
            raise ValueError('YES24 출력 검증 실패')
    except Exception as exc:
        # No relabelled cached ranking, and never fall back to another bookstore.
        print(f'YES24 수집 실패: {exc} - 기존 파일과 원래 집계 기간을 보존합니다.')
        return False
    for name in ('books.txt', f'books-{DAYS[now.weekday()]}.txt'):
        (directory / name).write_text(text, encoding='utf-8')
    print(f"YES24 주간 베스트 TOP 10 갱신: {ranking['start']} ~ {ranking['end']}")
    return True
