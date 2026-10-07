import json
import re
import unittest
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch

import daily_rotation as rotation
import gen_briefing


class DailyRotationTests(unittest.TestCase):
    def test_every_sentence_has_a_blank_line(self):
        library = json.loads(rotation.LIBRARY_PATH.read_text(encoding='utf-8'))
        for topic in library['topics']:
            for entry in topic['entries']:
                for paragraph in entry[1:]:
                    self.assertIsNone(re.search(r'[.!?][”’]?[ \t]+', paragraph), entry[0])

    def test_all_library_bodies_meet_length_rule(self):
        library = json.loads(rotation.LIBRARY_PATH.read_text(encoding='utf-8'))
        for topic in library['topics']:
            for entry in topic['entries']:
                with self.subTest(topic=topic['key'], title=entry[0]):
                    self.assertGreaterEqual(rotation.validate_entry(entry), 300)
                    self.assertLessEqual(rotation.validate_entry(entry), 700)

    def test_length_boundaries_exclude_title(self):
        for length in (299, 300, 700, 701):
            entry = ['title' * 100, 'a', 'b', 'c' * (length - 6)]
            if 300 <= length <= 700:
                self.assertEqual(rotation.validate_entry(entry), length)
            else:
                with self.assertRaises(ValueError):
                    rotation.validate_entry(entry)

    def test_fixed_slots_and_six_distinct_topics_every_day(self):
        start = date(2026, 9, 12)
        topics = json.loads(rotation.LIBRARY_PATH.read_text(encoding='utf-8'))['topics']
        labels = [topic['label'] for topic in topics]
        for offset in range(66):
            today = start + timedelta(days=offset)
            rows = rotation.build_rotating_sections(today)
            self.assertEqual([r[0] for r in rows], ['daily19', 'daily20', 'daily21', 'daily22', 'daily23', 'daily24'])
            self.assertEqual([r[1] for r in rows], labels)
            self.assertEqual([r[2].split('\n\n')[0] for r in rows], labels)
            self.assertTrue(all('준비되지 않았습니다' in r[2] or len(r[2]) > 180 for r in rows))
            self.assertEqual(rows, rotation.build_rotating_sections(today))

    def test_missing_day_never_cycles_old_stories(self):
        for today in (date(2026, 9, 12), date(2026, 9, 23), date(2099, 1, 1)):
            rows = rotation.build_rotating_sections(today)
            self.assertTrue(all('오늘의 새 원고가 아직 준비되지 않았습니다' in row[2] for row in rows))
            self.assertTrue(all('같은 전용면적' not in row[2] for row in rows))

    def test_topics_stay_in_the_same_slot(self):
        before = rotation.build_rotating_sections(date(2026, 10, 7))
        after = rotation.build_rotating_sections(date(2026, 10, 8))
        self.assertEqual([r[1] for r in before], [r[1] for r in after])
        old_topics = [r[2].split('\n\n')[0] for r in before]
        new_topics = [r[2].split('\n\n')[0] for r in after]
        self.assertEqual(new_topics, old_topics)
        self.assertNotEqual([r[2] for r in before], [r[2] for r in after])

    def test_kst_midnight_changes_the_daily_selection(self):
        before = datetime(2026, 10, 7, 14, 59, tzinfo=timezone.utc).astimezone(gen_briefing.KST)
        after = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc).astimezone(gen_briefing.KST)
        self.assertNotEqual(rotation.build_rotating_sections(before.date()), rotation.build_rotating_sections(after.date()))

    def test_today_originals_pass_and_relabelled_date_fails(self):
        packet = json.loads((rotation.CONTENT_DIR / '2026-10-07.json').read_text(encoding='utf-8'))
        rotation.validate_packet(packet, date(2026,10,7))
        for topic in packet['topics']:
            for paragraph in topic['entry'][1:]:
                self.assertIsNone(re.search(r'[.!?][”’]?[ \t]+', paragraph), topic['entry'][0])
        with self.assertRaisesRegex(ValueError, 'date/count'):
            rotation.validate_packet(packet, date(2026,10,8))
        packet['date'] = '2026-10-08'
        with self.assertRaisesRegex(ValueError, 'Repeated'):
            rotation.validate_packet(packet, date(2026,10,8))

    def test_legacy_title_cannot_be_republished(self):
        packet = json.loads((rotation.CONTENT_DIR / '2026-10-07.json').read_text(encoding='utf-8'))
        packet['topics'][0]['entry'][0] = '같은 전용면적이면 집 안의 느낌도 같을까요?'
        with self.assertRaisesRegex(ValueError, 'Repeated'):
            rotation.validate_packet(packet, date(2026,10,7))

    def test_public_originals_gate_rejects_other_body(self):
        from verify_daily_originals import verify
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026,10,7,20,0,tzinfo=tz)
        with patch.object(gen_briefing, 'datetime', FrozenDateTime):
            page = gen_briefing.build_html()
        self.assertTrue(verify(page, date(2026,10,7)))
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            verify(page.replace('창문이 많으면 환기도 무조건 잘될까요?', '다른 제목'), date(2026,10,7))

    def test_prepared_month_has_six_new_stories_each_day(self):
        titles = {topic['key']: set() for topic in json.loads(rotation.LIBRARY_PATH.read_text(encoding='utf-8'))['topics']}
        for offset in range(30):
            today = date(2026,10,8) + timedelta(days=offset)
            path = rotation.CONTENT_DIR / (today.isoformat()+'.json')
            self.assertTrue(path.exists(), str(path))
            packet = json.loads(path.read_text(encoding='utf-8'))
            rotation.validate_packet(packet, today)
            for topic in packet['topics']:
                self.assertNotIn(topic['entry'][0], titles[topic['key']])
                titles[topic['key']].add(topic['entry'][0])
                for paragraph in topic['entry'][1:]:
                    self.assertIsNone(re.search(r'[.!?][”’]?[ \t]+', paragraph), topic['entry'][0])
        self.assertTrue(all(len(values) == 30 for values in titles.values()))

    def test_empty_old_sections_do_not_shift_slots(self):
        with patch.object(gen_briefing, 'read_section_text', return_value=''):
            page = gen_briefing.build_html()
        self.assertEqual(page.count('<section class="card"'), 26)
        for number in range(13, 19):
            self.assertIn(f'data-slot="{number}"', page)
            self.assertIn(f'id="ta-daily{number + 6}"', page)
        self.assertIn('data-slot="19"', page)
        self.assertIn('id="ta-transactions"', page)
        self.assertIn('data-slot="26"', page)
        self.assertIn('id="ta-analysis7"', page)
        for number, key in enumerate(('analysis3', 'analysis4', 'analysis5', 'analysis2', 'analysis6', 'analysis1'), 20):
            self.assertIn(f'<h2>{number}. ', page)
            self.assertIn(f'data-slot="{number}"', page)
            self.assertIn(f'id="ta-{key}"', page)
        self.assertLess(page.index('id="ta-transactions"'), page.index('id="ta-analysis3"'))
        self.assertLess(page.index('id="ta-analysis1"'), page.index('id="ta-analysis7"'))


if __name__ == '__main__':
    unittest.main()
