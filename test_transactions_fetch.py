import unittest
from datetime import date

from realestate_transactions_fetch import (
    build_digest,
    classify_records,
    complex_area_key,
    parse_government_csv,
    tokenized_rows,
)


class TransactionDigestTests(unittest.TestCase):
    def sample(self, **changes):
        row = {
            "region_code": "11140",
            "region_name": "서울특별시 중구",
            "year": "2026",
            "month": "9",
            "day": "13",
            "dong": "순화동",
            "jibun": "1",
            "building_name": "덕수궁롯데캐슬",
            "area": 92.0,
            "floor": "12",
            "deal_amount": 150000,
            "price_per_pyeong": 5400,
        }
        row.update(changes)
        return row

    def test_duplicate_transactions_keep_their_count(self):
        rows = [self.sample(), self.sample()]
        self.assertEqual(len(tokenized_rows(rows)), 2)

    def test_record_high_requires_prior_history(self):
        row = self.sample()
        no_history = classify_records([row], {})[0]
        self.assertFalse(no_history["is_record"])
        key = complex_area_key(row)
        with_history = classify_records([row], {key: 140000})[0]
        self.assertTrue(with_history["is_record"])

    def test_digest_has_requested_spacing_and_no_source_link(self):
        row = self.sample(is_record=True)
        text = build_digest(date(2026, 9, 13), [row])
        self.assertTrue(text.startswith("9/13(일) 신규 등록 실거래가\n\n"))
        self.assertIn("전국 1건 (🔥1)", text)
        self.assertIn("\n\n[지역별 실거래가]\n", text)
        self.assertIn("서울 1건 (🔥1)", text)
        self.assertIn("\n\n[주요 신고가]\n", text)
        self.assertNotIn("수집 이후", text)
        self.assertNotIn("http", text)
        self.assertNotIn("오늘의 아파트", text)

    def test_all_regions_are_listed_and_fire_marker_is_fixed(self):
        rows = [
            self.sample(region_name=f"지역{i} 시군구", is_record=(i == 0), building_name=f"단지{i}")
            for i in range(6)
        ]
        text = build_digest(date(2026, 9, 13), rows)
        self.assertEqual(text.count("건 (🔥"), 7)
        for i in range(6):
            self.assertIn(f"지역{i} 1건 (🔥{1 if i == 0 else 0})", text)

    def test_government_csv_excludes_cancelled_deals(self):
        source = "\n".join(
            [
                '"안내"',
                '"NO","시군구","번지","본번","부번","단지명","전용면적(㎡)","계약년월","계약일","거래금액(만원)","동","층","매수자","매도자","건축년도","도로명","해제사유발생일","거래유형","중개사소재지","등기일자"',
                '"1","서울특별시 중구 순화동","1","1","0","덕수궁롯데캐슬","92","202609","13","150,000","-","12","개인","개인","2016","길","-","중개거래","서울 중구","-"',
                '"2","서울특별시 중구 순화동","1","1","0","취소단지","84","202609","13","100,000","-","3","개인","개인","2010","길","20260913","중개거래","서울 중구","-"',
            ]
        )
        rows = parse_government_csv(source.encode("cp949"))
        self.assertEqual([row["building_name"] for row in rows], ["덕수궁롯데캐슬"])


if __name__ == "__main__":
    unittest.main()
