"""Server-rendered daily content: stable slots, KST date, no API dependency."""
import json
from datetime import date
from pathlib import Path

LIBRARY_PATH = Path(__file__).with_name('daily-content-library.json')


def validate_entry(entry):
    if len(entry) != 4 or any(not isinstance(part, str) or not part.strip() for part in entry):
        raise ValueError('Incomplete daily content')
    # Exclude the individual title as well as the box label and date.
    body_length = len('\n\n'.join(entry[1:]))
    if not 300 <= body_length <= 700:
        raise ValueError(f'Daily content body must be 300-700 characters: {entry[0]} ({body_length})')
    return body_length


def build_rotating_sections(today):
    library = json.loads(LIBRARY_PATH.read_text(encoding='utf-8'))
    topics = library['topics']
    if len(topics) != 6:
        raise ValueError('Exactly six topics are required')
    elapsed = max(0, (today - date.fromisoformat(library['start_date'])).days)
    result = []
    for slot in range(6):
        topic = topics[(slot - elapsed) % 6]
        entry = topic['entries'][elapsed % len(topic['entries'])]
        validate_entry(entry)
        stamp = f'{today.year}년 {today.month}월 {today.day}일'
        content = '\n\n'.join([topic['label'], stamp, *entry])
        result.append((f'daily{19 + slot}', f'부동산 컨텐츠 {slot + 1}', content))
    return result
