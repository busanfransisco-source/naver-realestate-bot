import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import yes24_books as books
import gen_briefing
from briefing_health import inspect


def fixture(count=10, week='10월 05일 ~ 10월 11일', year=2026):
    rows = ''.join(
        f'<li data-goods-no="{100+i}"><div class="img_upper">'
        f'<em class="ico rank">{i}</em></div><a class="gd_name" '
        f'href="/product/goods/{100+i}">제목 {i} &amp; 책</a></li>'
        for i in range(1, count+1)
    )
    return (f'<select id="scope_year"><option value="{year}" selected>{year}년</option></select>'
            f'<select id="scope_week"><option selected>{week}</option>'
            '<option>09월 28일 ~ 10월 04일</option></select>'
            '<div id="divTitle"><h3><u class="cate">국내도서</u> 주별 베스트</h3></div>'
            f'<ul id="yesBestList">{rows}</ul>'
            '<a class="gd_name">광고: 순위에 포함하면 안 됩니다</a>')


class Yes24BooksTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 12, tzinfo=books.KST)
        self.ranking = books.parse_ranking(fixture(), self.now.date())

    def test_parse_source_week_and_exact_order_not_advertisements(self):
        self.assertEqual(self.ranking['start'], date(2026, 10, 5))
        self.assertEqual(self.ranking['end'], date(2026, 10, 11))
        self.assertEqual(self.ranking['books'], [f'제목 {i} & 책' for i in range(1, 11)])

    def test_incomplete_or_repeated_ranks_rejected(self):
        for html in (fixture(9), fixture().replace('>5</em>', '>4</em>')):
            with self.assertRaises(ValueError):
                books.parse_ranking(html, self.now.date())

    def test_duplicate_product_or_missing_title_rejected(self):
        for html in (fixture().replace('data-goods-no="105"', 'data-goods-no="104"'),
                     fixture().replace('제목 5 &amp; 책', ''),
                     fixture().replace('/product/goods/105', '/product/goods/999')):
            with self.assertRaises(ValueError):
                books.parse_ranking(html, self.now.date())

    def test_missing_period_and_wrong_category_rejected(self):
        for html in (fixture().replace('id="scope_week"', 'id="other"'),
                     fixture().replace('국내도서', '외국도서'),
                     fixture().replace('주별 베스트', '일별 베스트')):
            with self.assertRaises(ValueError):
                books.parse_ranking(html, self.now.date())

    def test_future_stale_and_not_seven_day_periods_rejected(self):
        for week in ('10월 12일 ~ 10월 18일', '09월 28일 ~ 10월 04일',
                     '10월 06일 ~ 10월 11일'):
            with self.assertRaises(ValueError):
                books.parse_ranking(fixture(week=week), self.now.date())

    def test_cross_year_week(self):
        data = books.parse_ranking(fixture(week='12월 28일 ~ 01월 03일', year=2027),
                                   date(2027, 1, 4))
        self.assertEqual(data['start'], date(2026, 12, 28))
        self.assertEqual(data['end'], date(2027, 1, 3))

    def test_utf8_and_source_url(self):
        response = Mock(text=fixture())
        with patch.object(books.requests, 'get', return_value=response) as fetch:
            data = books.collect(self.now.date())
        self.assertEqual(response.encoding, 'utf-8')
        self.assertEqual(fetch.call_args.args[0], books.URL)
        self.assertEqual(data, self.ranking)

    def test_render_collection_day_is_not_week_date(self):
        text = books.render(self.ranking, self.now)
        self.assertTrue(text.startswith('26년 10월 13일 화요일 주간 베스트셀러'))
        self.assertIn('집계 기간: 2026-10-05 ~ 2026-10-11', text)
        self.assertIn('온라인·매장', text)
        self.assertNotIn('http', text)
        self.assertIn('출처: YES24 주간 베스트', text)
        self.assertEqual(books.digest_info(text),
                         (self.now.date(), self.ranking['start'], self.ranking['end']))

    def test_refresh_writes_current_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertTrue(books.refresh(self.now, lambda today: self.ranking, directory))
            self.assertEqual((directory / 'books.txt').read_bytes(),
                             (directory / 'books-tue.txt').read_bytes())
            self.assertFalse((directory / 'books-mon.txt').exists())

    def test_failure_preserves_bytes_and_never_relabels_old_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            old = books.render(self.ranking, self.now - books.timedelta(days=1))
            for name in ('books.txt', 'books-tue.txt'):
                (directory / name).write_text(old, encoding='utf-8')
            self.assertFalse(books.refresh(self.now, Mock(side_effect=RuntimeError('timeout')), directory))
            self.assertEqual((directory / 'books.txt').read_text(encoding='utf-8'), old)
            self.assertEqual((directory / 'books-tue.txt').read_text(encoding='utf-8'), old)
            self.assertTrue(books.load_digest(directory, self.now.date()).startswith('26년 10월 12일'))

    def test_newest_yes24_file_precedes_legacy_weekday_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'books-wed.txt').write_text('알라딘 이전 목록', encoding='utf-8')
            current = books.render(self.ranking, self.now)
            (directory / 'books.txt').write_text(current, encoding='utf-8')
            self.assertEqual(books.load_digest(directory, date(2026, 10, 14)), current.strip())
            with patch('yes24_books.load_digest', return_value=current.strip()) as load:
                self.assertEqual(gen_briefing.read_section_text('books', 'wed'), current.strip())
                load.assert_called_once()

    def test_legacy_or_broken_digest_not_rebranded_as_yes24(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'books.txt').write_text('알라딘\n' + '\n'.join(f'{i}. 책' for i in range(1, 11)), encoding='utf-8')
            self.assertIn('가져오지 못했습니다', books.load_digest(directory, self.now.date()))
        self.assertIsNone(books.digest_info(books.render(self.ranking, self.now).replace('10. ', '11. ')))

    def test_cached_footer_link_is_removed_without_changing_dates_or_ranks(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            current = books.render(self.ranking, self.now).strip()
            (directory / 'books.txt').write_text(current + '\n' + books.URL, encoding='utf-8')
            self.assertEqual(books.load_digest(directory, self.now.date()), current)

    def test_health_gate_checks_source_and_stale_week(self):
        from test_briefing_health import HealthTests
        page = HealthTests().page()
        begin = page.index('id="ta-books">') + len('id="ta-books">')
        end = page.index('</textarea>', begin)
        text = books.render(self.ranking, self.now)
        page = page[:begin] + text + page[end:]
        row = next(r for r in inspect(page, self.now) if r['key'] == 'books')
        self.assertEqual(row['status'], 'ok')
        row = next(r for r in inspect(page, self.now + books.timedelta(days=8)) if r['key'] == 'books')
        self.assertIn('YES24 source week is stale', row['issues'])


if __name__ == '__main__':
    unittest.main()
