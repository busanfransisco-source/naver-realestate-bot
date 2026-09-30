import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from gen_briefing import analysis_date, is_fresh_analysis, read_policy_text
from validate_policy import validate


class PolicyTests(unittest.TestCase):
    def test_blank_lines_and_invalid_date(self):
        self.assertTrue(is_fresh_analysis('제목\n\n2026년 9월 12일 토요일', datetime(2026, 9, 12)))
        self.assertIsNone(analysis_date('제목\n2026-99-99'))
        self.assertFalse(is_fresh_analysis('제목\n2026-09-05', datetime(2026, 9, 12)))

    def test_four_articles_fail_then_six_pass_and_fallback_is_dated(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                for n in range(1, 7):
                    day = '12' if n <= 4 else '05'
                    Path(f'analysis{n}-sat.txt').write_text(f'제목\n2026-09-{day}\nhttps://example.com\n' + '분석입니다. ' * 60, encoding='utf-8')
                self.assertEqual(len(validate(datetime(2026, 9, 12))), 2)
                self.assertTrue(read_policy_text('analysis5', datetime(2026, 9, 12)).startswith('[최근 분석 · 원문 작성일 2026-09-05]'))
                for n in (5, 6):
                    path = Path(f'analysis{n}-sat.txt')
                    path.write_text(path.read_text(encoding='utf-8').replace('2026-09-05', '2026-09-12'), encoding='utf-8')
                self.assertEqual(validate(datetime(2026, 9, 12)), [])
                self.assertFalse(read_policy_text('analysis5', datetime(2026, 9, 12)).startswith('[최근 분석'))
                self.assertEqual(len(validate(datetime(2026, 9, 12), '<html></html>')), 6)
            finally:
                os.chdir(previous)
