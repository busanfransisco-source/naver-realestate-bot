import json
import tempfile
import unittest
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import production_data_cards as cards
from ensure_wiki_daily import recover
from daily_data_card_sources import build_wikimedia_digest
from briefing_health import inspect, REPAIR
from gen_briefing import build_html


def wiki_body(day):
    return build_wikimedia_digest({'부동산': {day-timedelta(days=i): 40+i for i in range(14)}})


class WikiRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, 14, tzinfo=cards.KST)
        self.old = cards.card_metadata('wikiinterest', wiki_body(self.now.date()-timedelta(days=5)))
        self.old['collectedAtKst'] = '2026-10-18T10:15:00+09:00'
        self.fresh = wiki_body(self.now.date()-timedelta(days=1))

    def render(self, body):
        now = self.now
        class FixedClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromtimestamp(now.timestamp(), tz)
        with patch('gen_briefing.datetime', FixedClock):
            return build_html(new_data_contents={key: body if key=='wikiinterest' else cards.pending_body(key) for key in cards.KEYS})

    def run_collection(self, path, body):
        with patch('production_data_cards.datetime') as clock, \
             patch('preview_daily_data_cards.preview_contents', return_value={'wikiinterest': body}) as fetch:
            clock.now.return_value = self.now
            clock.fromisoformat.side_effect = datetime.fromisoformat
            result = cards.collect(path, only=('wikiinterest',))
        self.assertTrue(fetch.call_args.kwargs['allow_delayed_wiki'])
        return result

    def test_expired_snapshot_stays_readable_with_real_source_clock(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cache.json'
            path.write_text(json.dumps({'cards': {'wikiinterest': self.old}}), encoding='utf-8')
            text = cards.load_contents(path, now=self.now)['wikiinterest']
            self.assertIn(cards.WIKI_DELAY_NOTICE, text)
            self.assertIn('2026-10-15 (UTC)', text)
            self.assertNotIn('집계 대기', text)
            self.assertFalse(cards.valid_card('wikiinterest', self.old, self.now))

    def test_retry_failure_preserves_raw_body_and_old_collection_time(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cache.json'
            path.write_text(json.dumps({'cards': {'wikiinterest': self.old,
                                                 'cryptofear': {'ready': False, 'untouched': True}}}), encoding='utf-8')
            result = self.run_collection(path, cards.pending_body('wikiinterest'))
            entry = result['cards']['wikiinterest']
            self.assertEqual(entry['body'], self.old['body'])
            self.assertEqual(entry['collectedAtKst'], self.old['collectedAtKst'])
            self.assertEqual(entry['expiresAtKst'], self.old['expiresAtKst'])
            self.assertFalse(entry['ready'])
            self.assertFalse(cards.refresh_succeeded(result, ['wikiinterest'], self.now))
            self.assertEqual(result['cards']['cryptofear'], {'ready': False, 'untouched': True})

    def test_delayed_api_response_can_bootstrap_display_without_faking_freshness(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cache.json'
            result = self.run_collection(path, self.old['body'])
            self.assertFalse(result['cards']['wikiinterest']['ready'])
            self.assertEqual(result['cards']['wikiinterest']['sourceDate'], '2026-10-15')
            self.assertIn(cards.WIKI_DELAY_NOTICE, cards.load_contents(path, now=self.now)['wikiinterest'])

    def test_fresh_source_automatically_clears_retained_notice(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cache.json'
            path.write_text(json.dumps({'cards': {'wikiinterest': self.old}}), encoding='utf-8')
            result = self.run_collection(path, self.fresh)
            self.assertTrue(result['cards']['wikiinterest']['ready'])
            self.assertTrue(cards.refresh_succeeded(result, ['wikiinterest'], self.now))
            self.assertEqual(cards.load_contents(path, now=self.now)['wikiinterest'], self.fresh)
            self.assertNotIn(cards.WIKI_DELAY_NOTICE, self.fresh)

    def test_api_response_cannot_downgrade_newer_saved_window(self):
        entry = cards.card_metadata('wikiinterest', self.fresh)
        chosen = cards.select_wiki_entry(self.old, entry, self.now, None)
        self.assertEqual(chosen['sourceDate'], '2026-10-19')
        self.assertTrue(chosen['ready'])
        self.assertEqual(chosen['refreshStatus'], 'retained_valid_source')

    def test_corrupt_or_future_snapshot_is_not_used_for_display(self):
        for entry in (dict(self.old, expiresAtKst='2099-01-01T00:00:00+09:00'),
                      cards.card_metadata('wikiinterest', wiki_body(self.now.date())),
                      cards.card_metadata('wikiinterest', wiki_body(self.now.date()+timedelta(days=1))),
                      dict(self.old, body='알 수 없는 문장입니다.')):
            self.assertFalse(cards.stored_wiki_snapshot(entry, self.now))

    def test_health_reports_delay_separately_from_missing_data(self):
        entry = dict(self.old, ready=False)
        body = cards.wiki_display_body(entry, self.now)
        page = self.render(body)
        row = inspect(page, self.now)[21]
        self.assertEqual(row['status'], 'delayed')
        self.assertTrue(row['sourceDelayed'])
        self.assertFalse(row['issues'])
        self.assertIn('data-preserve-source="true"', page)
        self.assertEqual(REPAIR['wikiinterest'], 'ensure_wiki_daily.py')

    def test_old_page_gets_browser_retention_instead_of_erasing_body(self):
        page = self.render(self.fresh)
        self.assertIn("key === 'wikiinterest' && card.dataset.preserveSource === 'true'", page)
        self.assertIn('이전 자료 복사', page)

    def test_browser_expiry_keeps_original_numbers_and_only_adds_notice_once(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is needed for browser-script execution')
        page = self.render(self.fresh)
        script = page[page.index('function refreshDataCardExpiry()'):page.index('refreshDataCardExpiry();\nsetInterval')]
        expected = cards.wiki_display_body(dict(cards.card_metadata('wikiinterest', self.fresh), ready=False), self.now+timedelta(days=7))
        harness = '''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const initial = BODY;
const ta = {id: 'ta-wikiinterest', value: initial};
const button = {disabled: false};
const card = {
 dataset: {preserveSource: 'true', expires: '2026-10-23T09:00:00+09:00'},
 querySelector: selector => selector === 'textarea' ? ta : button
};
const context = {
 Date: class extends Date {static now() {return Date.parse('2026-10-27T12:00:00+09:00')}},
 window: {}, document: {querySelectorAll: () => [card]}
};
vm.runInNewContext(SCRIPT, context);
context.refreshDataCardExpiry();
assert.equal(ta.value, EXPECTED);
assert.equal(context.window.__content_wikiinterest, EXPECTED);
assert.equal(button.disabled, false);
context.refreshDataCardExpiry();
assert.equal(ta.value, EXPECTED);
'''.replace('BODY', json.dumps(self.fresh)).replace('SCRIPT', json.dumps(script)).replace('EXPECTED', json.dumps(expected))
        result = subprocess.run([node, '-e', harness], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_delayed_display_is_not_audit_send_ready_success(self):
        import audit_data_cards as audit
        entry = dict(self.old, ready=False)
        body = cards.wiki_display_body(entry, self.now)
        cache = {'cards': {key: entry if key=='wikiinterest' else cards.card_metadata(key, cards.pending_body(key)) for key in cards.KEYS}}
        expected = {key: body if key=='wikiinterest' else cards.pending_body(key) for key in cards.KEYS}
        with patch.object(audit, 'load_contents', return_value=expected):
            result = audit.assess(cache, self.render(body), cache, self.now)
        self.assertTrue(result['deploymentMatched'])
        self.assertTrue(result['cards']['wikiinterest']['retainedForDisplay'])
        self.assertFalse(result['cards']['wikiinterest']['sourceUsableNow'])

    def test_only_production_opt_in_can_retrieve_a_delayed_digest(self):
        from preview_daily_data_cards import preview_contents
        with patch('preview_daily_data_cards.fetch_wikimedia_digest', return_value=self.old['body']):
            hidden = preview_contents(today_utc=self.now.date(), only=('wikiinterest',))
            shown = preview_contents(today_utc=self.now.date(), only=('wikiinterest',), allow_delayed_wiki=True)
        self.assertIn('집계 대기', hidden['wikiinterest'])
        self.assertEqual(shown['wikiinterest'], self.old['body'])

    def test_backstop_throttles_checked_source_and_retries_when_due(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cache.json'
            entry = dict(self.old, checkedAtKst=(self.now-timedelta(minutes=30)).isoformat())
            path.write_text(json.dumps({'cards': {'wikiinterest': entry}}), encoding='utf-8')
            with patch('ensure_wiki_daily.collect') as collect:
                self.assertFalse(recover(path, now=self.now))
                collect.assert_not_called()
                collect.return_value = {'cards': {'wikiinterest': cards.card_metadata('wikiinterest', self.fresh)}}
                self.assertTrue(recover(path, now=self.now+timedelta(hours=2)))
                collect.assert_called_once_with(path, only=('wikiinterest',))

    def test_backstop_missing_cache_and_latest_completed_day(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'cache.json'
            with patch('ensure_wiki_daily.collect', return_value={'cards': {'wikiinterest': cards.card_metadata('wikiinterest', self.fresh)}}) as collect:
                self.assertTrue(recover(path, now=self.now))
                collect.assert_called_once()
            path.write_text(json.dumps({'cards': {'wikiinterest': cards.card_metadata('wikiinterest', self.fresh)}}), encoding='utf-8')
            with patch('ensure_wiki_daily.collect') as collect:
                self.assertTrue(recover(path, now=self.now))
                collect.assert_not_called()

    def test_existing_daytime_workflows_recheck_wiki_and_keep_cache(self):
        for workflow in ('manual-briefing', 'daily-data-cards'):
            text = Path(f'.github/workflows/{workflow}.yml').read_text(encoding='utf-8')
            self.assertIn('python ensure_wiki_daily.py', text)
            self.assertIn('git add data-cards.json', text)
        text = Path('.github/workflows/naver-realestate.yml').read_text(encoding='utf-8')
        self.assertIn('git add data-cards.json', text[text.index('briefing_health.py --repair'):])


if __name__ == '__main__':
    unittest.main()
