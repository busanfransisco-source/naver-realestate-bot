import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

import daum_news_fetch as news


def article(*paragraphs):
    return '<div class="article_view">' + ''.join(f'<p>{text}</p>' for text in paragraphs) + '</div>'


class NewsSummaryTests(unittest.TestCase):
    def test_narrative_endings_are_formal_polite(self):
        examples = {
            '정부가 계획을 발표했다.': '정부가 계획을 발표했습니다.',
            '수요가 늘고 있다.': '수요가 늘고 있습니다.',
            '이번 조사는 첫 사례다.': '이번 조사는 첫 사례입니다.',
            '이번 조치의 목표는 안정적인 공급 확보다.': '이번 조치의 목표는 안정적인 공급 확보입니다.',
            '첫 번째 목표다.': '첫 번째 목표입니다.',
            '작년의 2배다.': '작년의 2배입니다.',
            '현재 지수는 6,163.11이다.': '현재 지수는 6,163.11입니다.',
            '조사는 이번이 처음이다.': '조사는 이번이 처음입니다.',
            '금리가 오른다.': '금리가 오릅니다.',
            '정부가 계획을 추진한다.': '정부가 계획을 추진합니다.',
            '이달부터 적용된다.': '이달부터 적용됩니다.',
            '거래량이 많다.': '거래량이 많습니다.',
            '시장에서는 거래를 주목받는다.': '시장에서는 거래를 주목받습니다.',
            '정부가 지원에 나선다.': '정부가 지원에 나섭니다.',
            '공무원이 근무지를 옮긴다.': '공무원이 근무지를 옮깁니다.',
            '새 규정은 적용하지 않는다.': '새 규정은 적용하지 않습니다.',
            '기관은 일정을 알린다.': '기관은 일정을 알립니다.',
        }
        for original, expected in examples.items():
            with self.subTest(original=original):
                self.assertEqual(news.polite_summary(original), expected)

    def test_existing_polite_endings_are_idempotent(self):
        for text in ('정부가 계획을 발표했습니다.', '주택 공급을 늘립니다.',
                     '부담이 커졌는데요.', '추가 확인이 필요할까요?'):
            self.assertEqual(news.polite_summary(text), text)

    def test_quotes_and_decimal_numbers_stay_verbatim(self):
        text = '국세청장은 "편법 증여를 철저히 조사하겠다. 원칙대로 대응하겠다"고 밝혔다. 성장률은 3.3%로 전망했다.'
        result = news.polite_summary(text)
        self.assertEqual(result, '국세청장은 "편법 증여를 철저히 조사하겠다. 원칙대로 대응하겠다"고 밝혔습니다. 성장률은 3.3%로 전망했습니다.')
        for opening, closing in (("'", "'"), ('‘', '’'), ('“', '”')):
            original = f'국세청장은 {opening}편법 증여를 조사하겠다. 원칙대로 대응하겠다{closing}고 밝혔다.'
            self.assertEqual(news.polite_summary(original), original.replace('밝혔다.', '밝혔습니다.'))

    def test_polite_conversion_respects_expanded_character_limit(self):
        first = '정부가 주택 공급 계획을 발표했다.'
        second = '사업은 다음 달부터 시작한다.'
        result = news.polite_summary(first + ' ' + second, max_chars=25)
        self.assertEqual(result, '정부가 주택 공급 계획을 발표했습니다.')
        self.assertLessEqual(len(result), 25)

    def test_article_summary_converts_extracted_lead(self):
        with patch.object(news, 'get') as get:
            get.return_value.text = article('정부가 올해 주택 공급 계획의 세부 추진 일정을 공개했다.')
            self.assertEqual(news.article_summary('https://v.daum.net/v/123'),
                             '정부가 올해 주택 공급 계획의 세부 추진 일정을 공개했습니다.')

    def test_news_body_gate_ignores_verbatim_quote_section(self):
        body = '🔥 (톱뉴스) 정부가 계획을 발표했습니다.\n\n[오늘의 명언]\n좋은 뱃사공은 잔잔한 바다에서 나오지 않는다. -속담'
        self.assertTrue(news.polite_news_body(body))
        self.assertFalse(news.polite_news_body(body.replace('발표했습니다.', '발표했다.')))
        self.assertFalse(news.polite_news_body(body + '\n👥 (사회) '))

    def test_saved_digest_keeps_date_quotes_indicators_and_blank_lines(self):
        text = '26년 10월 14일 수요일 오늘의 퀵뉴스⚡\n\n🔥 (톱뉴스) 정부가 "부담을 낮추겠다"고 밝혔다.\n\n[오늘의 명언]\n잔잔한 바다에서는 좋은 뱃사공이 만들어지지 않는다. -영국 속담\n\n[주요 경제 지표]\n  - 나스닥 : 27,204.38\n'
        self.assertEqual(news.polite_digest(text), text.replace('밝혔다.', '밝혔습니다.'))
        self.assertEqual(news.polite_digest(news.polite_digest(text)), news.polite_digest(text))

    def test_failed_style_conversion_cannot_silently_remove_a_news_item(self):
        with self.assertRaises(ValueError):
            news.polite_digest('🔥 (톱뉴스) 단어나 문장 조각뿐입니다만')

    def test_byline_is_removed_without_losing_subject(self):
        html = article('[서울=연합뉴스] 홍길동 기자 = 국세청이 부동산 편법 증여에 대한 조사를 강화하기로 했다.',
                       '임 청장은 국정감사에서 특수관계자 간 저가 거래를 살피겠다고 밝혔다.')
        result = news.summary_from_html(html)
        self.assertTrue(result.startswith('국세청이'))
        self.assertIn('임 청장은', result)
        self.assertNotIn('기자', result)

    def test_header_attached_to_lead(self):
        result = news.summary_from_html(article('[헤럴드경제=김용훈 기자]국제통화기금(IMF)이 올해 한국 성장률 전망을 3.3%로 높였다. 지난 7월보다 0.7%포인트 높인 수치다.'))
        self.assertTrue(result.startswith('국제통화기금(IMF)이'))
        self.assertIn('3.3%', result)
        self.assertIn('0.7%포인트', result)

    def test_quote_period_does_not_cut_off_attribution(self):
        text = '국세청장은 "편법 증여를 철저히 조사하겠다. 법과 원칙에 따라 대응하겠다"고 밝혔다. 주요 조사 대상은 특수관계자 간 저가 거래다.'
        sentences = news.complete_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].endswith('밝혔다.'))
        self.assertEqual(news.summary_from_html(article(text)), text)

    def test_smart_quotes_are_kept_whole(self):
        text = '시장 관계자는 “매매 수요가 늘었다. 거래량도 회복됐다”고 설명했다. 조사 결과는 다음 주 공개될 예정이다.'
        self.assertEqual(len(news.complete_sentences(text)), 2)

    def test_complete_sentences_only_no_ellipsis(self):
        first = '국세청이 부동산 편법 증여에 대한 조사를 강화하기로 했다.'
        result = news.summary_from_html(article(first + ' ' + '자세한 조사 대상과 범위는 ' * 20 + '추후 발표될 예정이다.'), max_chars=80)
        self.assertEqual(result, first)
        self.assertNotIn('…', result)

    def test_extraction_word_limit_stops_at_complete_sentence(self):
        first = '정부가 올해 주택 공급 계획의 세부 추진 일정을 공개했다.'
        second = '관련 기관은 ' + '주택 공급 계획 추진 일정을 ' * 8 + '설명했다.'
        result = news.summary_from_html(article(first + ' ' + second))
        self.assertEqual(result, first)
        self.assertLessEqual(len(result.split()), 25)

    def test_overlong_lead_is_not_cut_in_middle(self):
        self.assertEqual(news.summary_from_html(article('관련 기관은 ' * 50 + '조사에 착수했다.'), max_chars=80), '')

    def test_incomplete_tail_is_omitted(self):
        result = news.summary_from_html(article('국세청이 부동산 편법 증여에 대한 조사를 강화하기로 했다. 이어 "중점 조사 대상은'))
        self.assertEqual(result, '국세청이 부동산 편법 증여에 대한 조사를 강화하기로 했다.')

    def test_broadcast_script_is_not_a_news_summary(self):
        html = article('■ 방송 : MBC 라디오 ■ 진행 : 김종배 ☏ 진행자 > 제주에서 사건이 발생했습니다.')
        self.assertEqual(news.summary_from_html(html), '')

    def test_live_broadcast_marker_cannot_drop_the_lead(self):
        self.assertEqual(news.summary_from_html(article('[앵커] 국회로 가보겠습니다.', '오늘은 12개 상임위에서 국정감사가 진행되는데요.')), '')
        self.assertEqual(news.summary_from_html(article('◀ 앵 커 ▶ 경주시가 인구감소 관심지역에서 벗어났습니다.', '전입자 증가가 영향을 준 것으로 분석됩니다.')), '')

    def test_scene_fragment_is_not_a_complete_sentence(self):
        self.assertEqual(news.summary_from_html(article('13일 오전 국회 보건복지위원회 국정감사장.', '국민의힘 의원석에 내걸린 피켓을 시작으로 여야 의원들의 고성이 오갔다.')), '')

    def test_missing_article_container_does_not_scrape_page_chrome(self):
        self.assertEqual(news.summary_from_html('<p>메뉴와 추천 댓글이 길게 표시되지만 실제 기사 본문은 없습니다.</p>'), '')

    def test_photo_caption_not_used_as_lead(self):
        html = '<div class="article_view"><figure><p>정부 관계자가 13일 정부청사에 입장하고 있다.</p></figure><p>정부가 올해 주택 공급 계획의 세부 추진 일정을 공개했다.</p></div>'
        self.assertTrue(news.summary_from_html(html).startswith('정부가'))

    def test_orphan_subject_does_not_pass_as_lead(self):
        self.assertEqual(news.summary_from_html(article('임 청장은 국정감사에서 특수관계자 간 저가 거래를 살피겠다고 밝혔다.')), '')

    def test_div_lead_is_preserved_in_document_order(self):
        html = '<div class="article_view"><div dmcf-ptype="general">방위사업청이 내년도 방위력개선비 정부안으로 22조7225억원을 편성했다.</div><p>첨단 항공엔진 등 미래 국방기술의 자립 기반을 강화한다는 방침이다.</p></div>'
        result = news.summary_from_html(html)
        self.assertTrue(result.startswith('방위사업청이'))
        self.assertIn('방침이다.', result)

    def test_bold_subtitle_is_not_glued_to_the_lead(self):
        html = '<div class="article_view"><p><strong>통합돌봄거점, 실내놀이·긴급돌봄 등 기반시설 자율 확충</strong></p><div dmcf-ptype="general">정부가 맞춤형 저출산 대응 사업에 참여할 10개 지방자치단체를 선정했다.</div></div>'
        self.assertTrue(news.summary_from_html(html).startswith('정부가'))

    def test_opinion_intro_is_not_used_as_news(self):
        self.assertEqual(news.summary_from_html(article('지금 교육계는 서·논술형 평가를 둘러싼 논의가 한창이다.', '필자는 1987년 학력고사를 치르고 대학에 진학했다.')), '')

    def test_same_announcement_with_different_wording_is_duplicate(self):
        first = '국제통화기금(IMF)이 올해 한국 경제성장률 전망치를 3.3%로 상향했다. 지난 7월보다 0.7%포인트 높인 수치다.'
        second = '국제통화기금(IMF)이 올해 마지막으로 내놓은 전망에서 우리나라의 연간 경제성장률을 직전 대비 0.7%포인트 높은 3.3%로 올려 잡았다. 개발도상국을 포함한 전 세계 평균 성장률을 6년 만에 추월할 전망이다.'
        self.assertTrue(news.duplicate_summary(second, [('💰', '경제', first)]))

    def test_question_hook_is_not_exported_as_news(self):
        self.assertEqual(news.summary_from_html(article('“수면제를 계속 먹으면 중독되지 않을까요?” 불면증 환자들이 진료실에서 자주 던지는 질문이다.')), '')

    def test_title_does_not_include_teaser_and_publisher(self):
        anchor = BeautifulSoup('<a data-title="IMF%2C%20%EC%84%B1%EC%9E%A5%EB%A5%A0%20%EC%83%81%ED%96%A5"><strong>제목</strong><p>리드</p><span>연합뉴스 3분 전</span></a>', 'html.parser').a
        self.assertEqual(news.link_title(anchor), 'IMF, 성장률 상향')

    def test_recommended_old_article_is_rejected(self):
        now = datetime(2026, 10, 13, 11, tzinfo=news.KST)
        self.assertFalse(news.recent_article('https://v.daum.net/v/20260115120806425', now))
        self.assertTrue(news.recent_article('https://v.daum.net/v/20261013110303936', now))
        self.assertTrue(news.recent_article('https://v.daum.net/v/20261012110303936', now))
        self.assertFalse(news.recent_article('https://v.daum.net/v/20261014110303936', now))

    def test_duplicate_event_is_removed(self):
        summary = '건강보험공단은 향후 5년간 매년 수조원대 영업적자가 발생할 것으로 전망했다.'
        self.assertTrue(news.duplicate_summary(summary, [('💰', '경제', summary)]))
        self.assertFalse(news.duplicate_summary('정부가 올해 주택 공급 계획과 공공택지 조성 일정을 공개했다.', [('💰', '경제', summary)]))

    def test_daum_html_decoding_is_explicit(self):
        with patch.object(news.requests, 'get') as request:
            response = request.return_value
            news.get('https://news.daum.net/economic')
            self.assertEqual(response.encoding, 'utf-8')

    def test_non_daum_encoding_is_not_changed(self):
        with patch.object(news.requests, 'get') as request:
            response = request.return_value
            response.encoding = 'euc-kr'
            news.get('https://finance.naver.com/sise/sise_index.naver')
            self.assertEqual(response.encoding, 'euc-kr')

    def test_top_news_tries_next_candidate_instead_of_title_fallback(self):
        homepage = '<a href="https://v.daum.net/v/1234567890"><strong>불완전한 첫 번째 기사 제목입니다</strong></a><a href="https://v.daum.net/v/1234567891"><strong>완결된 두 번째 기사 제목입니다</strong></a>'
        with patch.object(news, 'get') as get, patch.object(news, 'SECTIONS', []), patch.object(news, 'article_summary', side_effect=['', '정부가 올해 주택 공급 계획과 세부 일정을 공개했다.']):
            get.return_value.text = homepage
            result = news.collect_news()
        self.assertEqual(len(result), 1)
        self.assertIn('공급 계획', result[0][2])


if __name__ == '__main__':
    unittest.main()
