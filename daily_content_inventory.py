"""Read-only inventory of complete, validated daily manuscripts."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from daily_rotation import CONTENT_DIR, validate_packet
from gen_briefing import KST

STOCK_MANIFEST = Path(__file__).with_name('daily-content-stock.json')
ALERT_PERCENT = 20


def read_baseline(path=STOCK_MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding='utf-8'))
    total = manifest['baselineManuscripts']
    first = date.fromisoformat(manifest['preparedFrom'])
    last = date.fromisoformat(manifest['preparedThrough'])
    if type(total) is not int or total <= 0 or total != ((last-first).days+1)*6:
        raise ValueError('invalid manuscript stock baseline')
    return total


def inventory(today=None, root=CONTENT_DIR, validator=validate_packet, *, baseline_manuscripts=None):
    baseline = read_baseline() if baseline_manuscripts is None else baseline_manuscripts
    if type(baseline) is not int or baseline <= 0 or baseline % 6:
        raise ValueError('baseline must contain complete six-manuscript packets')
    today = today or datetime.now(KST).date()
    root = Path(root)
    checked = {}

    def valid(day):
        if day not in checked:
            try:
                packet = json.loads((root / (day.isoformat() + '.json')).read_text(encoding='utf-8'))
                validator(packet, day)
                checked[day] = True
            except (OSError, ValueError, KeyError, TypeError):
                checked[day] = False
        return checked[day]

    days = 0
    while days < 370 and valid(today + timedelta(days=days)):
        days += 1
    last = today + timedelta(days=days-1) if days else None
    if last is None:
        for path in sorted(root.glob('*.json'), reverse=True):
            try:
                day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if day < today and valid(day):
                last = day
                break
    remaining = days*6
    level = 'missing_today' if not days else 'low' if remaining*100 <= baseline*ALERT_PERCENT else 'ok'
    end = last.isoformat() if last else None
    return dict(checkedDateKst=today.isoformat(), remainingDaysIncludingToday=days,
                remainingFutureDays=max(days-1, 0), manuscripts=remaining,
                baselineManuscripts=baseline, remainingPercent=round(remaining*100/baseline, 2),
                alertAtOrBelowPercent=ALERT_PERCENT,
                lastPreparedDate=end, nextMissingDate=(today+timedelta(days=days)).isoformat(),
                level=level, alertSignature=(f'{level}:{end or "none"}' if level != 'ok' else None))


if __name__ == '__main__':
    result = inventory()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['level'] == 'missing_today' else 0)
