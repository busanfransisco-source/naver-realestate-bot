"""Read-only inventory of complete, validated daily manuscripts."""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from daily_rotation import CONTENT_DIR, validate_packet
from gen_briefing import KST


def inventory(today=None, root=CONTENT_DIR, validator=validate_packet):
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
    level = 'missing_today' if not days else 'low' if days <= 3 else 'ok'
    end = last.isoformat() if last else None
    return dict(checkedDateKst=today.isoformat(), remainingDaysIncludingToday=days,
                remainingFutureDays=max(days-1, 0), manuscripts=days*6,
                lastPreparedDate=end, nextMissingDate=(today+timedelta(days=days)).isoformat(),
                level=level, alertSignature=(f'{level}:{end or "none"}' if level != 'ok' else None))


if __name__ == '__main__':
    result = inventory()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result['level'] == 'missing_today' else 0)
