import copy
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import TestCase
from unittest.mock import Mock

from kospi_quote import (KST, PRIMARY_URL, FALLBACK_URL, UNAVAILABLE,
                         parse_quote, fetch_quote, format_quote, indicator_issues)

NOW = datetime(2026, 11, 14, 16, 10, tzinfo=KST)
PAYLOAD = {'itemCode': 'KOSPI', 'closePrice': '5,290.53', 'marketStatus': 'CLOSE',
           'localTradedAt': '2026-11-13T20:15:00+09:00',
           'stockExchangeType': {'zoneId': 'Asia/Seoul'}}


class KospiTests(TestCase):
    def test_real_quote_date_is_not_response_date(self):
        payload = {'time': '20261114160613', 'datas': [PAYLOAD]}
        quote = parse_quote(payload, NOW)
        self.assertEqual(quote.value, Decimal('5290.53'))
        text = format_quote(quote, NOW)
        self.assertIn('2026-11-13 종가', text)
        self.assertIn('네이버 표시 20:15 KST', text)
        self.assertIn('주말 휴장', text)
        self.assertNotIn('2026-11-14', text)

    def test_polling_raw_value_and_exchange_shape(self):
        record = copy.deepcopy(PAYLOAD)
        record['closePriceRaw'] = '5290.53'
        record['exchange'] = record.pop('stockExchangeType')
        self.assertEqual(parse_quote({'datas': [record]}, NOW).value, Decimal('5290.53'))

    def test_wrong_symbol_missing_clock_and_bad_value_rejected(self):
        for key, bad in [('itemCode', 'KOSDAQ'), ('localTradedAt', None),
                         ('localTradedAt', '2026-11-13'), ('closePrice', '0'),
                         ('closePrice', 'NaN'), ('closePrice', True),
                         ('closePrice', '-5290.53'), ('closePrice', '5,2,90.53'),
                         ('marketStatus', 'UNKNOWN')]:
            with self.subTest(key=key, bad=bad):
                payload = copy.deepcopy(PAYLOAD); payload[key] = bad
                with self.assertRaises(ValueError):
                    parse_quote(payload, NOW)

    def test_future_or_unusually_old_quote_rejected(self):
        for stamp in (NOW+timedelta(minutes=1), NOW-timedelta(days=8),
                      NOW-timedelta(hours=1)):
            payload = copy.deepcopy(PAYLOAD); payload['localTradedAt'] = stamp.isoformat()
            with self.assertRaises(ValueError):
                parse_quote(payload, NOW)

    def test_intraday_quote_requires_recent_same_day_source(self):
        now = NOW.replace(day=13, hour=14)
        payload = copy.deepcopy(PAYLOAD)
        payload.update(marketStatus='OPEN', localTradedAt=(now-timedelta(minutes=5)).isoformat())
        self.assertIn('장중', format_quote(parse_quote(payload, now), now))
        payload['localTradedAt'] = (now-timedelta(hours=1)).isoformat()
        with self.assertRaises(ValueError):
            parse_quote(payload, now)

    def test_closed_weekday_does_not_invent_a_holiday(self):
        text = format_quote(parse_quote(PAYLOAD, NOW.replace(day=16)), NOW.replace(day=16))
        self.assertIn('2026-11-13 종가', text)
        self.assertNotIn('휴장', text)

    def test_bounded_fallback_after_primary_error(self):
        response = Mock(); response.json.return_value = {'datas': [PAYLOAD]}
        getter = Mock(side_effect=[OSError('timeout'), response])
        self.assertEqual(fetch_quote(getter, NOW).value, Decimal('5290.53'))
        self.assertEqual([c.args[0] for c in getter.call_args_list], [PRIMARY_URL, FALLBACK_URL])
        self.assertTrue(all(c.kwargs['timeout'] == 8 for c in getter.call_args_list))

    def test_failure_is_visible_not_a_zero_or_silent_omission(self):
        getter = Mock(side_effect=OSError('unavailable'))
        self.assertIsNone(fetch_quote(getter, NOW))
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(format_quote(None, NOW), UNAVAILABLE)
        self.assertEqual(indicator_issues('  - 코스피 : '+UNAVAILABLE), [])

    def test_indicator_requires_one_dated_quote(self):
        good = '  - 코스피 : '+format_quote(parse_quote(PAYLOAD, NOW), NOW)
        self.assertEqual(indicator_issues(good, now=NOW), [])
        for bad in ('', '  - 코스피 : 5290.53', good+'\n'+good):
            self.assertTrue(indicator_issues(bad, now=NOW))

    def test_rendered_indicator_rejects_invalid_and_stale_values(self):
        good = '  - 코스피 : '+format_quote(parse_quote(PAYLOAD, NOW), NOW)
        for bad in (good.replace('5,290.53', '0.00'),
                    good.replace('5,290.53', '5,2,90.53'),
                    good.replace('2026-11-13', '2026-99-99'),
                    good.replace('20:15', '99:99'),
                    good.replace('2026-11-13', '2000-11-13'),
                    good.replace('2026-11-13', '2999-11-13')):
            with self.subTest(body=bad):
                self.assertTrue(indicator_issues(bad, now=NOW))
