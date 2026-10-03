from datetime import date, timedelta
from unittest import TestCase, mock

import preview_daily_data_cards as preview
import check_daily_data_connections as diagnostics


class PreviewDailyDataCardsTests(TestCase):
    def test_selected_seoul_does_not_fetch_other_sources(self):
        with mock.patch.object(preview, 'fetch_crypto_history') as crypto, \
             mock.patch.object(preview, 'fetch_wikimedia_digest') as wiki:
            contents = preview.preview_contents(only=('seoulcommerce',))
        self.assertEqual(set(contents), {'seoulcommerce'})
        crypto.assert_not_called()
        wiki.assert_not_called()

    def setUp(self):
        patcher = mock.patch.object(preview, 'fetch_seoul_commerce_digest',
                                    side_effect=preview.SourceUnavailable('test only'))
        patcher.start()
        self.addCleanup(patcher.stop)
        secrets = mock.patch.object(preview, 'load_secret', return_value='test-only')
        secrets.start()
        self.addCleanup(secrets.stop)

    def test_diagnostics_never_load_power_key_or_call_power_endpoints(self):
        history = [(date(2026, 10, 1) - timedelta(days=i), 70, 'Greed') for i in range(30)]
        with mock.patch.object(diagnostics, 'load_secret', return_value=None) as keys, \
             mock.patch.object(diagnostics.sources, 'fetch_crypto_history', return_value=history), \
             mock.patch.object(diagnostics.sources, 'fetch_wikimedia_digest', return_value='검증용\n집계 마감: 2026-09-30 (UTC)'), \
             mock.patch.object(diagnostics.requests, 'get') as get, \
             mock.patch.object(diagnostics.sources, 'parse_seoul_commerce_payload', return_value={
                 'observed_at_kst': date(2026, 10, 1)
             }):
            report = diagnostics.check_connections()
        self.assertEqual(set(report['sources']), {'crypto', 'wikimedia', 'seoul'})
        keys.assert_called_once_with('seoul')
        self.assertEqual(get.call_count, 1)
        self.assertIn('openapi.seoul.go.kr', get.call_args.args[0])

    def test_only_fresh_keyless_sources_become_preview_text(self):
        today = date(2026, 10, 1)
        history = [(today - timedelta(days=i), 70, "Greed") for i in range(30)]
        with mock.patch.object(preview, "fetch_crypto_history", return_value=history), \
             mock.patch.object(preview, "fetch_wikimedia_digest", return_value=(
                 "경제 주제 읽기 관심도\n집계 마감: 2026-09-30 (UTC)\n출처: Wikimedia"
             )):
            contents = preview.preview_contents(today_utc=today)
        self.assertEqual(set(contents), {"seoulcommerce", "cryptofear", "wikiinterest"})
        self.assertIn("70/100", contents["cryptofear"])
        self.assertIn("2026-09-30 (UTC)", contents["wikiinterest"])
        self.assertIn("자동공유 비활성", contents["seoulcommerce"])
        self.assertNotIn("kpxpower", contents)

    def test_stale_sources_fail_closed(self):
        today = date(2026, 10, 1)
        history = [(today - timedelta(days=i + 4), 70, "Greed") for i in range(30)]
        with mock.patch.object(preview, "fetch_crypto_history", return_value=history), \
             mock.patch.object(preview, "fetch_wikimedia_digest", return_value=(
                 "경제 주제 읽기 관심도\n집계 마감: 2026-09-20 (UTC)"
             )):
            contents = preview.preview_contents(today_utc=today)
        self.assertIn("집계 대기", contents["cryptofear"])
        self.assertIn("집계 대기", contents["wikiinterest"])
        self.assertNotIn("70/100", contents["cryptofear"])

    def test_diagnostic_reason_never_exposes_exception_url(self):
        secret_error = preview.requests.Timeout('http://example.test/PRIVATE_API_KEY?x=1')
        self.assertEqual(preview.failure_reason(secret_error), '네트워크 응답 시간 초과')
        diagnostics = {}
        with mock.patch.object(preview, 'fetch_crypto_history', side_effect=secret_error), \
             mock.patch.object(preview, 'fetch_wikimedia_digest', side_effect=preview.SourceUnavailable('old source')):
            preview.preview_contents(diagnostics=diagnostics)
        self.assertIn('cryptofear', diagnostics)
        self.assertNotIn('PRIVATE_API_KEY', str(diagnostics))
