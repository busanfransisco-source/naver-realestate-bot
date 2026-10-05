import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import requests
import gen_briefing
import neonet_trend as trend


def fixture():
    rows = ''.join(f'<tr><td>{region}</td><td>0.05% 상승 (▲)</td><td>0.03% 하락 (▼)</td></tr>'
                   for region in trend.REGIONS)
    return ('<div class="dl_box">전국 아파트 3.3㎡당 매매가격 1,884만 원 (전주대비 0.11% 상승) '
            '3.3㎡당 전세가격 1,055만 원 (전주대비 0.09% 상승)</div>'
            '<table><tr><th>전주 대비 매매가격 변동률</th><th>전주 대비 전세가격 변동률</th></tr>'
            + rows + '</table><table><tr><td>서울특별시</td><td>5,104</td><td>5,107</td></tr></table>')


class NeonetTrendTests(unittest.TestCase):
    def test_published_rates_not_rounded_price_recalculation(self):
        data = trend.parse_page(fixture())
        self.assertEqual(data['national']['sale'], '0.11')
        self.assertEqual(data['national']['salePrice'], 1884)
        self.assertEqual(data['regions'][0]['sale'], '0.05')
        self.assertEqual(data['regions'][0]['jeonse'], '-0.03')
        self.assertEqual(len(data['regions']), 17)

    def test_two_column_layout_long_name_and_computed_summary(self):
        saved = {'checkedAtKst': '2026-10-05T09:00:00+09:00', 'data': trend.parse_page(fixture())}
        body = trend.format_digest(saved)
        self.assertIn('서울  +0.05%   신도시  +0.05%', body)
        self.assertIn('\n전남광주통합특별시  +0.05%\n대전  +0.05%   울산  +0.05%', body)
        self.assertIn('매매 상승 17 · 하락 0 · 변동 없음 0', body)
        self.assertIn('전세 상승 0 · 하락 17 · 변동 없음 0', body)
        saved['data']['regions'][0]['sale'] = None
        self.assertIn('매매 상승 16 · 하락 0 · 변동 없음 1', trend.format_digest(saved))

    def test_dash_and_direction_checks(self):
        self.assertIsNone(trend.rate('-'))
        self.assertEqual(trend.display(None), '변동 없음')
        self.assertEqual(trend.display('0.00'), '변동 없음')
        for invalid in ('0.03% 상승 (▼)', '0.03%', '집계 대기', '101% 상승 (▲)'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                trend.rate(invalid)

    def test_missing_duplicate_blocked_and_wrong_scope_fail_closed(self):
        page = fixture()
        for broken in ('웹 페이지 요청이 과도하여 자동 차단되었습니다.',
                       page.replace('서울특별시', '알수없음'),
                       page + page, page.replace('전국 아파트', '서울 아파트')):
            with self.assertRaises(ValueError):
                trend.parse_page(broken)

    def test_failure_keeps_original_verified_source_and_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                session = Mock()
                session.get.return_value.text = fixture()
                first = trend.collect(now=datetime(2026,10,5,9,tzinfo=trend.KST), session=session)
                original = Path(trend.CACHE).read_bytes()
                session.get.side_effect = requests.ConnectTimeout()
                second = trend.collect(now=datetime(2026,10,6,9,tzinfo=trend.KST), session=session)
                self.assertEqual(first, second)
                self.assertEqual(original, Path(trend.CACHE).read_bytes())
                self.assertNotIn('조회:', second)
                self.assertEqual(json.loads(Path(trend.CACHE).read_text(encoding='utf-8'))['checkedAtKst'],
                                 '2026-10-05T09:00:00+09:00')
                self.assertNotIn('2026-10-06', second)
                self.assertIn('서울  +0.05%', second)
                self.assertIn('서울  -0.03%', second)
                self.assertIn('🏘️ 지역별 매매가 변동률', second)
                self.assertIn('🔑 지역별 전세가 변동률', second)
                for removed in ('출처:', '통계 기준일:', '부동산뱅크 ·', '※', 'https://'):
                    self.assertNotIn(removed, second)
                self.assertEqual(gen_briefing.read_section_text('trend', 'tue'), second)
            finally:
                os.chdir(previous)

    def test_no_cross_source_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path('trend.txt').write_text('한국부동산원 전국 +9.99%', encoding='utf-8')
                body = gen_briefing.read_section_text('trend', 'mon')
                self.assertIn('집계 대기', body)
                self.assertNotIn('9.99', body)
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
