"""Check public deployment and source usability separately; no credentials or sending."""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from production_data_cards import CACHE, KEYS, KST, load_contents, valid_card, daily_seoul_snapshot

BASE = 'https://busanfransisco-source.github.io/naver-realestate-bot/'


def assess(cache, page, public_cache, now):
    soup = BeautifulSoup(page, 'html.parser')
    cards = cache.get('cards', {})
    expected = load_contents(CACHE, now=now)
    result = {'checkedAtKst': now.isoformat(), 'expectedGeneratedAtKst': cache.get('generatedAtKst'),
              'publicGeneratedAtKst': public_cache.get('generatedAtKst'), 'cards': {}}
    matched = len(soup.select('section.card')) == 29 and cache == public_cache
    for key in KEYS:
        entry = cards.get(key, {})
        area = soup.select_one('#ta-' + key)
        body_matches = bool(area and area.get_text() == expected[key])
        usable = valid_card(key, entry, now)
        expiry = entry.get('expiresAtKst')
        remaining = max(0, int((datetime.fromisoformat(expiry) - now).total_seconds())) if usable else 0
        parent = area.find_parent('section') if area else None
        expiry_guard = bool(not usable and area and area.get_text() == entry.get('body')
                            and parent and expiry and parent.get('data-expires') == expiry
                            and datetime.fromisoformat(expiry) <= now
                            and 'refreshDataCardExpiry' in page)
        result['cards'][key] = {'publicBodyMatches': body_matches, 'browserExpiryGuardPresent': expiry_guard,
                                'dailySnapshotReady': key == 'seoulcommerce' and entry.get('ready') is True and daily_seoul_snapshot(entry, now),
                                'sourceUsableNow': usable,
                                'remainingSourceSeconds': remaining, 'sourceWindow': entry.get('sourceWindow'),
                                'refreshStatus': entry.get('refreshStatus'), 'failureReason': entry.get('failureReason')}
        matched = matched and (body_matches or expiry_guard)
    result['deploymentMatched'] = matched
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempts', type=int, default=12)
    args = parser.parse_args()
    local = json.loads(CACHE.read_text(encoding='utf-8'))
    result = {}
    for attempt in range(args.attempts):
        now = datetime.now(KST)
        try:
            query = {'verify': local['generatedAtKst'], 'attempt': attempt}
            page = requests.get(BASE + 'briefing.html', params=query, timeout=15)
            page.raise_for_status()
            remote = requests.get(BASE + 'data-cards.json', params=query, timeout=15)
            remote.raise_for_status()
            result = assess(local, page.text, remote.json(), now)
        except (requests.RequestException, ValueError):
            result = {'checkedAtKst': now.isoformat(), 'deploymentMatched': False,
                      'failureReason': '공개 배포 조회 또는 형식 검증 실패'}
        if result.get('deploymentMatched'):
            break
        if attempt + 1 < args.attempts:
            time.sleep(8)
    target = Path('tmp/data-card-deployment-audit.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get('deploymentMatched'):
        raise SystemExit('Public deployment does not match the collected snapshot')


if __name__ == '__main__':
    main()
