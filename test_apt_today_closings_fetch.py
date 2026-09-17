import json
import unittest
from datetime import date

from apt_today_closings_fetch import (
    build_digest,
    decode_next_payloads,
    extract_json_object,
)


class AptTodayClosingsTests(unittest.TestCase):
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
