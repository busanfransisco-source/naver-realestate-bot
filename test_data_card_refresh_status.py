from datetime import datetime
from pathlib import Path
import unittest
from production_data_cards import KST, card_metadata, refresh_succeeded
from daily_data_card_sources import SourceUnavailable
from preview_daily_data_cards import failure_reason


class RefreshStatusTests(unittest.TestCase):
    def test_retained_data_is_not_success_even_if_still_usable(self):
        now = datetime(2026,10,6,15,1,tzinfo=KST)
        body = '조회: 2026-10-06 15:01 (KST)\n원자료 시각: 14:40~14:40'
        entry = card_metadata('seoulcommerce', body)
        entry['refreshStatus'] = 'collected'
        data = {'cards': {'seoulcommerce': entry}}
        self.assertTrue(refresh_succeeded(data, ['seoulcommerce'], now))
        entry['refreshStatus'] = 'retained_valid_source'
        self.assertFalse(refresh_succeeded(data, ['seoulcommerce'], now))
        entry['refreshStatus'] = 'collected'
        self.assertFalse(refresh_succeeded(data, ['seoulcommerce'], now.replace(hour=16)))

    def test_freshness_rejection_has_correct_public_reason(self):
        self.assertEqual(failure_reason(SourceUnavailable('서울 상권 최근 30분 자료가 대상 장소의 75%에 못 미칩니다')),
                         '원자료 기준시각 또는 최신 표본 부족')

    def test_workflow_retry_and_failed_status_preserve_publish(self):
        workflow = Path('.github/workflows/daily-data-cards.yml').read_text(encoding='utf-8')
        self.assertIn('for attempt in 1 2', workflow)
        self.assertIn('--require-fresh', workflow)
        self.assertIn('continue-on-error: true', workflow)
        self.assertIn("steps.collect.outcome == 'failure'", workflow)


if __name__ == '__main__':
    unittest.main()
