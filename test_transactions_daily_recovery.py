import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import ensure_transactions_daily as recovery


TODAY = date(2026, 10, 13)


def source():
    return {'since': '2026-10-12T20:00:00Z', 'totalCount': 1,
            'allTimeHighCount': 0, 'preconstructedSaleCount': 0,
            'oneHundredMillionClubCount': 0, 'oneHundredMillionClubAllTimeHighCount': 0,
            'sidoStats': [{'sidoShortName': '서울', 'count': 1, 'allTimeHighCount': 0}],
            'allTimeHighTransactions': [], 'highlightTransactions': []}


class TransactionRecoveryTests(unittest.TestCase):
    def test_before_five_defers_but_five_and_daytime_recover(self):
        for hour, expected_calls in ((4, 0), (5, 1), (12, 1), (17, 1)):
            with self.subTest(hour=hour), patch.object(recovery, 'datetime') as clock, patch.object(recovery, 'recover', return_value=True) as collect:
                clock.now.return_value = datetime(2026, 10, 13, hour, tzinfo=recovery.KST)
                self.assertTrue(recovery.main())
                self.assertEqual(collect.call_count, expected_calls)

    def test_existing_pending_file_is_replaced_by_verified_today(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value=source()):
            target = Path(folder)/'transactions-2026-10-13.txt'
            target.write_text('10/13(화) 신규 등록 실거래가\n오늘 자료를 수집 중입니다.', encoding='utf-8')
            self.assertTrue(recovery.recover(TODAY, folder, fetch=Mock(), sleeper=Mock()))
            self.assertTrue(recovery.complete_today(target.read_text(encoding='utf-8'), TODAY))

    def test_missing_today_is_recovered_and_all_three_files_match(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value=source()):
            self.assertTrue(recovery.recover(TODAY, folder, fetch=Mock(return_value='source'), sleeper=Mock()))
            root = Path(folder)
            text = (root/'transactions-2026-10-13.txt').read_text(encoding='utf-8')
            self.assertTrue(recovery.complete_today(text, TODAY))
            self.assertEqual(text, (root/'transactions-tue.txt').read_text(encoding='utf-8'))
            self.assertEqual(text, (root/'transactions.txt').read_text(encoding='utf-8'))

    def test_already_collected_day_never_refetches_or_overwrites(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value=source()):
            recovery.recover(TODAY, folder, fetch=Mock(), sleeper=Mock())
            fetch = Mock(side_effect=AssertionError('must not fetch'))
            self.assertTrue(recovery.recover(TODAY, folder, fetch=fetch, sleeper=Mock()))
            fetch.assert_not_called()

    def test_stale_upstream_is_not_relabelled_and_previous_files_preserved(self):
        old = {**source(), 'since': '2026-10-11T20:00:00Z'}
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value=old):
            path = Path(folder)/'transactions.txt'
            path.write_text('previous verified source', encoding='utf-8')
            fetch, sleep = Mock(), Mock()
            self.assertFalse(recovery.recover(TODAY, folder, fetch=fetch, sleeper=sleep))
            self.assertEqual(fetch.call_count, 2)
            sleep.assert_called_once_with(3)
            self.assertEqual(path.read_text(encoding='utf-8'), 'previous verified source')
            self.assertFalse((Path(folder)/'transactions-2026-10-13.txt').exists())

    def test_network_error_is_bounded_and_next_attempt_can_recover(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value=source()):
            fetch = Mock(side_effect=[RuntimeError('temporary outage'), 'good source'])
            self.assertTrue(recovery.recover(TODAY, folder, fetch=fetch, sleeper=Mock()))
            self.assertEqual(fetch.call_count, 2)

    def test_missing_counts_or_truncated_record_list_cannot_publish_false_zero(self):
        variants = [{k: v for k, v in source().items() if k != 'totalCount'},
                    {**source(), 'allTimeHighCount': 1},
                    {**source(), 'preconstructedSaleCount': -1}]
        for summary in variants:
            with self.subTest(summary=summary), tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value=summary):
                self.assertFalse(recovery.recover(TODAY, folder, fetch=Mock(), sleeper=Mock()))
                self.assertFalse((Path(folder)/'transactions.txt').exists())

    def test_upstream_confirmed_zero_is_valid(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(recovery, 'parse_today_summary', return_value={**source(), 'totalCount': 0, 'sidoStats': []}):
            self.assertTrue(recovery.recover(TODAY, folder, fetch=Mock(), sleeper=Mock()))
            self.assertIn('전국 0건', (Path(folder)/'transactions.txt').read_text(encoding='utf-8'))

    def test_inconsistent_zero_or_missing_regional_counts_are_rejected(self):
        for changes in ({'totalCount': 0}, {'sidoStats': []}, {'preconstructedSaleCount': 2},
                        {'oneHundredMillionClubCount': 2}, {'oneHundredMillionClubAllTimeHighCount': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                recovery.validate_summary({**source(), **changes}, TODAY)

    def test_check_only_rejects_missing_or_baseline_then_accepts_completed_source(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(recovery.check_today(folder, TODAY))
            path = Path(folder)/'transactions-2026-10-13.txt'
            path.write_text('10/13(화) 신규 등록 실거래가\n전국 비교 기준 데이터 저장을 완료했습니다.', encoding='utf-8')
            self.assertFalse(recovery.check_today(folder, TODAY))
            with patch.object(recovery, 'parse_today_summary', return_value=source()):
                recovery.recover(TODAY, folder, fetch=Mock(), sleeper=Mock())
            self.assertTrue(recovery.check_today(folder, TODAY))


if __name__ == '__main__':
    unittest.main()
