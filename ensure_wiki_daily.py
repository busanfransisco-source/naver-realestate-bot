"""Bounded wiki-only backstop; preserve source dates and never send messages."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from production_data_cards import CACHE, KST, collect, valid_card


def recover(path=CACHE, *, now=None, force=False, collector=None):
    now = now or datetime.now(KST)
    try:
        entry = json.loads(Path(path).read_text(encoding='utf-8')).get('cards', {}).get('wikiinterest', {})
        if not isinstance(entry, dict):
            entry = {}
    except (OSError, ValueError, AttributeError):
        entry = {}
    if not force:
        if (valid_card('wikiinterest', entry, now)
                and entry['sourceDate'] == (now.astimezone(timezone.utc).date()-timedelta(days=1)).isoformat()):
            print('Wiki: latest completed UTC day already available')
            return True
        try:
            checked = datetime.fromisoformat(entry['checkedAtKst'])
            if checked.tzinfo is not None and timedelta(0) <= now-checked < timedelta(hours=2):
                print('Wiki: checked within two hours; saved source preserved')
                return valid_card('wikiinterest', entry, now)
        except (KeyError, TypeError, ValueError):
            pass
    result = (collector or collect)(path, only=('wikiinterest',))
    entry = result['cards']['wikiinterest']
    fresh = valid_card('wikiinterest', entry, now)
    print('Wiki:', entry.get('refreshStatus'), 'source:', entry.get('sourceDate'), 'fresh:', fresh)
    return fresh


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    raise SystemExit(0 if recover(force=args.force) else 1)
