"""Dated original manuscripts; never recycle or relabel an old story."""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

LIBRARY_PATH = Path(__file__).with_name('daily-content-library.json')
CONTENT_DIR = Path(__file__).with_name('daily-content')


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
    path = CONTENT_DIR / (today.isoformat() + '.json')
    packet = None
    if path.exists():
        packet = json.loads(path.read_text(encoding='utf-8'))
        validate_packet(packet, today)
    result = []
    for slot in range(6):
        topic = topics[slot]
        if packet is None:
            content = '\n\n'.join([topic['label'], '오늘의 새 원고가 아직 준비되지 않았습니다.',
                '이전 글을 오늘 자료처럼 반복하지 않습니다. 새 원고 검수 후 업데이트됩니다.'])
            result.append((f'daily{19 + slot}', topic['label'], content))
            continue
        entry = packet['topics'][slot]['entry']
        stamp = f'{today.year}년 {today.month}월 {today.day}일'
        content = '\n\n'.join([topic['label'], stamp, *entry])
        result.append((f'daily{19 + slot}', topic['label'], content))
    return result


def normalized(text):
    return re.sub(r'\W+', '', text).lower()


def validate_packet(packet, today):
    library = json.loads(LIBRARY_PATH.read_text(encoding='utf-8'))
    topics = packet.get('topics', [])
    if packet.get('date') != today.isoformat() or len(topics) != 6:
        raise ValueError('Daily manuscript date/count mismatch')
    history = {topic['key']: list(topic['entries']) for topic in library['topics']}
    prior_angles = {topic['key']: set() for topic in library['topics']}
    for archive in CONTENT_DIR.glob('*.json'):
        if archive.stem >= today.isoformat():
            continue
        previous = json.loads(archive.read_text(encoding='utf-8'))
        for topic in previous['topics']:
            history[topic['key']].append(topic['entry'])
            prior_angles[topic['key']].add(normalized(topic.get('editorialAngle', '')))
    titles = set()
    for topic, expected in zip(topics, library['topics']):
        if topic.get('key') != expected['key'] or topic.get('label') != expected['label']:
            raise ValueError('Daily manuscript topic/slot mismatch')
        entry = topic['entry']
        validate_entry(entry)
        if not topic.get('editorialAngle') or not isinstance(topic.get('sources'), list):
            raise ValueError('Editorial angle and source notes required')
        if normalized(topic['editorialAngle']) in prior_angles[topic['key']]:
            raise ValueError('Repeated editorial angle: '+entry[0])
        if any(not isinstance(url, str) or not url.startswith('https://') for url in topic['sources']):
            raise ValueError('Invalid source URL: '+entry[0])
        if topic['key'] == 'money' and re.search(r'\d', '\n'.join(entry[1:])) and not topic['sources']:
            if not re.search(r'가상|가정', '\n'.join(entry[1:])):
                raise ValueError('Hypothetical arithmetic must state its assumptions: '+entry[0])
        title = normalized(entry[0])
        body = normalized('\n'.join(entry[1:]))
        if title in titles:
            raise ValueError('Duplicate daily title')
        titles.add(title)
        for old in history[topic['key']]:
            if title == normalized(old[0]) or SequenceMatcher(None, body, normalized('\n'.join(old[1:])), autojunk=False).ratio() >= .72:
                raise ValueError('Repeated daily manuscript: '+entry[0])
