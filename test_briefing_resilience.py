import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import gen_briefing
import market_fetch


class BriefingResilienceTests(unittest.TestCase):
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

                with mock.patch.object(market_fetch, "naver_market_items", return_value={}), \
                     mock.patch.object(market_fetch, "oil_detail", side_effect=RuntimeError), \
                     mock.patch.object(market_fetch, "fx_rates", return_value={}), \
                     mock.patch.object(market_fetch, "coins_top10", side_effect=RuntimeError), \
                     mock.patch.object(market_fetch, "get", side_effect=RuntimeError), \
                     mock.patch.object(market_fetch, "bestsellers", side_effect=RuntimeError("차단")):
                    market_fetch.main()

                for path in targets:
                    self.assertEqual(path.read_text(encoding="utf-8"), "기존 정상 베스트셀러 10권")
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
