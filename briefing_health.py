"""Per-slot content gates, bounded recovery and public-page verification.

Recovery never authors policy text, changes dates, or sends Kakao messages.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from gen_briefing import KST, analysis_date, has_fetch_failure

KEYS = ('fortune weather shortnews subs trend fuelfx metalcoin books realestate world finance ai '
        'daily19 daily20 daily21 daily22 daily23 daily24 transactions seoulcommerce cryptofear '
        'wikiinterest analysis3 analysis4 analysis5 analysis2 analysis6 analysis1 analysis7').split()
REPAIR = {
    'fortune': 'fortune_fetch.py', 'weather': 'weather_fetch.py',
    'shortnews': 'daum_news_fetch.py', 'subs': 'aptinfo_fetch.py',
    'trend': 'aptinfo_fetch.py', 'fuelfx': 'market_fetch.py',
    'metalcoin': 'market_fetch.py', 'books': 'market_fetch.py',
    'realestate': 'naver_realestate_fetch.py', 'world': 'world_news_fetch.py',
    'finance': 'finance_news_fetch.py', 'ai': 'ai_news_fetch.py',
}


def content_date(key, text, today):
    match = re.search(r'(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일', text[:200])
    if match:
        year, month, day = map(int, match.groups())
        return datetime(year + 2000 if year < 100 else year, month, day).date()
    if key == 'fortune':
        match = re.search(r'(\d{1,2})월\s*(\d{1,2})일', text[:70])
        if match:
            return datetime(today.year, *map(int, match.groups())).date()
    if key == 'transactions':
        match = re.match(r'(\d{1,2})/(\d{1,2})\(', text)
        if match:
            return datetime(today.year, *map(int, match.groups())).date()
    return analysis_date(text)


def inspect(page, now=None):
    now = now or datetime.now(KST)
    today = now.date()
    soup = BeautifulSoup(page, 'html.parser')
    results = []
    for slot, key in enumerate(KEYS, 1):
        nodes = soup.select(f'#ta-{key}')
        text = nodes[0].get_text().strip() if len(nodes) == 1 else ''
        issues = []
        card = nodes[0].find_parent('section') if nodes else None
        if not card or str(card.get('data-slot')) != str(slot):
            issues.append('missing/duplicate/wrong slot')
        if len(text) < 80 or has_fetch_failure(text) or any(x in text for x in ('집계 대기', '수집 중입니다', '준비되지 않았습니다')):
            issues.append('missing or incomplete body')
        # Morning collection is allowed to be pending until its intended deadline.
        due = 8
        if key.startswith('analysis'):
            due = 8
        elif key == 'transactions':
            due = 7
        elif key == 'seoulcommerce':
            due = 8
        elif key == 'cryptofear':
            due = 10
        elif key == 'wikiinterest':
            due = 11
        if key in ('seoulcommerce', 'cryptofear', 'wikiinterest'):
            from production_data_cards import card_metadata
            meta = card_metadata(key, text)
            try:
                source = datetime.fromisoformat(meta['sourceDate']).date()
                age = (today - source).days
                previous_seoul = key == 'seoulcommerce' and '(전날 · KST)' in text
                allowed = 3 if key == 'wikiinterest' else 1 if key == 'cryptofear' or previous_seoul else 0
                if age < 0 or age > allowed or previous_seoul and (age != 1 or not meta['ready']):
                    issues.append('source date outside allowed window')
            except (TypeError, ValueError):
                issues.append('missing source clock')
        elif key == 'trend':
            # Weekly values may be unchanged; cache check age, not today's label.
            try:
                cache = json.loads(Path('neonet-trend-cache.json').read_text(encoding='utf-8'))
                stamp = cache.get('checkedAtKst') or cache.get('checked_at_kst')
                if not stamp or now - datetime.fromisoformat(stamp) > timedelta(days=8):
                    issues.append('weekly source not checked within 8 days')
            except (OSError, ValueError, TypeError):
                issues.append('missing weekly source clock')
        else:
            try:
                if content_date(key, text, today) != today:
                    issues.append('not today material')
            except ValueError:
                issues.append('invalid date')
        required = {
            'fuelfx': ('휘발유', '경유', '미국 달러', '일본 엔'),
            'metalcoin': ('국제 금', '국내 금', '국제 은', '비트코인'),
            'analysis7': ('한 줄 판정:', '원문 기사:', '1차 근거:'),
        }.get(key, ())
        for token in required:
            if token not in text or re.search(re.escape(token) + r'[^\n]*(?:확인 불가|수집 실패)', text):
                issues.append(f'missing required item: {token}')
        if key in ('books',) and len(re.findall(r'^\d+\.', text, re.M)) < 10:
            issues.append('top 10 incomplete')
        if key == 'metalcoin' and len(re.findall(r'^\S+ [\d,]+(?:\.\d+)?원', text.split('🪙')[-1], re.M)) < 10:
            issues.append('coin top 10 incomplete')
        if key in ('realestate', 'world', 'finance', 'ai') and text.count('https://') < 2:
            issues.append('news links incomplete')
        results.append(dict(slot=slot, key=key, status=('failed' if now.hour >= due else 'pending') if issues else 'ok',
                            issues=issues, sha256=hashlib.sha256(text.encode()).hexdigest()))
    if len(soup.select('section.card')) != 29:
        results[0]['status'] = 'failed'
        results[0]['issues'].append('page must contain exactly 29 cards')
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repair', action='store_true')
    parser.add_argument('--url')
    parser.add_argument('--report', default='briefing-health.json')
    args = parser.parse_args()
    local = Path('briefing.html')
    rows = inspect(local.read_text(encoding='utf-8'))
    if args.repair:
        scripts = sorted({REPAIR[r['key']] for r in rows if r['issues'] and r['key'] in REPAIR})
        for script in scripts:
            print(f'Retry source group: {script}', flush=True)
            try:
                subprocess.run([sys.executable, script], timeout=180, check=True)
            except (subprocess.SubprocessError, OSError):
                print(f'Retry failed: {script}', flush=True)
        subprocess.run([sys.executable, 'gen_briefing.py'], check=True)
        rows = inspect(local.read_text(encoding='utf-8'))
    deployed = None
    if args.url:
        # Actual public text must match all 29 local bodies, not just page HTTP 200.
        for attempt in range(8):
            try:
                response = requests.get(args.url, params={'health': time.time_ns()}, timeout=20)
                response.raise_for_status()
                public = inspect(response.text)
                deployed = all(a['sha256'] == b['sha256'] for a, b in zip(rows, public)) and not any('missing/duplicate/wrong slot' in r['issues'] for r in public)
                if deployed:
                    break
            except requests.RequestException:
                deployed = False
            if attempt < 7:
                time.sleep(10)
    report = dict(checkedAtKst=datetime.now(KST).isoformat(), publicMatches=deployed, cards=rows)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in rows:
        print(f"{row['slot']:02} {row['key']}: {row['status']} {'; '.join(row['issues'])}")
    raise SystemExit(any(r['status'] == 'failed' for r in rows) or deployed is False)


if __name__ == '__main__':
    main()
