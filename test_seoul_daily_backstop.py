import unittest
from datetime import datetime
from ensure_seoul_daily import needs_collection
from production_data_cards import KST, card_metadata

class SeoulDailyBackstopTests(unittest.TestCase):
    def test_daytime_missing_and_yesterday_retry(self):
        now = datetime(2026, 10, 7, 12, 5, tzinfo=KST)
        self.assertTrue(needs_collection(None, now))
        old = card_metadata('seoulcommerce', '조회: 2026-10-06 18:00\n원자료 시각: 17:40~17:50')
        self.assertTrue(needs_collection(old, now))

    def test_other_time_slot_is_also_eligible_for_fallback(self):
        entry = card_metadata('seoulcommerce', '조회: 2026-10-07 11:00\n원자료 시각: 10:40~10:50')
        self.assertTrue(needs_collection(entry, datetime(2026, 10, 7, 16, tzinfo=KST)))

    def test_midnight_does_not_collect_low_coverage(self):
        self.assertFalse(needs_collection(None, datetime(2026, 10, 7, 0, 58, tzinfo=KST)))

if __name__ == '__main__':
    unittest.main()
