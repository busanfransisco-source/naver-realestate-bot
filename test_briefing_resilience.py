import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import json
from datetime import date

import gen_briefing
import market_fetch


class BriefingResilienceTests(unittest.TestCase):
    def test_30_card_preview_keeps_policy_analyses_last(self):
        preview = gen_briefing.build_html(new_data_contents={
            key: f"{label}\n원자료 기준일: 2026-10-01"
            for key, label in gen_briefing.NEW_DATA_SECTIONS
        })
        self.assertEqual(preview.count('<section class="card"'), 30)
        for number, (key, label) in enumerate(gen_briefing.NEW_DATA_SECTIONS, start=20):
            self.assertIn(f'<h2>{number}. {label}</h2>', preview)
            self.assertIn(f'id="ta-{key}"', preview)
        for number, key in enumerate(
            ('analysis3', 'analysis4', 'analysis5', 'analysis2', 'analysis6', 'analysis1', 'analysis7'),
            start=24,
        ):
            self.assertIn(f'data-slot="{number}"', preview)
            self.assertIn(f'id="ta-{key}"', preview)
        self.assertLess(preview.index('id="ta-wikiinterest"'), preview.index('id="ta-analysis3"'))

    def test_30_card_preview_rejects_incomplete_data(self):
        with self.assertRaises(ValueError):
            gen_briefing.build_html(new_data_contents={'cryptofear': '10/1 기준 74점'})

    def test_transactions_reject_stale_weekday_and_show_today_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path("transactions-thu.txt").write_text(
                    "9/24(목) 신규 등록 실거래가\n\n전국 1,736건", encoding="utf-8"
                )
                Path("transactions.txt").write_text(
                    "9/30(수) 신규 등록 실거래가\n\n전국 1,748건", encoding="utf-8"
                )
                content = gen_briefing.read_transactions_text(date(2026, 10, 1))
                self.assertTrue(content.startswith("10/1(목) 신규 등록 실거래가"))
                self.assertIn("수집 중", content)
                self.assertNotIn("1,736", content)
                self.assertNotIn("1,748", content)
            finally:
                os.chdir(previous)

    def test_transactions_prefer_today_dated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path("transactions-2026-10-01.txt").write_text(
                    "10/1(목) 신규 등록 실거래가\n\n전국 321건", encoding="utf-8"
                )
                Path("transactions-thu.txt").write_text(
                    "9/24(목) 신규 등록 실거래가\n\n전국 1,736건", encoding="utf-8"
                )
                self.assertIn(
                    "전국 321건",
                    gen_briefing.read_transactions_text(date(2026, 10, 1)),
                )
            finally:
                os.chdir(previous)

    def test_new_policy_box_is_appended_without_renumbering_existing_boxes(self):
        generated = gen_briefing.build_html()
        self.assertIn('<h2>13. ⭕ 오늘의 부동산 OX</h2>', generated)
        self.assertIn('<h2>18. 📦 이사 준비 한 가지</h2>', generated)
        self.assertIn('<h2>19. 🏢 전국 신규 등록 실거래가</h2>', generated)
        self.assertIn('<h2>26. 📰 부동산 불장의 진실 정책분석</h2>', generated)
        self.assertIn('id="ta-analysis7"', generated)

    def test_market_workflows_commit_fuel_cache(self):
        for workflow_name in ("manual-briefing.yml", "naver-realestate.yml"):
            workflow = Path(".github/workflows", workflow_name).read_text(encoding="utf-8")
            self.assertIn("fuel-cache.json", workflow)

    def test_oil_detail_uses_new_naver_energy_json(self):
        response = mock.Mock()
        response.json.return_value = {
            "closePrice": "1,858.50",
            "fluctuations": "-0.07",
        }
        with mock.patch.object(market_fetch, "get", return_value=response) as mocked_get:
            self.assertEqual(market_fetch.oil_detail("OIL_GSL"), (1858.5, -0.07))
        mocked_get.assert_called_once_with(
            "https://stock.naver.com/api/securityService/marketindex/energy/OIL_GSL"
        )

    def test_fx_rates_use_new_naver_exchange_json(self):
        def response_for(url, **kwargs):
            response = mock.Mock()
            response.json.return_value = {
                "exchangeInfo": {
                    "closePrice": "1,383.70",
                    "fluctuationsRatio": "0.12",
                    "localTradedAt": "2026-09-18T10:14:53+09:00",
                }
            }
            return response

        with mock.patch.object(market_fetch, "get", side_effect=response_for) as mocked_get:
            rates = market_fetch.fx_rates()
        self.assertEqual(rates["USD"]["value"], 1383.7)
        self.assertEqual(rates["USD"]["change_pct"], 0.12)
        self.assertIn(
            "https://stock.naver.com/api/securityService/marketindex/exchange/FX_USDKRW",
            [call.args[0] for call in mocked_get.call_args_list],
        )

    def test_partial_fuelfx_keeps_valid_exchange_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path("fuelfx-wed.txt").write_text(
                    "26년 9월 16일 수요일 기름값·환율\n\n"
                    "⛽ 전국 평균 기름값\n\n"
                    "(기름값을 가져오지 못했습니다)\n\n"
                    "💱 주요국 환율\n\n미국 달러 : 1,364.00원",
                    encoding="utf-8",
                )
                content = gen_briefing.read_section_text("fuelfx", "wed")
                self.assertIn("미국 달러 : 1,364.00원", content)
                self.assertNotIn("가져오지 못했습니다", content)
            finally:
                os.chdir(previous)

    def test_previous_valid_books_are_used_when_today_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path("books-mon.txt").write_text(
                    "(베스트셀러를 가져오지 못했습니다)", encoding="utf-8"
                )
                Path("books.txt").write_text(
                    "(베스트셀러를 가져오지 못했습니다)", encoding="utf-8"
                )
                Path("books-sun.txt").write_text("기존 정상 베스트셀러 10권", encoding="utf-8")
                self.assertEqual(
                    gen_briefing.read_section_text("books", "mon"),
                    "기존 정상 베스트셀러 10권",
                )
            finally:
                os.chdir(previous)

    def test_failed_collection_does_not_overwrite_existing_books(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                weekday = market_fetch.WEEKDAY_EN[
                    market_fetch.datetime.now(market_fetch.KST).weekday()
                ]
                targets = [Path("books.txt"), Path(f"books-{weekday}.txt")]
                for path in targets:
                    path.write_text("기존 정상 베스트셀러 10권", encoding="utf-8")
                Path("fx-cache.json").write_text(
                    json.dumps({"USD": 1380.5}), encoding="utf-8"
                )

                with mock.patch.object(market_fetch, "naver_market_items", return_value={}), \
                     mock.patch.object(market_fetch, "oil_detail", side_effect=RuntimeError), \
                     mock.patch.object(market_fetch, "fx_rates", return_value={}), \
                     mock.patch.object(market_fetch, "coins_top10", side_effect=RuntimeError), \
                     mock.patch.object(market_fetch, "get", side_effect=RuntimeError), \
                     mock.patch.object(market_fetch, "bestsellers", side_effect=RuntimeError("차단")):
                    market_fetch.main()

                for path in targets:
                    self.assertEqual(path.read_text(encoding="utf-8"), "기존 정상 베스트셀러 10권")
                self.assertIn(
                    "미국 달러 : 1,380.50원 (직전 정상값)",
                    Path("fuelfx.txt").read_text(encoding="utf-8"),
                )
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
