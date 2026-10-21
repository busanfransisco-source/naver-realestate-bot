"""Apply a verified cloud morning bundle to the latest website checkout.

Run only inside the GitHub publication job. No scheduler, keys or messaging.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

from morning_briefing_contract import BOX_KEYS, KST, validate_snapshot
from neonet_trend import format_digest


def apply_bundle(snapshot_path, trend_path, *, root='.', now=None):
    now = now or datetime.now(KST)
    root = Path(root)
    snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    bodies = validate_snapshot(snapshot, now)
    trend = json.loads(Path(trend_path).read_text(encoding='utf-8'))
    if (trend.get('checkedAtKst') != snapshot['evidence']['trendCheckedAtKst']
            or format_digest(trend).strip() != bodies[4].strip()):
        raise ValueError('morning weekly body and actual source cache differ')
    target = root / 'morning-briefing-ready.json'
    if target.is_file():
        try:
            old = json.loads(target.read_text(encoding='utf-8'))
            validate_snapshot(old, now)
            if datetime.fromisoformat(old['generatedAtKst']) >= datetime.fromisoformat(snapshot['generatedAtKst']):
                return False
        except (ValueError, KeyError, TypeError):
            pass
    weekday = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[now.weekday()]
    payloads = {}
    for key, body in zip(BOX_KEYS, bodies):
        for name in (f'{key}.txt', f'{key}-{weekday}.txt'):
            payloads[name] = body
        if key in ('fortune', 'weather', 'realestate'):
            payloads[f'{key}-{now.date().isoformat()}.txt'] = body
    payloads['neonet-trend-cache.json'] = json.dumps(trend, ensure_ascii=False, indent=2) + '\n'
    payloads['morning-briefing-ready.json'] = json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n'
    # Everything has passed before any website input is changed. Publication is
    # one Git commit; never stage arbitrary artifact paths or environment files.
    for name, content in payloads.items():
        temporary = root / (name + '.morning-tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(root / name)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--trend-cache', required=True)
    args = parser.parse_args()
    changed = apply_bundle(args.snapshot, args.trend_cache)
    print('Cloud morning bundle applied' if changed else 'Newer verified cloud bundle already published; unchanged')
