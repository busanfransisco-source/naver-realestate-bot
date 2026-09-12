import json
import unittest
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch

import daily_rotation as rotation
import gen_briefing


class DailyRotationTests(unittest.TestCase):
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

    def test_fixed_slots_and_five_distinct_topics_every_day(self):
        start = date(2026, 9, 12)
        for offset in range(55):
            today = start + timedelta(days=offset)
            rows = rotation.build_rotating_sections(today)
            self.assertEqual([r[0] for r in rows], ['daily19', 'daily20', 'daily21', 'daily22', 'daily23'])
            self.assertEqual(len(set(r[1] for r in rows)), 5)
            self.assertTrue(all(len(r[2]) > 180 for r in rows))
            self.assertEqual(rows, rotation.build_rotating_sections(today))

    def test_each_fixed_slot_gets_all_55_stories_before_repeat(self):
        start = date(2026, 9, 12)
        for slot in range(5):
            stories = []
            for day in range(55):
                row = rotation.build_rotating_sections(start + timedelta(days=day))[slot]
                stories.append(row[2].split('\n\n')[2])
            self.assertEqual(len(set(stories)), 55)

    def test_topics_move_one_slot_right(self):
        before = rotation.build_rotating_sections(date(2026, 9, 12))
        after = rotation.build_rotating_sections(date(2026, 9, 13))
        self.assertEqual([r[1] for r in after], [before[-1][1]] + [r[1] for r in before[:-1]])

    def test_kst_midnight_changes_the_daily_selection(self):
        before = datetime(2026, 9, 12, 14, 59, tzinfo=timezone.utc).astimezone(gen_briefing.KST)
        after = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc).astimezone(gen_briefing.KST)
        self.assertNotEqual(rotation.build_rotating_sections(before.date()), rotation.build_rotating_sections(after.date()))

    def test_empty_old_sections_do_not_shift_slots(self):
        with patch.object(gen_briefing, 'read_section_text', return_value=''):
            page = gen_briefing.build_html()
        self.assertEqual(page.count('<section class="card"'), 23)
        for number in range(19, 24):
            self.assertIn(f'data-slot="{number}"', page)
            self.assertIn(f'id="ta-daily{number}"', page)


if __name__ == '__main__':
    unittest.main()
