"""Dated KOSPI quote from NAVER's current index endpoints, without credentials."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re

KST = timezone(timedelta(hours=9))
PRIMARY_URL = 'https://m.stock.naver.com/api/index/KOSPI/basic'
FALLBACK_URL = 'https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI'
UNAVAILABLE = '시세 확인 대기 (제공처 값·기준시각 미확인)'


@dataclass(frozen=True)
class KospiQuote:
    value: Decimal
    source_at: datetime
    market_status: str


def source_clock_is_current(stamp, now, status):
    stamp, now = stamp.astimezone(KST), now.astimezone(KST)
    age = now - stamp
    if stamp.weekday() >= 5 or not timedelta(0) <= age <= timedelta(days=7):
        return False
    return status == 'CLOSE' or (stamp.date() == now.date() and age <= timedelta(minutes=30))


def parse_quote(payload, now):
    if now.tzinfo is None or not isinstance(payload, dict):
        raise ValueError('aware clock and quote object required')
    if 'datas' in payload:
        records = payload['datas']
        matches = [row for row in records if isinstance(row, dict) and row.get('itemCode') == 'KOSPI'] if isinstance(records, list) else []
        if len(matches) != 1:
            raise ValueError('one KOSPI quote required')
        payload = matches[0]
    if payload.get('itemCode') != 'KOSPI':
        raise ValueError('wrong index')
    value = payload.get('closePriceRaw', payload.get('closePrice'))
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError('missing index value')
    text = str(value).strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?', text):
        raise ValueError('invalid index value')
    try:
        value = Decimal(text.replace(',', ''))
    except InvalidOperation as exc:
        raise ValueError('invalid index value') from exc
    if not value.is_finite() or value <= 0:
        raise ValueError('index must be positive and finite')
    try:
        stamp = datetime.fromisoformat(payload['localTradedAt'])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError('missing source clock') from exc
    if stamp.tzinfo is None:
        raise ValueError('source clock needs timezone')
    stamp = stamp.astimezone(KST)
    exchange = payload.get('stockExchangeType', payload.get('exchange', {}))
    if not isinstance(exchange, dict) or exchange.get('zoneId') != 'Asia/Seoul':
        raise ValueError('wrong exchange timezone')
    status = payload.get('marketStatus')
    if status not in ('OPEN', 'CLOSE'):
        raise ValueError('unknown market state')
    if not source_clock_is_current(stamp, now, status):
        raise ValueError('source clock stale, future or on a weekend')
    return KospiQuote(value, stamp, status)


def fetch_quote(getter, now):
    """Two bounded endpoint attempts; never use response time as quote time."""
    for url in (PRIMARY_URL, FALLBACK_URL):
        try:
            return parse_quote(getter(url, timeout=8).json(), now)
        except (ValueError, TypeError, KeyError, OSError):
            continue
    return None


def format_quote(quote, now):
    if quote is None:
        return UNAVAILABLE
    stamp = quote.source_at.astimezone(KST)
    state = '종가' if quote.market_status == 'CLOSE' else '장중'
    weekend = ' · 주말 휴장' if now.astimezone(KST).weekday() >= 5 and quote.market_status == 'CLOSE' else ''
    # NAVER's timestamp may be later than the closing auction. Label it honestly.
    return f'{quote.value:,.2f}pt ({stamp:%Y-%m-%d} {state} · 네이버 표시 {stamp:%H:%M} KST{weekend})'


def indicator_issues(body, now=None):
    rows = re.findall(r'^\s*- 코스피 : (.*)$', body, re.M)
    if len(rows) != 1:
        return ['exactly one KOSPI indicator required']
    if rows[0] == UNAVAILABLE:
        return []  # The unavailable state is explicit; do not hide the other news.
    match = re.fullmatch(r'((?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2})pt \((\d{4}-\d{2}-\d{2}) (종가|장중) · 네이버 표시 (\d{2}:\d{2}) KST( · 주말 휴장)?\)', rows[0])
    if not match:
        return ['KOSPI value must include source date and provider time']
    try:
        value = Decimal(match[1].replace(',', ''))
        stamp = datetime.fromisoformat(f'{match[2]}T{match[4]}:00+09:00')
        now = now or datetime.now(KST)
        if now.tzinfo is None or not value.is_finite() or value <= 0:
            raise ValueError('invalid quote value or clock')
        status = 'CLOSE' if match[3] == '종가' else 'OPEN'
        if not source_clock_is_current(stamp, now, status):
            raise ValueError('quote clock stale, future or on a weekend')
        if match[5] and (status != 'CLOSE' or now.astimezone(KST).weekday() < 5):
            raise ValueError('incorrect weekend status')
    except (ValueError, InvalidOperation):
        return ['KOSPI value or source clock is invalid, stale or future']
    return []
