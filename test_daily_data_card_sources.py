from datetime import date, datetime, timedelta, timezone
import unittest
from unittest import mock

import daily_data_card_sources as cards


class DailyDataCardSourceTests(unittest.TestCase):
    def test_crypto_uses_source_date_and_30_day_range(self):
        newest = date(2026, 10, 1)
        rows = [
            {
                "timestamp": str(int(datetime.combine(
                    newest - timedelta(days=offset),
                    datetime.min.time(), timezone.utc
                ).timestamp())),
                "value": str(74 - offset),
                "value_classification": "Greed",
            }
            for offset in range(31)
        ]
        response = mock.Mock()
        response.json.return_value = {"metadata": {"error": None}, "data": rows}
        session = mock.Mock()
        session.get.return_value = response
        digest = cards.build_crypto_digest(cards.fetch_crypto_history(session))
        self.assertIn("원자료 기준일: 2026-10-01 (UTC)", digest)
        self.assertIn("74/100", digest)
        self.assertIn("전일 +1점", digest)
        self.assertIn("최근 30일: 45~74점", digest)
        session.get.assert_called_once_with(
            cards.CRYPTO_URL,
            params={"limit": 31, "format": "json"},
            headers=None,
            timeout=25,
        )

    def test_crypto_rejects_missing_calendar_day(self):
        newest = date(2026, 10, 1)
        rows = [
            (newest - timedelta(days=offset), 50, "Fear")
            for offset in range(30) if offset != 2
        ]
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_crypto_digest(rows)

    def test_wikimedia_uses_common_utc_day_and_minimum_sample(self):
        newest = date(2026, 9, 30)
        days = [newest - timedelta(days=offset) for offset in range(14)]
        histories = {
            "금리": {
                day: (180 if offset < 7 else 100)
                for offset, day in enumerate(days)
            },
            "부동산": {day: 2 for day in days},
        }
        digest = cards.build_wikimedia_digest(histories)
        self.assertIn("2026-09-30 (UTC)", digest)
        self.assertIn("금리 1,260회 (직전 7일 700회, +80%)", digest)
        self.assertNotIn("부동산 14회", digest)
        self.assertIn("문서 조회수", digest)

    def test_wikimedia_requires_common_complete_days(self):
        newest = date(2026, 9, 30)
        histories = {
            "금리": {newest - timedelta(days=i): 100 for i in range(14)},
            "부동산": {newest - timedelta(days=i): 100 for i in range(13)},
        }
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_wikimedia_digest(histories)

    def test_wikimedia_request_identifies_client_and_article(self):
        response = mock.Mock()
        response.json.return_value = {
            "items": [{"timestamp": "2026093000", "views": 180, "article": "한국은행"}]
        }
        session = mock.Mock()
        session.get.return_value = response
        result = cards.fetch_wikimedia_history(
            session, "한국은행", date(2026, 9, 30), date(2026, 9, 30)
        )
        self.assertEqual(result[date(2026, 9, 30)], 180)
        args, kwargs = session.get.call_args
        self.assertIn("ko.wikipedia.org", args[0])
        self.assertEqual(kwargs["headers"]["User-Agent"], cards.WIKIMEDIA_USER_AGENT)


if __name__ == "__main__":
    unittest.main()
