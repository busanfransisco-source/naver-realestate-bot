"""Read-only proof that public boxes 13..18 contain the dated original packet."""
import argparse
import json
from datetime import datetime, date
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
    parser.add_argument('--all-local', action='store_true', help='Validate every prepared dated packet without network')
    parser.add_argument('--url', default='https://busanfransisco-source.github.io/naver-realestate-bot/briefing.html')
    args = parser.parse_args()
    if args.all_local:
        paths = sorted(CONTENT_DIR.glob('*.json'))
        for path in paths:
            validate_packet(json.loads(path.read_text(encoding='utf-8')), date.fromisoformat(path.stem))
        print(f'PASS: {len(paths)} dated packets / {len(paths)*6} original manuscripts')
        raise SystemExit(0)
    today = datetime.now(KST).date()
    response = requests.get(args.url, params={'originals': today.isoformat()}, timeout=20)
    response.raise_for_status()
    response.encoding = 'utf-8'
    verify(response.text, today)
    print('PASS: public boxes 13..18 match six verified originals for '+today.isoformat())
