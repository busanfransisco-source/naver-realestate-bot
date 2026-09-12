"""Policy authoring release gate; unlike display fallback, all six must be fresh."""
import argparse
import html
import re
from pathlib import Path
from datetime import datetime
from urllib.request import urlopen
from gen_briefing import KST, WEEKDAY_EN, is_fresh_analysis


def validate(today, page=None):
    errors = []
    weekday = WEEKDAY_EN[today.weekday()]
    for number in range(1, 7):
        name = f'analysis{number}-{weekday}.txt'
        path = Path(name)
        text = path.read_text(encoding='utf-8').strip() if path.exists() else ''
        if not is_fresh_analysis(text, today) or len(text) < 250 or 'https://' not in text or '준비되지 않았습니다' in text:
            errors.append(f'{name}: missing, stale or incomplete')
        if page is not None:
            match = re.search(rf'<textarea\b[^>]*id="ta-analysis{number}"[^>]*>(.*?)</textarea>', page, re.S)
            if not match or html.unescape(match.group(1)).strip() != text:
                errors.append(f'ta-analysis{number}: published content differs')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--html', type=Path)
    parser.add_argument('--url')
    args = parser.parse_args()
    page = args.html.read_text(encoding='utf-8') if args.html else None
    if args.url:
        with urlopen(args.url, timeout=30) as response:
            page = response.read().decode('utf-8')
    errors = validate(datetime.now(KST), page)
    print('\n'.join(errors) if errors else 'PASS: all 6 policy analyses are fresh and complete')
    raise SystemExit(bool(errors))
