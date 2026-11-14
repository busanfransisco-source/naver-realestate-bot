import html
import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from bs4 import BeautifulSoup
import daum_news_fetch as news
import gen_briefing
from quicknews_sources import MISSING, source_line, source_issues, render_preview

URL = 'https://v.daum.net/v/20261114143305220'
SUMMARY = '정부가 올해 주택 공급 계획의 세부 추진 일정을 공개했습니다.'


class SourceTests(TestCase):
    def test_only_observed_canonical_article_url_accepted(self):
        self.assertEqual(source_line(URL), URL)
        for bad in (None, '', 'javascript:alert(1)', URL+'?affiliate=ad',
                    URL+'\n광고', 'https://v.daum.net.evil/v/20261114143305220'):
            self.assertEqual(source_line(bad), MISSING)

    def test_source_sits_immediately_below_each_article(self):
        body = '🔥 (톱뉴스) '+SUMMARY+'\n'+source_line(URL)
        self.assertEqual(source_issues(body), [])
        self.assertEqual(source_issues(body.replace(source_line(URL), MISSING)), [])
        self.assertTrue(source_issues('🔥 (톱뉴스) '+SUMMARY))

    def test_html_is_safe_and_plain_text_stays_identical(self):
        body = '🔥 (톱뉴스) '+SUMMARY+'\n'+source_line(URL)+'\n\n<script>alert(1)</script>'
        soup = BeautifulSoup(render_preview(body), 'html.parser')
        self.assertEqual(soup.get_text(), body)
        self.assertIsNone(soup.script)
        self.assertEqual(soup.a['href'], URL)
        self.assertEqual(soup.a.get_text(), URL)
        self.assertIn('noopener', soup.a['rel'])
        self.assertEqual(len(soup.find_all('a')), 1)

    def test_missing_source_is_not_a_made_up_link(self):
        soup = BeautifulSoup(render_preview('🔥 (톱뉴스) '+SUMMARY+'\n'+MISSING), 'html.parser')
        self.assertIsNone(soup.a)
        self.assertIn(MISSING, soup.get_text())

    def test_duplicate_guard_accepts_source_preserving_items(self):
        self.assertTrue(news.duplicate_summary(SUMMARY, [('🔥', '톱뉴스', SUMMARY, URL)]))

    def test_collect_preserves_url_from_the_article_anchor(self):
        home = f'<a href="{URL}"><strong>정부 주택 공급 세부 추진 일정 공개</strong></a>'
        with patch.object(news, 'get') as getter, patch.object(news, 'SECTIONS', []), patch.object(news, 'recent_article', return_value=True), patch.object(news, 'article_summary', return_value=SUMMARY):
            getter.return_value.text = home
            result = news.collect_news()
        self.assertEqual(result, [('🔥', '톱뉴스', SUMMARY, URL)])

    def test_main_writes_source_under_summary_without_ads(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = os.getcwd(); os.chdir(tmp)
            try:
                with patch.object(news, 'collect_news', return_value=[('🔥', '톱뉴스', SUMMARY, URL)]), patch.object(news, 'todays_quote', return_value=None), patch.object(news, 'get_indicators', return_value=[]):
                    news.main()
                body = Path('shortnews.txt').read_text()
                self.assertIn(SUMMARY+'\n'+URL+'\n', body)
                self.assertNotIn('원문:', body)
                self.assertNotIn('광고', body)
            finally:
                os.chdir(before)

    def test_rendered_card_keeps_copy_and_visible_text_in_sync(self):
        body = '🔥 (톱뉴스) '+SUMMARY+'\n'+source_line(URL)
        original = gen_briefing.read_section_text
        with patch.object(gen_briefing, 'read_section_text', side_effect=lambda key, day: body if key == 'shortnews' else original(key, day)):
            page = gen_briefing.build_html()
        soup = BeautifulSoup(page, 'html.parser')
        self.assertEqual(soup.select_one('#ta-shortnews').get_text(), body)
        self.assertEqual(soup.select_one('#preview-shortnews').get_text(), body)
        self.assertEqual(soup.select_one('#preview-shortnews a')['href'], URL)
        self.assertEqual(len(soup.select('#ta-shortnews')), 1)
        self.assertIn('ta.style.cssText = previousStyle', page)
