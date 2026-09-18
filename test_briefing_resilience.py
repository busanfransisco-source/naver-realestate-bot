import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import json

import gen_briefing
import market_fetch


class BriefingResilienceTests(unittest.TestCase):
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
