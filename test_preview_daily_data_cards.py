from datetime import date, timedelta
from unittest import TestCase, mock

import preview_daily_data_cards as preview


class PreviewDailyDataCardsTests(TestCase):
    def test_only_fresh_keyless_sources_become_preview_text(self):
        today = date(2026, 10, 1)
        history = [(today - timedelta(days=i), 70, "Greed") for i in range(30)]
        with mock.patch.object(preview, "fetch_crypto_history", return_value=history), \
             mock.patch.object(preview, "fetch_wikimedia_digest", return_value=(
                 "경제 주제 읽기 관심도\n집계 마감: 2026-09-30 (UTC)\n출처: Wikimedia"
             )):
            contents = preview.preview_contents(today_utc=today)
        self.assertEqual(set(contents), {"seoulcommerce", "cryptofear", "kpxpower", "wikiinterest"})
        self.assertIn("70/100", contents["cryptofear"])
        self.assertIn("2026-09-30 (UTC)", contents["wikiinterest"])
        self.assertIn("자동공유 비활성", contents["seoulcommerce"])
        self.assertIn("자동공유 비활성", contents["kpxpower"])

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
