"""Verify the public morning bundle and its nine website copy fields."""
from datetime import datetime
import json
from pathlib import Path
import re
import time

from bs4 import BeautifulSoup
import requests

from morning_briefing_contract import BOX_KEYS, KST, validate_snapshot

BASE = 'https://busanfransisco-source.github.io/naver-realestate-bot/'


def verify_pair(snapshot, html, expected, now):
    bodies = validate_snapshot(snapshot, now)
    validate_snapshot(expected, now)
    if datetime.fromisoformat(snapshot['generatedAtKst']) < datetime.fromisoformat(expected['generatedAtKst']):
        raise ValueError('public snapshot is older than the published bundle')
    soup = BeautifulSoup(html, 'html.parser')
    for number, key, body in zip(range(1, 10), BOX_KEYS, bodies):
        if not body:
            # Its omission was explicitly hashed and validated above. Do not
            # confuse the web's explanatory placeholder with a sendable block.
            continue
        nodes = soup.select(f'textarea#ta-{key}')
        if len(nodes) != 1 or nodes[0].get_text().strip() != body.strip():
            raise ValueError(f'public morning body mismatch: {number}')
        section = nodes[0].find_parent('section', class_='card')
        heading = section.find('h2') if section else None
        if not heading or not re.match(rf'\s*{number}\s*[.)]', heading.get_text(' ', strip=True)):
            raise ValueError(f'public morning number mismatch: {number}')
        button = section.select_one('button.copy-btn')
        if not button or f"copySection('{key}'," not in button.get('onclick', ''):
            raise ValueError(f'public copy target mismatch: {number}')
    # The existing copy function reads these textarea values, not a second body.
    if "document.getElementById('ta-' + key)" not in html:
        raise ValueError('public copy implementation differs')
    return snapshot['snapshotSha256']


def verify_publication(expected, *, timeout=120, get=requests.get, now_fn=None, sleep=time.sleep):
    now_fn = now_fn or (lambda: datetime.now(KST))
    deadline = time.monotonic() + timeout
    while True:
        try:
            params = {'morningVerify': time.time_ns()}
            responses = [get(BASE + name, params=params, timeout=12,
                             headers={'Cache-Control': 'no-cache'})
                         for name in ('morning-briefing-ready.json', 'briefing.html')]
            for response in responses:
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError('unexpected public response size')
                response.encoding = 'utf-8'
            return verify_pair(responses[0].json(), responses[1].text, expected, now_fn())
        except (requests.RequestException, ValueError, KeyError, TypeError):
            if time.monotonic() >= deadline:
                raise ValueError('Public morning bundle/page verification did not complete before deadline') from None
            sleep(min(10, max(0, deadline - time.monotonic())))


if __name__ == '__main__':
    expected = json.loads(Path('morning-briefing-ready.json').read_text(encoding='utf-8'))
    digest = verify_publication(expected)
    print('Published morning bundle, boxes 1-9 and copy targets MATCH:', digest)
