"""Transactions must match today's completed source even before noon."""
import time
from datetime import datetime
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from gen_briefing import KST, WEEKDAY_KR_SHORT, has_fetch_failure

def verify_body(text, today):
    title = f'{today.month}/{today.day}({WEEKDAY_KR_SHORT[today.weekday()]}) 신규 등록 실거래가'
    return text.startswith(title) and '전국 ' in text and '수집 중' not in text and not has_fetch_failure(text)

def main():
    today = datetime.now(KST).date()
    local = Path(f'transactions-{today.isoformat()}.txt').read_text(encoding='utf-8').strip()
    if not verify_body(local, today):
        raise SystemExit('Today transaction source is missing or incomplete')
    for attempt in range(12):
        try:
            response = requests.get('https://busanfransisco-source.github.io/naver-realestate-bot/briefing.html', params={'transactions_verify': time.time_ns()}, timeout=20)
            response.raise_for_status()
            node = BeautifulSoup(response.text, 'html.parser').find('textarea', id='ta-transactions')
            if node and node.get_text().strip() == local:
                print('PASS: public box 19 exactly matches today completed source')
                return
        except requests.RequestException:
            pass
        if attempt < 11:
            time.sleep(10)
    raise SystemExit('Public box 19 does not match today collected source')

if __name__ == '__main__':
    main()
