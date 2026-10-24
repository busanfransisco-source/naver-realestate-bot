"""Recover missing box 19 in the current publishing run; never send messages."""
import re
import time
import argparse
from datetime import datetime
from pathlib import Path

from apt_today_closings_fetch import (
    KST, WEEKDAY_EN, WEEKDAY_KR_SHORT, SourceBlocked, build_digest, fetch_page_html,
    parse_today_summary, summary_date,
)


def complete_today(text, today):
    title = f'{today.month}/{today.day}({WEEKDAY_KR_SHORT[today.weekday()]}) 신규 등록 실거래가'
    return (text.startswith(title+'\n')
            and re.search(r'^전국 [\d,]+건 \(🔥[\d,]+\)', text, re.M) is not None
            and '분양권/입주권 ' in text
            and not any(marker in text for marker in ('수집 중', '집계 대기', '기준점 저장', '수집 실패')))


def validate_summary(summary, today):
    if summary_date(summary) != today:
        raise ValueError('upstream source is not today; no relabelling')
    keys = ('totalCount', 'allTimeHighCount', 'preconstructedSaleCount',
            'oneHundredMillionClubAllTimeHighCount', 'oneHundredMillionClubCount')
    for key in keys:
        if type(summary.get(key)) is not int or summary[key] < 0:
            raise ValueError('upstream count missing or invalid: '+key)
    total, high = summary['totalCount'], summary['allTimeHighCount']
    if (high > total or summary['preconstructedSaleCount'] > total
            or summary['oneHundredMillionClubCount'] > total
            or summary['oneHundredMillionClubAllTimeHighCount'] > high):
        raise ValueError('upstream component count exceeds national total')
    regions = summary.get('sidoStats')
    if not isinstance(regions, list):
        raise ValueError('regional counts missing')
    for row in regions:
        if any(type(row.get(key)) is not int or row[key] < 0 for key in ('count', 'allTimeHighCount')):
            raise ValueError('invalid regional count')
        if row['allTimeHighCount'] > row['count']:
            raise ValueError('regional record highs exceed regional total')
    if sum(row['count'] for row in regions) != total or sum(row['allTimeHighCount'] for row in regions) != high:
        raise ValueError('regional and national totals disagree')
    highs = summary.get('allTimeHighTransactions') or []
    if len(highs) != high:
        raise ValueError('full record-high list is incomplete')


def check_today(directory=Path('.'), today=None):
    today = today or datetime.now(KST).date()
    try:
        text = (Path(directory)/f'transactions-{today.isoformat()}.txt').read_text(encoding='utf-8')
    except OSError:
        return False
    return complete_today(text, today)


def recover(today, directory=Path('.'), fetch=fetch_page_html, sleeper=time.sleep):
    directory = Path(directory)
    dated = directory / f'transactions-{today.isoformat()}.txt'
    try:
        content = dated.read_text(encoding='utf-8')
    except OSError:
        content = ''
    if complete_today(content, today):
        print('Transactions already complete for', today, '; no duplicate collection')
        return True
    for attempt in range(2):
        try:
            summary = parse_today_summary(fetch())
            validate_summary(summary, today)
            source_day, content = build_digest(summary)
            if source_day != today or not complete_today(content, today):
                raise ValueError('generated source is incomplete')
            for filename in ('transactions.txt', f'transactions-{WEEKDAY_EN[today.weekday()]}.txt', dated.name):
                (directory / filename).write_text(content, encoding='utf-8')
            print('Recovered today transactions:', today, 'total', summary['totalCount'],
                  'record highs', summary['allTimeHighCount'])
            return True
        except SourceBlocked as error:
            print(f'Transaction source blocked (HTTP {error.status_code}); '
                  'no immediate retry; use the official nationwide recovery workflow')
            return False
        except Exception as error:
            print(f'Transaction recovery attempt {attempt+1}/2 failed: {type(error).__name__}: {error}')
            if attempt == 0:
                sleeper(3)
    print('No fresh verified source; previous files preserved for a later automatic retry')
    return False


def main():
    now = datetime.now(KST)
    # apt.today's new daily batch becomes available at 05:00 KST.
    if now.hour < 5:
        print('Before 05:00 KST source publication; recovery deferred')
        return True
    return recover(now.date())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    raise SystemExit(0 if (check_today() if args.check_only else main()) else 1)
