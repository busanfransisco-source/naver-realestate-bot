from datetime import date, datetime, timedelta, timezone
import unittest
from unittest import mock

import daily_data_card_sources as cards


class DailyDataCardSourceTests(unittest.TestCase):
    def test_seoul_share_digest_coverage_freshness_and_no_sales_ranking(self):
        now = datetime(2026, 10, 2, 17, 0)
        rows = [{'area': f'장소{i:02d}', 'observed_at_kst': now-timedelta(minutes=20),
                 'relative_level': '바쁜', 'industries': [{'industry': '커피', 'relative_level': '분주한'}]}
                for i in range(82)]
        rows[-1]['area'] = '오래된장소'
        rows[-1]['observed_at_kst'] = now-timedelta(hours=2)
        digest = cards.build_seoul_commerce_digest(rows, now_kst=now)
        self.assertIn('확보된 81곳 중 81곳', digest)
        self.assertIn('지연된 1곳·수집 실패 0곳은 제외', digest)
        self.assertIn('— 커피', digest)
        self.assertNotIn('오래된장소', digest)
        self.assertNotIn('매출액 순위가 아닙니다', digest)
        self.assertNotIn('신한카드 내국인', digest)
        self.assertIn('전체 82곳 중 81곳', digest)
        self.assertIn('바쁨·분주 비중은 100.0%', digest)
        for removed in ('비중의 분모', '전일 비중과 바로 비교하지 않습니다', '출처:', 'https://data.seoul.go.kr'):
            self.assertNotIn(removed, digest)
        self.assertIn('📍 서울 주요 상권 실시간', digest)
        self.assertIn('\n\n💡 이렇게 읽으세요\n\n', digest)
        self.assertEqual(digest, cards.build_seoul_commerce_digest(list(reversed(rows)), now_kst=now))
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_seoul_commerce_digest(rows[:61], now_kst=now)
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_seoul_commerce_digest(rows + [rows[0]], now_kst=now)
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_seoul_commerce_digest(rows, now_kst=now+timedelta(hours=1))

    def test_seoul_accepts_twenty_five_minute_source_but_excludes_over_thirty(self):
        now = datetime(2026, 10, 3, 18, 15)
        rows = [{'area': f'장소{i:02d}', 'observed_at_kst': now-timedelta(minutes=10),
                 'relative_level': '보통', 'industries': []} for i in range(82)]
        for row in rows[62:]:
            row['observed_at_kst'] = now-timedelta(minutes=25)
        digest = cards.build_seoul_commerce_digest(rows, now_kst=now)
        self.assertIn('확보된 82곳', digest)
        self.assertIn('17:50~18:05', digest)
        self.assertIn('조회 시점 기준 최근 30분 자료 반영', digest)
        for row in rows[61:]:
            row['observed_at_kst'] = now-timedelta(minutes=31)
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_seoul_commerce_digest(rows, now_kst=now)

    def test_seoul_catalogue_contains_exactly_82_unique_codes(self):
        self.assertEqual(len(cards.SEOUL_COMMERCE_CODES), 82)
        self.assertEqual(len(set(cards.SEOUL_COMMERCE_CODES)), 82)
        self.assertIn('POI122', cards.SEOUL_COMMERCE_CODES)
        self.assertNotIn('POI008', cards.SEOUL_COMMERCE_CODES)

    def test_seoul_emoji_groups_preserve_mixed_source_clocks_and_metadata(self):
        from production_data_cards import card_metadata
        now = datetime(2026, 10, 3, 18, 15)
        rows = [{'area': f'장소{i:02d}', 'observed_at_kst': now-timedelta(minutes=10),
                 'relative_level': '보통', 'industries': []} for i in range(82)]
        rows[0].update(relative_level='분주한', observed_at_kst=now-timedelta(minutes=20))
        rows[1].update(relative_level='바쁜', industries=[{'industry': '커피', 'relative_level': '바쁜'}])
        digest = cards.build_seoul_commerce_digest(rows, now_kst=now)
        self.assertIn('🔴 분주\n• 장소00 (17:55)', digest)
        self.assertIn('🟠 바쁨\n• 장소01 (18:05)', digest)
        self.assertNotIn('2곳의 원자료 기준시각은 모두', digest)
        metadata = card_metadata('seoulcommerce', digest)
        self.assertTrue(metadata['ready'])
        self.assertEqual(metadata['sourceWindow'], '2026-10-03 17:55~18:05')

    PAGE = ('<h3>실시간 전력수급현황</h3><p class="info_top">2026.10.01(목) 23:40 <a>새로고침</a></p>'
            '<table><tr><th>공급능력</th><td id="avil">98,448 MW</td></tr>'
            '<tr><th>현재수요(전력시장)</th><td id="load">61,991 MW</td></tr>'
            '<tr><th>공급예비력</th><td id="supPow">36,457 MW</td></tr>'
            '<tr><th>공급예비율</th><td id="supPer">58.81 %</td></tr></table><h4>실시간 전력수급 그래프</h4>')

    def test_kpx_official_page_actuals_and_units(self):
        actual = cards.parse_kpx_supply_page(self.PAGE)
        self.assertEqual(actual['observed_at_kst'], datetime(2026, 10, 1, 23, 40))
        self.assertEqual(actual['demand_mw'], 61991)
        self.assertEqual(actual['source_route'], 'official_web')
        self.assertEqual(actual['demand_scope'], '전력시장')
        self.assertEqual(cards.parse_kpx_supply_page(self.PAGE + '<p class="info_top">다른 차트 시각</p>'), actual)

    def test_kpx_official_page_rejects_missing_or_contradictory_values(self):
        for page in (self.PAGE.replace('id="load"', 'id="changed"'),
                     self.PAGE.replace('98,448', '50,000'),
                     self.PAGE.replace('58.81', '5.81'),
                     self.PAGE.replace(' MW', ' kW'),
                     self.PAGE.replace('2026.10.01', '2026.13.01'),
                     self.PAGE.replace('<h4>', '<td id="load">61,991 MW</td><h4>')):
            with self.subTest(page=page), self.assertRaises(cards.SourceUnavailable):
                cards.parse_kpx_supply_page(page)

    def test_kpx_card_fallback_and_stale_page_gate(self):
        prices = [{'date_kst': date(2026, 10, 1), 'hour_ending': hour,
                   'area': '육지', 'smp_krw_per_kwh': 100,
                   'mainland_forecast_mw': 60000} for hour in range(1, 25)]
        for api_error in (cards.SourceUnavailable('코드 30'), cards.requests.ConnectTimeout()):
            with mock.patch.object(cards, 'fetch_kpx_supply', side_effect=api_error), \
                 mock.patch.object(cards, 'fetch_kpx_supply_page', return_value=cards.parse_kpx_supply_page(self.PAGE)), \
                 mock.patch.object(cards, 'fetch_kpx_prices', return_value=prices):
                digest = cards.fetch_kpx_digest(mock.Mock(), 'test-key', now_kst=datetime(2026, 10, 1, 23, 45))
                self.assertIn('수급 수집경로: 전력거래소 공식 홈페이지', digest)
                self.assertIn('전력수요 (전력시장) 61,991MW', digest)
                with self.assertRaisesRegex(cards.SourceUnavailable, '20분'):
                    cards.fetch_kpx_digest(mock.Mock(), 'test-key', now_kst=datetime(2026, 10, 1, 23, 59) + timedelta(minutes=5))

    def test_kpx_supply_uses_official_case_sensitive_key_parameter(self):
        response = mock.Mock()
        response.text = ("<response><header><resultCode>30</resultCode>"
                         "</header></response>")
        session = mock.Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(cards.SourceUnavailable, "코드 30"):
            cards.fetch_kpx_supply(session, "test-only-key")
        session.get.assert_called_once_with(
            cards.KPX_SUPPLY_URL,
            params={"ServiceKey": "test-only-key"}, timeout=25,
        )

    def test_seoul_sample_shape_requires_matching_area_and_source_time(self):
        payload = {
            "RESULT": {"resultCode": "INFO-000"},
            "AREA_NM": "광화문·덕수궁",
            "LIVE_CMRCL_STTS": {
                "CMRCL_TIME": "20261001 1940",
                "AREA_CMRCL_LVL": "바쁜",
                "AREA_SH_PAYMENT_CNT": "163",
            },
        }
        parsed = cards.parse_seoul_commerce_payload(payload, "광화문·덕수궁")
        self.assertEqual(parsed["relative_level"], "바쁜")
        self.assertEqual(parsed["observed_at_kst"], datetime(2026, 10, 1, 19, 40))
        self.assertEqual(parsed["shinhan_payment_count"], 163)
        with self.assertRaises(cards.SourceUnavailable):
            cards.parse_seoul_commerce_payload(payload, "홍대입구역")

    def test_crypto_uses_source_date_and_30_day_range(self):
        newest = date(2026, 10, 1)
        rows = [
            {
                "timestamp": str(int(datetime.combine(
                    newest - timedelta(days=offset),
                    datetime.min.time(), timezone.utc
                ).timestamp())),
                "value": str(74 - offset),
                "value_classification": "Greed",
            }
            for offset in range(31)
        ]
        response = mock.Mock()
        response.json.return_value = {"metadata": {"error": None}, "data": rows}
        session = mock.Mock()
        session.get.return_value = response
        digest = cards.build_crypto_digest(cards.fetch_crypto_history(session))
        self.assertIn("원자료 기준일: 2026-10-01 (UTC)", digest)
        self.assertIn("74/100", digest)
        self.assertIn("전일 73점 대비 +1점", digest)
        self.assertIn("7일 전 67점 대비 +7점", digest)
        self.assertIn("최근 7일 평균 71.0점", digest)
        self.assertIn("직전 7일 평균 64.0점", digest)
        self.assertIn("최근 30일 평균 59.5점 · 최저 45점 / 최고 74점", digest)
        self.assertIn("현재 위치: 최저~최고 구간의 100% 지점", digest)
        self.assertIn("가격 전망·매수 신호가 아닙니다", digest)
        self.assertTrue(digest.startswith('🪙 비트코인 공포·탐욕 지수'))
        self.assertIn('\n\n📊 최근 흐름\n\n', digest)
        self.assertNotIn('https://alternative.me/', digest)
        self.assertTrue(digest.endswith('매수 신호가 아닙니다.'))
        session.get.assert_called_once_with(
            cards.CRYPTO_URL,
            params={"limit": 31, "format": "json"},
            headers=None,
            timeout=25,
        )

    def test_crypto_rejects_missing_calendar_day(self):
        newest = date(2026, 10, 1)
        rows = [
            (newest - timedelta(days=offset), 50, "Fear")
            for offset in range(30) if offset != 2
        ]
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_crypto_digest(rows)

    def test_crypto_ties_flat_and_transition_are_explicit(self):
        newest = date(2026, 10, 3)
        flat = [(newest-timedelta(days=i), 50, 'Neutral') for i in range(30)]
        digest = cards.build_crypto_digest(flat)
        self.assertIn('30일간 같은 점수', digest)
        self.assertIn('낮은 날 0일\n• 같은 날 30일\n• 높은 날 0일', digest)
        self.assertIn("'중립' 분류가 최소 30일 연속", digest)
        mixed = [(newest, 50, 'Neutral')] + [
            (newest-timedelta(days=i), 49 if i % 2 else 50, 'Fear')
            for i in range(1, 30)]
        digest = cards.build_crypto_digest(mixed)
        self.assertIn('낮은 날 15일\n• 같은 날 15일\n• 높은 날 0일', digest)
        self.assertIn("'중립' 분류가 1일 연속", digest)
        self.assertIn("전일 '공포'에서 분류가 바뀌었습니다", digest)
        broken = flat.copy()
        broken[20] = (newest-timedelta(days=21), 50, 'Neutral')
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_crypto_digest(broken)

    def test_kpx_supply_xml_keeps_actual_time_and_units(self):
        xml = ("<response><header><resultCode>00</resultCode></header><body><items><item>"
               "<baseDatetime>20261001203500</baseDatetime><currPwrTot>63213.2</currPwrTot>"
               "<suppAbility>82238.0</suppAbility><suppReserveRate>30.096</suppReserveRate>"
               "</item></items></body></response>")
        actual = cards.parse_kpx_supply_xml(xml)
        self.assertEqual(actual["observed_at_kst"], datetime(2026, 10, 1, 20, 35))
        self.assertEqual(actual["demand_mw"], 63213.2)
        self.assertAlmostEqual(actual["reserve_rate_pct"], 30.096)
        with self.assertRaises(cards.SourceUnavailable):
            cards.parse_kpx_supply_xml(xml.replace("00</resultCode>", "20</resultCode>"))

    def test_kpx_price_requires_full_page_and_24_hours(self):
        rows = [
            {"date": "20261002", "hour": str(hour), "areaName": "육지",
             "smp": str(90 + hour), "mlfd": str(60000 + hour * 100)}
            for hour in range(1, 25)
        ]
        payload = {"header": {"resultCode": "00"},
                   "body": {"totalCount": "24", "items": {"item": rows}}}
        prices = cards.parse_kpx_price_json({"response": payload})
        actual = {"observed_at_kst": datetime(2026, 10, 1, 20, 35),
                  "demand_mw": 63213.2, "capacity_mw": 82238.0,
                  "reserve_rate_pct": 30.096}
        digest = cards.build_kpx_digest(
            actual, prices, today=date(2026, 10, 1),
            now_kst=datetime(2026, 10, 1, 20, 40),
        )
        self.assertIn("실측: 2026-10-01 20:35", digest)
        self.assertIn("계획 대상일: 2026-10-02", digest)
        self.assertIn("예측 최대수요 62,400MW", digest)
        self.assertIn("도매시장 가격", digest)
        with self.assertRaises(cards.SourceUnavailable):
            cards.parse_kpx_price_json({**payload, "body": {**payload["body"], "totalCount": "48"}})
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_kpx_digest(
                actual, prices[:-1], today=date(2026, 10, 1),
                now_kst=datetime(2026, 10, 1, 20, 40),
            )

    def test_wikimedia_uses_common_utc_day_and_minimum_sample(self):
        newest = date(2026, 9, 30)
        days = [newest - timedelta(days=offset) for offset in range(14)]
        histories = {
            "금리": {
                day: (180 if offset < 7 else 100)
                for offset, day in enumerate(days)
            },
            "부동산": {day: 2 for day in days},
        }
        digest = cards.build_wikimedia_digest(histories)
        self.assertIn("2026-09-30 (UTC)", digest)
        self.assertIn("금리 1,260회 (직전 7일 700회, +80%)", digest)
        self.assertIn("조회 증가 1개 · 감소 0개 · 보합 1개 문서", digest)
        self.assertIn("이번 주 읽기 흐름", digest)
        self.assertNotIn("선정 문서만 본 작은 표본", digest)
        self.assertTrue(digest.startswith('📚 경제 주제 읽기 관심도'))
        self.assertIn('\n\n📈 조회 증가가 두드러진 문서\n\n', digest)
        self.assertTrue(digest.endswith('직전 7일 50회 이상'))
        self.assertNotIn('https://doc.wikimedia.org', digest)
        self.assertNotIn("부동산 14회", digest)
        self.assertIn("문서 조회수", digest)

    def test_wikimedia_requires_common_complete_days(self):
        newest = date(2026, 9, 30)
        histories = {
            "금리": {newest - timedelta(days=i): 100 for i in range(14)},
            "부동산": {newest - timedelta(days=i): 100 for i in range(13)},
        }
        with self.assertRaises(cards.SourceUnavailable):
            cards.build_wikimedia_digest(histories)

    def test_wikimedia_distinguishes_growth_rate_absolute_and_low_base(self):
        newest = date(2026, 10, 2)
        pairs = {'부동산': (20, 10), '코스피': (200, 150),
                 '기준금리': (1, 0), '환율': (100, 200)}
        histories = {title: {newest-timedelta(days=i): pair[0 if i < 7 else 1]
                            for i in range(14)} for title, pair in pairs.items()}
        digest = cards.build_wikimedia_digest(histories)
        self.assertIn("조회 증가율이 가장 큰 문서는 '부동산'", digest)
        self.assertIn('조회 증가 횟수가 가장 큰 문서: 코스피 +350회 (1,050→1,400회)', digest)
        self.assertIn('증가율 순위 비교 대상 3/4개 문서', digest)
        self.assertNotIn('1. 기준금리', digest)
        self.assertIn('한 문서의 급증을 경제 전반의 관심 증가로 확대하지', digest)
        self.assertIn('적용 대상·시점·예외', digest)

    def test_wikimedia_flat_and_zero_denominator_never_invent_growth(self):
        newest = date(2026, 10, 2)
        histories = {'부동산': {newest-timedelta(days=i): 20 for i in range(14)},
                     '기준금리': {newest-timedelta(days=i): 0 for i in range(14)}}
        digest = cards.build_wikimedia_digest(histories)
        self.assertIn('선정 문서 전체 증감 +0회', digest)
        self.assertIn('전주 비교 불가', digest)
        self.assertIn('주제별 합계가 보합', digest)
        self.assertNotIn('조회 증가 횟수가 가장 큰 문서:', digest)

    def test_wikimedia_growth_ties_and_new_readers_keep_distinct_lists(self):
        newest = date(2026, 10, 2)
        pairs = {'부동산': (20, 10), '코스피': (40, 20), '환율': (500, 0)}
        histories = {title: {newest-timedelta(days=i): pair[0 if i < 7 else 1]
                            for i in range(14)} for title, pair in pairs.items()}
        digest = cards.build_wikimedia_digest(histories)
        self.assertIn('증가율 공동 1위: 부동산 · 코스피', digest)
        self.assertIn('가장 많이 읽힌 문서\n\n1. 환율 3,500회', digest)
        self.assertIn('증가율 순위 비교 대상 2/3개 문서', digest)

    def test_wikimedia_request_identifies_client_and_article(self):
        response = mock.Mock()
        response.json.return_value = {
            "items": [{"timestamp": "2026093000", "views": 180, "article": "한국은행"}]
        }
        session = mock.Mock()
        session.get.return_value = response
        result = cards.fetch_wikimedia_history(
            session, "한국은행", date(2026, 9, 30), date(2026, 9, 30)
        )
        self.assertEqual(result[date(2026, 9, 30)], 180)
        args, kwargs = session.get.call_args
        self.assertIn("ko.wikipedia.org", args[0])
        self.assertEqual(kwargs["headers"]["User-Agent"], cards.WIKIMEDIA_USER_AGENT)


if __name__ == "__main__":
    unittest.main()
