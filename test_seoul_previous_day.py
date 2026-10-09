import unittest
from datetime import datetime, timedelta
from seoul_previous_day import KST, capture_slot, render_previous_day, valid_snapshot
from production_data_cards import card_metadata, valid_card


class PreviousDayTests(unittest.TestCase):
    def rows(self, now):
        return [{'area': f'장소{i}', 'observed_at_kst': now.replace(tzinfo=None),
                 'relative_level': '보통', 'industries': []} for i in range(82)]

    def test_two_slots_then_next_day_ready_and_no_overwrite(self):
        days = {}
        for hour in (12, 18):
            now = datetime(2026, 10, 9, hour, 5, tzinfo=KST)
            rows = self.rows(now.replace(minute=0))
            self.assertTrue(capture_slot(now, days, lambda: rows))
            self.assertFalse(capture_slot(now, days, lambda: self.fail('must stay fixed')))
            self.assertTrue(valid_snapshot(days['2026-10-09'][str(hour)], '2026-10-09', hour))
        tomorrow = datetime(2026, 10, 10, 9, tzinfo=KST)
        body = render_previous_day(tomorrow, days)
        self.assertIn('2026-10-09 (전날 · KST)', body)
        self.assertIn('전날 정오 기준', body)
        self.assertIn('전날 오후 6시 기준', body)
        entry = card_metadata('seoulcommerce', body)
        self.assertTrue(valid_card('seoulcommerce', entry, tomorrow))
        self.assertFalse(valid_card('seoulcommerce', entry, tomorrow+timedelta(days=1)))

    def test_late_job_and_later_source_cannot_fake_noon(self):
        days = {}
        self.assertFalse(capture_slot(datetime(2026,10,9,13,tzinfo=KST), days, lambda: self.fail()))
        with self.assertRaises(ValueError):
            capture_slot(datetime(2026,10,9,12,15,tzinfo=KST), days,
                         lambda: self.rows(datetime(2026,10,9,12,10)))
        self.assertEqual(days, {})

    def test_missing_slot_and_date_never_substitute(self):
        now = datetime(2026,10,9,12,5,tzinfo=KST)
        days = {}
        capture_slot(now, days, lambda: self.rows(now.replace(minute=0)))
        body = render_previous_day(now+timedelta(days=1), days)
        self.assertIn('미수집', body)
        self.assertFalse(card_metadata('seoulcommerce', body)['ready'])
        self.assertEqual(render_previous_day(now, days).count('미수집'), 2)


if __name__ == '__main__':
    unittest.main()
