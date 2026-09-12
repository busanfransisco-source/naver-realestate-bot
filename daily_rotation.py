"""Server-rendered daily content: stable slots, KST date, no API dependency."""
import json
from datetime import date
from pathlib import Path

LIBRARY_PATH = Path(__file__).with_name('daily-content-library.json')


def build_rotating_sections(today):
    library = json.loads(LIBRARY_PATH.read_text(encoding='utf-8'))
    topics = library['topics']
    if len(topics) != 5:
        raise ValueError('Exactly five topics are required')
    elapsed = max(0, (today - date.fromisoformat(library['start_date'])).days)
    result = []
    for slot in range(5):
        topic = topics[(slot - elapsed) % 5]
        entry = topic['entries'][elapsed % len(topic['entries'])]
        if len(entry) != 4 or any(not part.strip() for part in entry):
            raise ValueError('Incomplete daily content: ' + topic['key'])
        stamp = f'{today.year}년 {today.month}월 {today.day}일'
        content = '\n\n'.join([topic['label'], stamp, *entry])
        result.append((f'daily{19 + slot}', topic['label'], content))
    return result
