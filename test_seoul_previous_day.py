import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from seoul_previous_day import KST, capture_slot, render_previous_day, valid_snapshot, watch_slot, merge_archive
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

    def test_early_runner_keeps_newer_real_samples_until_target(self):
        current = [datetime(2026,10,9,11,29,tzinfo=KST)]
        saved = []
        def sleep(seconds):
            current[0] += timedelta(seconds=seconds)
        with patch('seoul_previous_day.read_archive', return_value={}), patch('seoul_previous_day.save_archive', side_effect=lambda days: saved.append(days['2026-10-09']['12']['sourceMinKst'])):
            self.assertTrue(watch_slot(12, clock=lambda: current[0], sleeper=sleep,
                                      fetch_rows=lambda: self.rows(current[0])))
        self.assertGreater(len(saved), 1)
        self.assertTrue(saved[-1].startswith('2026-10-09T12:00'))

    def test_late_runner_fails_without_calling_api(self):
        self.assertFalse(watch_slot(12, clock=lambda: datetime(2026,10,9,13,tzinfo=KST),
                                    fetch_rows=lambda: self.fail('late source must not replace noon')))

    def test_artifact_merge_preserves_other_slot_and_newer_sample(self):
        days = {}
        for hour in (12,18):
            now = datetime(2026,10,9,hour,5,tzinfo=KST)
            capture_slot(now,days,lambda: self.rows(now.replace(minute=0)))
        original = days['2026-10-09']['12']['body']
        earlier = {}
        before = datetime(2026,10,9,11,40,tzinfo=KST)
        capture_slot(before,earlier,lambda: self.rows(before))
        merge_archive(days,earlier)
        self.assertEqual(days['2026-10-09']['12']['body'], original)
        self.assertIn('18', days['2026-10-09'])

    def test_all_active_places_are_visible(self):
        from daily_data_card_sources import build_seoul_commerce_digest
        rows = self.rows(datetime(2026,10,9,12))
        for row in rows:
            row['relative_level'] = '바쁜'
        body = build_seoul_commerce_digest(rows, now_kst=datetime(2026,10,9,12))
        self.assertEqual(body.count('• 장소'),82)
        self.assertNotIn('이 밖에',body)

    def test_independent_capture_is_not_queued_behind_full_briefing(self):
        from pathlib import Path
        text = Path('.github/workflows/seoul-time-capture.yml').read_text(encoding='utf-8')
        capture = text.split('  publish:')[0]
        self.assertNotIn('group: manual-briefing',capture)
        self.assertIn('--watch-hour',capture)
        self.assertIn('--merge tmp/seoul-captured/seoul-time-snapshots.json --publish-only',text)


if __name__ == '__main__':
    unittest.main()
