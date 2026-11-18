import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import daum_news_fetch as news
import morning_cloud_prepare as cloud
from test_morning_cloud_prepare import NOW, fixture_sources, write_sources

class BudgetTests(unittest.TestCase):
    def test_expired_budget_makes_no_request(self):
        with patch.object(news, 'DEADLINE', 1), patch.object(news.time, 'monotonic', return_value=2), patch.object(news.requests, 'get') as request:
            with self.assertRaises(news.CollectionBudgetExpired):
                news.get('https://news.daum.net')
            request.assert_not_called()

    def test_remaining_budget_caps_request_timeout(self):
        with patch.object(news, 'DEADLINE', 4), patch.object(news.time, 'monotonic', return_value=2), patch.object(news.requests, 'get') as request:
            news.get('https://news.daum.net')
            self.assertEqual(request.call_args.kwargs['timeout'], 2)

    def test_http_diagnostics_do_not_include_url_or_secret(self):
        response = type('Response', (), {'status_code': 503})()
        with patch.object(news, 'DEADLINE', None), patch.object(news.requests, 'get', side_effect=news.requests.HTTPError('secret-url', response=response)):
            with self.assertRaises(news.requests.HTTPError):
                news.get('https://example.com/secret')
        self.assertIn('http_503', news.DIAGNOSTICS)
        self.assertNotIn('secret', repr(news.DIAGNOSTICS))

    def test_fetches_bounded_and_preserves_source_order(self):
        active = peak = 0
        lock = threading.Lock()
        def get(url):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.01)
            with lock: active -= 1
            return type('Response', (), {'text': url})()
        candidates = [(str(i), str(i)) for i in range(10)]
        with patch.object(news, 'DEADLINE', None), patch.object(news, 'get', side_effect=get), patch.object(news, 'summary_from_html', side_effect=lambda html:html), patch.object(news, 'polite_summary', side_effect=lambda text:text):
            rows = list(news.candidate_summaries(candidates))
        self.assertLessEqual(peak, 4)
        self.assertGreater(peak, 1)
        self.assertEqual(rows, [(str(i), str(i), str(i)) for i in range(10)])

class RetentionTests(unittest.TestCase):
    def run_case(self, mutate=lambda b:b):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bodies, _, _ = fixture_sources()
            count = iter(range(8))
            import re
            bodies[2] = re.sub('원문 링크 미확인', lambda _: f'https://v.daum.net/v/20261021060000{next(count):03}', bodies[2])
            bodies[2] = mutate(bodies[2])
            write_sources(root, bodies=bodies)
            before = (root/'shortnews.txt').read_bytes()
            def fail(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], 180)
            report = cloud.prepare(root, root/'ready.json', root/'report.json', collect=True, now=NOW, runner=fail, retry_delays=())
            snapshot = json.loads((root/'ready.json').read_text())
            self.assertEqual((root/'shortnews.txt').read_bytes(), before)
            return report, snapshot

    def test_current_verified_news_retained_with_notice_not_fresh_success(self):
        report, snapshot = self.run_case()
        self.assertEqual(report['retainedKeys'], ['shortnews'])
        self.assertNotIn('shortnews', report['omittedKeys'])
        self.assertIn(cloud.RETAINED_NEWS_NOTICE, snapshot['boxes'][2]['body'])
        self.assertEqual(report['sourceHealth'], 'degraded')
        self.assertTrue(report['hadErrors'])
        self.assertEqual(report['groups'][2]['boxes'][0]['status'], 'retained_daily')
        self.assertEqual(report['groups'][2]['processReason'], 'collector_timeout')

    def test_previous_day_future_or_missing_links_not_retained(self):
        for mutate in (lambda b:b.replace('10월 21일','10월 20일'), lambda b:b.replace('10월 21일','10월 22일'), lambda b:b.replace('https://v.daum.net/v/20261021060000000','원문 링크 미확인'), lambda b:b.replace('20261021060000','20261001060000'), lambda b:b.replace('20261021060000','20261021070000'), lambda b:b.replace('20261021060000001','20261021060000000')):
            report, snapshot = self.run_case(mutate)
            self.assertIn('shortnews', report['omittedKeys'])
            self.assertTrue(snapshot['boxes'][2]['omitted'])

if __name__ == '__main__': unittest.main()
