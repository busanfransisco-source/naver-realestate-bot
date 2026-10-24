import json
import unittest
from datetime import date
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import apt_today_closings_fetch as fetcher

from apt_today_closings_fetch import (
    build_digest,
    decode_next_payloads,
    extract_json_object,
    format_transaction,
)


class AptTodayClosingsTests(unittest.TestCase):
    def test_explicit_source_restriction_never_tries_reader(self):
        for status in (403, 429):
            with self.subTest(status=status), \
                 patch('curl_cffi.requests.get', return_value=Mock(status_code=status)) as direct, \
                 patch.object(fetcher.urllib.request, 'urlopen') as reader:
                with self.assertRaises(fetcher.SourceBlocked) as caught:
                    fetcher.fetch_page_html()
                self.assertEqual(caught.exception.status_code, status)
                direct.assert_called_once()
                reader.assert_not_called()

    def test_http_restriction_exception_never_tries_reader(self):
        for status in (403, 429):
            response_error = RuntimeError('restricted')
            response_error.response = Mock(status_code=status)
            errors = (HTTPError(fetcher.SOURCE_URL, status, 'restricted', {}, None), response_error)
            for error in errors:
                with self.subTest(status=status, error=type(error).__name__), \
                     patch('curl_cffi.requests.get', side_effect=error), \
                     patch.object(fetcher.urllib.request, 'urlopen') as reader:
                    with self.assertRaises(fetcher.SourceBlocked) as caught:
                        fetcher.fetch_page_html()
                    self.assertEqual(caught.exception.status_code, status)
                    reader.assert_not_called()

    def test_checkpoint_body_is_not_treated_as_missing_data_or_retried(self):
        response = Mock(status_code=200, text='<title>Vercel Security Checkpoint</title>')
        with patch('curl_cffi.requests.get', return_value=response), \
             patch.object(fetcher.urllib.request, 'urlopen') as reader:
            with self.assertRaises(fetcher.SourceBlocked):
                fetcher.fetch_page_html()
            reader.assert_not_called()

    def test_normal_source_response_is_returned_without_reader(self):
        response = Mock(status_code=200, text='valid todaySummary payload')
        with patch('curl_cffi.requests.get', return_value=response), \
             patch.object(fetcher.urllib.request, 'urlopen') as reader:
            self.assertEqual(fetcher.fetch_page_html(), response.text)
            reader.assert_not_called()

    def test_transient_network_failure_can_use_existing_reader(self):
        reply = Mock()
        reply.__enter__ = Mock(return_value=reply)
        reply.__exit__ = Mock(return_value=None)
        reply.read.return_value = b'valid todaySummary payload'
        with patch('curl_cffi.requests.get', side_effect=TimeoutError('temporary timeout')), \
             patch.object(fetcher.urllib.request, 'urlopen', return_value=reply) as reader:
            self.assertEqual(fetcher.fetch_page_html(), 'valid todaySummary payload')
            reader.assert_called_once()

    def test_reader_rate_limit_is_reported_as_blocked(self):
        error = HTTPError(fetcher.READER_URL, 429, 'restricted', {}, None)
        with patch('curl_cffi.requests.get', side_effect=TimeoutError('temporary timeout')), \
             patch.object(fetcher.urllib.request, 'urlopen', side_effect=error) as reader:
            with self.assertRaises(fetcher.SourceBlocked) as caught:
                fetcher.fetch_page_html()
            self.assertEqual(caught.exception.status_code, 429)
            reader.assert_called_once()

    def test_fallback_estimates_pyeong_type_only_when_source_supply_is_missing(self):
        transaction = {
            "danjiName": "전용59", "amount": 280000, "exclusiveArea": 59.97,
            "type": {}, "sido": {"shortName": "서울"},
            "sigungu": {"name": "강남구", "shortName": "강남"},
        }
        self.assertIn("전용59 약26평형 28억", format_transaction(transaction))
        transaction["type"] = {"supplyPY": 27}
        self.assertIn("전용59 27평형 28억", format_transaction(transaction))

    def test_decodes_next_payload_and_extracts_today_summary(self):
        summary = {
            "since": "2026-09-13T15:00:00.000Z",
            "totalCount": 57,
            "allTimeHighCount": 5,
        }
        payload = "6:" + json.dumps({"todaySummary": summary}, ensure_ascii=False)
        page = f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script>"
        decoded = decode_next_payloads(page)
        self.assertEqual(extract_json_object(decoded[0], "todaySummary"), summary)

    def test_digest_uses_exact_counts_and_removes_site_links(self):
        summary = {
            "since": "2026-09-13T15:00:00.000Z",
            "totalCount": 57,
            "preconstructedSaleCount": 5,
            "allTimeHighCount": 5,
            "oneHundredMillionClubAllTimeHighCount": 0,
            "oneHundredMillionClubCount": 0,
            "sidoStats": [
                {"sidoShortName": "충남", "count": 30, "allTimeHighCount": 1},
                {"sidoShortName": "서울", "count": 9, "allTimeHighCount": 3},
            ],
            "highlightTransactions": [],
        }
        target_date, text = build_digest(summary)
        self.assertEqual(target_date, date(2026, 9, 14))
        self.assertIn("전국 57건 (🔥5)", text)
        self.assertIn("분양권/입주권 5건", text)
        self.assertIn("충남 30건 (🔥1)", text)
        self.assertLess(text.index("서울 9건"), text.index("충남 30건"))
        self.assertNotIn("apt.today", text)
        self.assertNotIn("http", text)

    def test_digest_lists_every_nationwide_record_high(self):
        record_highs = [
            {
                "id": number,
                "danjiName": f"신고가단지{number}",
                "amount": 100000 + number,
                "isPYAllTimeHigh": True,
                "type": {"supplyPY": 34},
                "sido": {"shortName": "서울"},
                "sigungu": {"name": "강남구", "shortName": "강남"},
            }
            for number in range(1, 6)
        ]
        summary = {
            "since": "2026-09-13T15:00:00.000Z",
            "totalCount": 57,
            "preconstructedSaleCount": 5,
            "allTimeHighCount": 5,
            "sidoStats": [],
            "highlightTransactions": record_highs[:2],
            "allTimeHighTransactions": record_highs,
        }
        _, text = build_digest(summary)
        for number in range(1, 6):
            self.assertIn(f"신고가단지{number}", text)
        self.assertEqual(text.count("신고가단지"), 5)

    def test_record_highs_are_grouped_by_region_then_price_descending(self):
        def row(number, region, amount):
            return {
                "id": number,
                "danjiName": f"{region}{amount}",
                "amount": amount,
                "isPYAllTimeHigh": True,
                "type": {"supplyPY": 34},
                "sido": {"shortName": region},
                "sigungu": {"name": "테스트구", "shortName": "테스트"},
            }

        record_highs = [
            row(1, "부산", 500000),
            row(2, "서울", 100000),
            row(3, "인천", 250000),
            row(4, "경기", 300000),
            row(5, "서울", 200000),
        ]
        summary = {
            "since": "2026-09-13T15:00:00.000Z",
            "totalCount": 5,
            "allTimeHighCount": 5,
            "sidoStats": [],
            "highlightTransactions": [],
            "allTimeHighTransactions": record_highs,
        }
        _, text = build_digest(summary)
        names = ["서울200000", "서울100000", "경기300000", "인천250000", "부산500000"]
        positions = [text.index(name) for name in names]
        self.assertEqual(positions, sorted(positions))
        headings = ["🏙️ 서울", "🏘️ 경기", "🌉 인천", "🌊 부산"]
        heading_positions = [text.index(heading) for heading in headings]
        self.assertEqual(heading_positions, sorted(heading_positions))


if __name__ == "__main__":
    unittest.main()
