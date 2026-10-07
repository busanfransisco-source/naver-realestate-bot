"""Read-only proof that public boxes 13..18 contain the dated original packet."""
import argparse
import json
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from gen_briefing import KST
from daily_rotation import CONTENT_DIR, build_rotating_sections, validate_packet

def verify(page, today):
    packet = json.loads((CONTENT_DIR / (today.isoformat()+'.json')).read_text(encoding='utf-8'))
    validate_packet(packet, today)
    soup = BeautifulSoup(page, 'html.parser')
    for number, (key, label, expected) in enumerate(build_rotating_sections(today), 13):
        matches = soup.select('#ta-'+key)
        if len(matches) != 1 or matches[0].get_text() != expected:
            raise ValueError(f'Box {number}: public original manuscript mismatch')
        if matches[0].find_parent('section').get('data-slot') != str(number):
            raise ValueError(f'Box {number}: slot mismatch')
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://busanfransisco-source.github.io/naver-realestate-bot/briefing.html')
    args = parser.parse_args()
    today = datetime.now(KST).date()
    response = requests.get(args.url, params={'originals': today.isoformat()}, timeout=20)
    response.raise_for_status()
    response.encoding = 'utf-8'
    verify(response.text, today)
    print('PASS: public boxes 13..18 match six verified originals for '+today.isoformat())
