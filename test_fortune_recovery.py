import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import requests
import fortune_fetch as fortune
import gen_briefing
from morning_cloud_prepare import _run_group, read_sources
from morning_briefing_contract import BOX_KEYS

NOW = datetime(2026, 11, 24, 6, 5, tzinfo=fortune.KST)


def report(day=NOW):
    lines = [f"오늘의 운세, {day.month}월 {day.day}일", "[음력 10월 16일] 일진: 임인(壬寅)", ""]
    for animal in fortune.ANIMALS:
        lines.extend([f"〈{animal}띠〉", "", "확인한 내용을 차분히 살펴보고 계획을 진행하십시오.", "", "",
                      "운세지수 62%. 금전 60 건강 65 애정 60", ""])
    return "\n".join(lines).strip()


def fallback_html(day=NOW, animals=fortune.ANIMALS):
    header = f"{day.year}년 {day.month}월 {day.day}일"
    paragraphs = "".join(
        f"<p>오늘의 {'호랑이' if animal == '범' else animal}(子)띠 운세 -&gt; "
        "확인한 내용을 차분히 살펴보고 계획을 진행하십시오. "
        "운세지수 62%. 금전 60 건강 65 애정 60</p>" for animal in animals)
    return (f"<title>[지윤철학원의 오늘의 운세] {header} 화요일 띠별 운세</title>"
            f'<div class="view_con"><p>[오늘의 운세] {header} 화요일(음력 10월 16일) '
            f"일진: 임인(壬寅) 오늘의 띠별 운세</p>{paragraphs}</div>")


def fallback_responses(*, html=None, release=None, day=NOW):
    search = Mock()
    search.json.return_value = {"list": [{
        "title": f"[지윤철학원의 오늘의 운세] {day.year}년 {day.month}월 {day.day}일 화요일 띠별 운세",
        "id": "20261123500259",
        "releaseDate": release or "2026-11-23T18:33:33.000+0000",
    }]}
    article = Mock(text=html or fallback_html(day))
    return search, article


class FortuneRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_cwd = os.getcwd()
        os.chdir(self.directory.name)

    def tearDown(self):
        os.chdir(self.original_cwd)
        self.directory.cleanup()

    def test_primary_timeout_uses_independent_publisher_and_preserves_fixed_format(self):
        with patch.object(fortune, "find_today_document_srl", side_effect=requests.Timeout()), \
             patch.object(fortune.requests, "get", side_effect=fallback_responses()) as get:
            actual = fortune.build_report(NOW)
        self.assertEqual(actual, report())
        self.assertEqual(get.call_args_list[0].args[0], fortune.FALLBACK_BASE + "/rest/search")
        self.assertEqual(get.call_args_list[1].args[0], fortune.FALLBACK_BASE + "/article/20261123500259")

    def test_missing_or_partial_primary_also_uses_fallback(self):
        for srl, body in ((None, ""), (1, "〈쥐띠〉\n일부 본문")):
            with self.subTest(srl=srl), \
                 patch.object(fortune, "find_today_document_srl", return_value=(srl, "오늘의 운세, 11월 24일")), \
                 patch.object(fortune, "fetch_document_text", return_value=("", body)), \
                 patch.object(fortune.requests, "get", side_effect=fallback_responses()):
                self.assertEqual(fortune.build_report(NOW), report())

    def test_wrong_date_future_release_and_partial_fallback_are_rejected(self):
        cases = [
            fallback_responses(day=NOW-timedelta(days=1)),
            fallback_responses(release="2026-11-24T06:30:00+09:00"),
            fallback_responses(html=fallback_html(animals=fortune.ANIMALS[:-1])),
            fallback_responses(html=fallback_html(NOW-timedelta(days=1))),
        ]
        for responses in cases:
            with self.subTest(responses=responses), \
                 patch.object(fortune, "find_today_document_srl", side_effect=requests.Timeout()), \
                 patch.object(fortune.requests, "get", side_effect=responses):
                with self.assertRaises(ValueError):
                    fortune.build_report(NOW)

    def test_complete_saved_today_is_reused_without_network_or_file_changes(self):
        path = Path("fortune-2026-11-24.txt")
        path.write_text(report(), encoding="utf8")
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(fortune, "datetime", wraps=datetime) as clock, \
             patch.object(fortune.requests, "get") as get:
            clock.now.return_value = NOW
            self.assertEqual(fortune.main(), 0)
            get.assert_not_called()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(gen_briefing.read_section_text("fortune", "tue", NOW), report())

    def test_failed_collection_preserves_previous_files_and_returns_failure(self):
        paths = [Path("fortune.txt"), Path("fortune-tue.txt"), Path("fortune-2026-11-23.txt")]
        for path in paths:
            path.write_text(report(NOW-timedelta(days=1)), encoding="utf8")
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        with patch.object(fortune, "datetime", wraps=datetime) as clock, \
             patch.object(fortune, "build_report", side_effect=requests.Timeout()):
            clock.now.return_value = NOW
            self.assertEqual(fortune.main(), 1)
        self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths])
        self.assertFalse(Path("fortune-2026-11-24.txt").exists())
        self.assertEqual(fortune.load_report(NOW), fortune.UNAVAILABLE)

    def test_dated_complete_body_wins_in_cloud_and_no_collection_is_scheduled(self):
        Path("fortune-2026-11-24.txt").write_text(report(), encoding="utf8")
        Path("fortune-tue.txt").write_text("수집 실패", encoding="utf8")
        runner = Mock()
        state = _run_group(Path("."), ("fortune", "fortune_fetch.py", ("fortune",)),
                           NOW, time.monotonic()+60, runner, fixed_clock=True)
        runner.assert_not_called()
        self.assertEqual(state["status"], "ok")
        self.assertEqual(state["boxes"][0]["status"], "retained_fortune")
        bodies, _ = read_sources(".", NOW, only_keys=("fortune",))
        self.assertEqual(bodies[BOX_KEYS.index("fortune")], report())

    def test_next_day_collects_new_forecast_and_never_relabels_yesterday(self):
        Path("fortune.txt").write_text(report(), encoding="utf8")
        tomorrow = NOW + timedelta(days=1)
        with patch.object(fortune, "datetime", wraps=datetime) as clock, \
             patch.object(fortune, "build_report", return_value=report(tomorrow)) as fetch:
            clock.now.return_value = tomorrow
            self.assertEqual(fortune.main(), 0)
            fetch.assert_called_once_with(tomorrow)
        self.assertEqual(Path("fortune-2026-11-25.txt").read_text(encoding="utf8"), report(tomorrow))

    def test_same_date_in_previous_year_primary_page_is_rejected(self):
        html = '<div class="date" title="등록일"><strong>2025.11.20</strong></div>' \
               '<div class="xe_content">오늘의 운세, 11월 24일〈쥐띠〉</div>'
        with patch.object(fortune.requests, "get", return_value=Mock(text=html)):
            with self.assertRaises(ValueError):
                fortune.fetch_document_text(1, "오늘의 운세, 11월 24일", NOW)


if __name__ == "__main__":
    unittest.main()
