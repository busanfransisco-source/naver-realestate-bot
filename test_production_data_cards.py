import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import production_data_cards as cards
import gen_briefing


class ProductionDataCardsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 3, 18, 20, tzinfo=cards.KST)
        self.seoul = '서울 주요 상권 실시간\n조회: 2026-10-03 18:15 (KST)\n원자료 시각: 18:10~18:15 · 최근 30분 자료만 반영'
        self.crypto = '비트코인 공포·탐욕\n원자료 기준일: 2026-10-03 (UTC)'
        self.wiki = '경제 주제 읽기 관심도\n집계 마감: 2026-10-02 (UTC)'

    def test_valid_source_clocks(self):
        for key, body in zip(cards.KEYS, (self.seoul, self.crypto, self.wiki)):
            self.assertTrue(cards.valid_card(key, cards.card_metadata(key, body), self.now))

    def test_seoul_expiry_is_source_based_not_collect_time(self):
        entry = cards.card_metadata('seoulcommerce', self.seoul)
        self.assertEqual(entry['expiresAtKst'], '2026-10-03T18:40:00+09:00')
        self.assertFalse(cards.valid_card('seoulcommerce', entry, self.now + timedelta(minutes=20)))

    def test_seoul_previous_day_and_future_fail_closed(self):
        entry = cards.card_metadata('seoulcommerce', self.seoul)
        self.assertFalse(cards.valid_card('seoulcommerce', entry, self.now - timedelta(hours=1)))
        self.assertFalse(cards.valid_card('seoulcommerce', entry, self.now + timedelta(days=1)))

    def test_utc_date_age_limits(self):
        entry = cards.card_metadata('cryptofear', self.crypto)
        self.assertFalse(cards.valid_card('cryptofear', entry, self.now + timedelta(days=2)))
        entry = cards.card_metadata('wikiinterest', self.wiki)
        self.assertFalse(cards.valid_card('wikiinterest', entry, self.now - timedelta(days=1)))
        self.assertFalse(cards.valid_card('wikiinterest', entry, self.now + timedelta(days=3)))

    def test_expiry_tampering_is_not_accepted(self):
        entry = cards.card_metadata('seoulcommerce', self.seoul)
        entry['expiresAtKst'] = '2099-01-01T00:00:00+09:00'
        self.assertFalse(cards.valid_card('seoulcommerce', entry, self.now))

    def test_cache_corruption_and_expiry_hide_bodies(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cards.json'
            path.write_text('{bad', encoding='utf-8')
            self.assertTrue(all('집계 대기' in body for body in cards.load_contents(path, now=self.now).values()))
            path.write_text(json.dumps({'cards': {'seoulcommerce': cards.card_metadata('seoulcommerce', self.seoul)}}), encoding='utf-8')
            self.assertEqual(cards.load_contents(path, now=self.now)['seoulcommerce'], self.seoul)
            self.assertIn('집계 대기', cards.load_contents(path, now=self.now + timedelta(hours=1))['seoulcommerce'])

    def test_production_main_always_requests_29_cards(self):
        with patch('production_data_cards.load_contents', return_value={key: cards.pending_body(key) for key in cards.KEYS}), patch('gen_briefing.build_html', return_value='rendered') as build, patch('builtins.open', unittest.mock.mock_open()):
            gen_briefing.main()
        self.assertEqual(set(build.call_args.kwargs['new_data_contents']), set(cards.KEYS))

    def test_html_has_browser_expiry_gate(self):
        content = gen_briefing.build_html(new_data_contents={key: cards.pending_body(key) for key in cards.KEYS})
        self.assertEqual(content.count('data-data-card="true"'), 3)
        self.assertIn('setInterval(refreshDataCardExpiry, 15000)', content)
        self.assertIn("업데이트됩니다.\\n자동공유 비활성'", content)

    def test_non_object_cache_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cards.json'
            for data in ({'cards': []}, {'cards': {'cryptofear': 'bad'}}):
                path.write_text(json.dumps(data), encoding='utf-8')
                self.assertTrue(all('집계 대기' in body for body in cards.load_contents(path, now=self.now).values()))

    def test_collect_retains_only_valid_source_without_relabeling(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cards.json'
            old = cards.card_metadata('cryptofear', self.crypto)
            old['collectedAtKst'] = '2026-10-03T17:00:00+09:00'
            path.write_text(json.dumps({'cards': {'cryptofear': old}}), encoding='utf-8')
            with patch('production_data_cards.datetime') as clock, patch('preview_daily_data_cards.preview_contents', return_value={k: cards.pending_body(k) for k in cards.KEYS}):
                clock.now.return_value = self.now
                clock.fromisoformat.side_effect = datetime.fromisoformat
                data = cards.collect(path)
            current = data['cards']['cryptofear']
            self.assertEqual(current['refreshStatus'], 'retained_valid_source')
            for field in ('body', 'sourceDate', 'sourceWindow', 'expiresAtKst', 'collectedAtKst'):
                self.assertEqual(current[field], old[field])
            self.assertFalse(data['cards']['seoulcommerce']['ready'])
            self.assertIn('보류 사유:', data['cards']['seoulcommerce']['body'])

    def test_collect_never_reuses_expired_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cards.json'
            path.write_text(json.dumps({'cards': {'seoulcommerce': cards.card_metadata('seoulcommerce', self.seoul)}}), encoding='utf-8')
            with patch('production_data_cards.datetime') as clock, patch('preview_daily_data_cards.preview_contents', return_value={k: cards.pending_body(k) for k in cards.KEYS}):
                clock.now.return_value = self.now + timedelta(hours=1)
                clock.fromisoformat.side_effect = datetime.fromisoformat
                data = cards.collect(path)
            self.assertFalse(data['cards']['seoulcommerce']['ready'])
            self.assertNotIn('18:10~18:15', data['cards']['seoulcommerce']['body'])


if __name__ == '__main__':
    unittest.main()
