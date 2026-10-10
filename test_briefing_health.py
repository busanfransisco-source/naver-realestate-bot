import unittest
from datetime import datetime
from unittest.mock import patch
from pathlib import Path
from briefing_health import inspect, KEYS, KST
from validate_policy import validate


class HealthTests(unittest.TestCase):
    def page(self):
        return ''.join(f'<section class="card" data-slot="{i}"><textarea id="ta-{k}">2026-10-06\n' +
                       '자료 설명입니다. ' * 40 + '</textarea></section>' for i, k in enumerate(KEYS, 1))

    def test_all_29_checked_and_partial_gold_rejected(self):
        rows = inspect(self.page(), datetime(2026, 10, 6, 15, tzinfo=KST))
        self.assertEqual(len(rows), 29)
        self.assertEqual(rows[6]['status'], 'failed')
        self.assertIn('missing required item: 국제 금', rows[6]['issues'])

    def test_stale_analysis7_cannot_pass(self):
        page = self.page().replace('id="ta-analysis7">2026-10-06', 'id="ta-analysis7">2026-09-30')
        row = inspect(page, datetime(2026, 10, 6, 15, tzinfo=KST))[-1]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('not today material', row['issues'])

    def test_pending_before_collection_deadline(self):
        page = self.page().replace('id="ta-transactions">2026-10-06', 'id="ta-transactions">수집 중입니다')
        self.assertEqual(inspect(page, datetime(2026, 10, 6, 6, tzinfo=KST))[18]['status'], 'pending')

    def test_missing_card_detected(self):
        rows = inspect(self.page().replace('ta-ai', 'ta-wrong'), datetime(2026, 10, 6, 15, tzinfo=KST))
        self.assertIn('missing/duplicate/wrong slot', rows[11]['issues'])

    def test_transaction_missing_is_failure_after_seven_not_noon(self):
        page = self.page().replace('id="ta-transactions">2026-10-06', 'id="ta-transactions">수집 중입니다')
        row = inspect(page, datetime(2026, 10, 6, 7, 30, tzinfo=KST))[18]
        self.assertEqual(row['status'], 'failed')

    def test_workflows_gate_after_publish(self):
        for name in ('manual-briefing', 'naver-realestate', 'daily-data-cards', 'transactions', 'weather', 'fortune'):
            text = Path(f'.github/workflows/{name}.yml').read_text(encoding='utf-8')
            self.assertIn('briefing_health.py --url', text)

    def test_seoul_previous_day_is_accepted_only_when_both_slots_exist(self):
        from production_data_cards import card_metadata
        body = '📍 서울 주요 상권\n기준일: 2026-10-05 (전날 · KST)\n🕛 전날 정오 기준\n🌆 전날 오후 6시 기준\n'+'관찰 자료입니다. '*30
        page = self.page()
        start = page.index('id="ta-seoulcommerce">')+len('id="ta-seoulcommerce">')
        end = page.index('</textarea>',start)
        page = page[:start]+body+page[end:]
        row = inspect(page,datetime(2026,10,6,9,tzinfo=KST))[19]
        self.assertEqual(row['status'],'ok')
        page = page.replace('관찰 자료입니다.','미수집',1)
        row = inspect(page,datetime(2026,10,6,9,tzinfo=KST))[19]
        self.assertEqual(row['status'],'failed')


if __name__ == '__main__':
    unittest.main()
