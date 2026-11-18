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

    def test_single_candidate_parse_error_does_not_abort_batch(self):
        with patch.object(news, 'DEADLINE', None), patch.object(news, 'get') as get, patch.object(news, 'summary_from_html', side_effect=[ValueError('bad html'), 'good']), patch.object(news, 'polite_summary', side_effect=lambda text:text):
            get.return_value.text='html'
            result=list(news.candidate_summaries([('bad','1'),('good','2')]))
        self.assertEqual(result,[('bad','1',''),('good','2','good')])

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

    def test_diagnostics_persist_without_request_details(self):
        from quicknews_state import commit_candidate, STATUS
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            commit_candidate('', NOW, root, diagnostic_counts={'http_503':2,'secret-url':5,'ReadTimeout':'private'},budget_exhausted=True)
            status=json.loads((root/STATUS).read_text())
            self.assertEqual(status['collectionDiagnostics'],{'http_503':2})
            self.assertTrue(status['budgetExhausted'])

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

    def test_retained_news_retries_and_can_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            body=fixture_sources()[0][2]
            import re
            count=iter(range(8))
            body=re.sub('원문 링크 미확인', lambda _:f'https://v.daum.net/v/20261021060000{next(count):03}',body)
            for name in ('shortnews.txt','shortnews-wed.txt'): (root/name).write_text(body)
            calls=0
            def runner(command, **kwargs):
                nonlocal calls
                if command[-1]=='daum_news_fetch.py':
                    calls+=1
                    if calls==1: raise subprocess.TimeoutExpired(command,180)
                    for name in ('shortnews.txt','shortnews-wed.txt'): (root/name).write_text(body)
                return subprocess.CompletedProcess(command,0)
            report=cloud.prepare(root,root/'ready.json',root/'report.json',collect=True,now=NOW,runner=runner,retry_delays=(0,),sleeper=lambda _:None)
            self.assertEqual(calls,2)
            self.assertEqual(report['retainedKeys'],[])
            self.assertTrue(report['hadErrors'])
            self.assertEqual(report['groups'][2]['boxes'][0]['status'],'ok')

    def test_apply_render_and_signed_snapshot_share_retention_notice(self):
        import os
        from datetime import datetime
        import gen_briefing
        from quicknews_state import merge_status, NOTICE
        from morning_source_publication import apply_collection, verify_publication_page
        from morning_briefing_contract import validate_snapshot
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            root,target=Path(src),Path(dst)
            now=datetime.now(cloud.KST)
            body=fixture_sources()[0][2].replace('26년 10월 21일',f'{now.year%100}년 {now.month}월 {now.day}일')
            import re
            count=iter(range(8))
            body=re.sub('원문 링크 미확인',lambda _:f'https://v.daum.net/v/{now:%Y%m%d}000000{next(count):03}',body)
            (root/'shortnews.txt').write_text(body)
            def fail(*args,**kwargs): raise subprocess.TimeoutExpired(args[0],180)
            report=cloud.prepare(root,root/'ready.json',root/'report.json',collect=True,now=now,runner=fail,retry_delays=())
            publication=root/'morning-website-sources.json'
            applied=apply_collection(publication,snapshot_path=root/'ready.json',root=target,now=now)
            self.assertTrue(applied['websiteApplied'])
            self.assertTrue(applied['readyApplied'])
            status=root/'shortnews-status.txt'
            status.write_text(json.dumps(dict(status='failed',attemptedAtKst=now.isoformat(),issues=['timeout'])))
            self.assertTrue(merge_status(status,root=target,now=now))
            previous=os.getcwd()
            try:
                os.chdir(target)
                html=gen_briefing.build_html()
            finally: os.chdir(previous)
            artifact=json.loads(publication.read_text())
            verify_publication_page(artifact,html,now)
            snap=json.loads((target/'morning-briefing-ready.json').read_text())
            bodies=validate_snapshot(snap,now)
            self.assertEqual(bodies[2],artifact['boxes'][0]['body'])
            self.assertEqual(bodies[2].count(cloud.RETAINED_NEWS_NOTICE),1)
            self.assertNotIn(NOTICE,bodies[2])

if __name__ == '__main__': unittest.main()
