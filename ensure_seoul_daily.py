"""Daytime backstop: fetch only when a genuine today snapshot is missing."""
import json
import time
from datetime import datetime
from pathlib import Path
from production_data_cards import KST, CACHE, stored_seoul_snapshot, collect, refresh_succeeded

def needs_collection(entry, now):
    if not 10 <= now.hour < 21:
        return False
    return not (stored_seoul_snapshot(entry, now) and entry.get('sourceDate') == now.date().isoformat())

def main():
    now = datetime.now(KST)
    try:
        entry = json.loads(Path(CACHE).read_text(encoding='utf-8')).get('cards', {}).get('seoulcommerce')
    except (OSError, ValueError, AttributeError):
        entry = None
    if not needs_collection(entry, now):
        print('Seoul daily backstop: already collected today or outside daytime window')
        return
    for attempt in range(2):
        data = collect(only=('seoulcommerce',))
        if refresh_succeeded(data, ('seoulcommerce',)):
            print('Seoul daily backstop: today source collected')
            return
        if attempt == 0:
            time.sleep(30)
    raise SystemExit('Seoul daily backstop failed; original source date preserved')

if __name__ == '__main__':
    main()
