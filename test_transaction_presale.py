import json
import subprocess
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock

import transaction_presale as presale
from realestate_transactions_fetch import build_digest, tokenized_rows
from ensure_transactions_daily import complete_today, recover

TODAY = date(2026, 11, 27)
APT = dict(building_name='검증아파트',region_name='서울특별시 중구',area=84,deal_amount=100000,
           year='2026',month='11',day='26',is_presale=False,is_record=True,price_per_pyeong=3900)
RIGHT = {**APT,'building_name':'검증분양권','is_presale':True,'property_type':'분양권/입주권'}


class PresaleTests(TestCase):
    def write_fixture(self, folder, **changes):
        root=Path(folder)
        state=dict(version=6,last_output_date=TODAY.isoformat(),source='국토교통부 공공데이터 API (분양권 CSV 일시 실패)',
                   today_new_records=[APT],seen_tokens=list(tokenized_rows([APT,RIGHT])),history_max={},
                   auxiliary_complete=False,presale_status='timeout')
        state.update(changes)
        (root/'transactions-state.json').write_text(json.dumps(state,ensure_ascii=False),encoding='utf8')
        body=build_digest(TODAY,[APT])+'\n'
        for name in ('transactions.txt','transactions-fri.txt','transactions-2026-11-27.txt'):
            (root/name).write_text(body,encoding='utf8')
        return body

    def test_timeout_and_successful_zero_have_different_copyable_bodies(self):
        failed=build_digest(TODAY,[APT],presale_status='timeout')
        self.assertIn('분양권/입주권 집계 미확인(수집 시간초과)',failed)
        self.assertNotIn('분양권/입주권 0건',failed)
        self.assertIn('전국 1건 (🔥1)',failed)
        self.assertTrue(complete_today(failed,TODAY))
        self.assertIn('분양권/입주권 0건',build_digest(TODAY,[APT]))
        self.assertIn('집계 미확인',presale.count_line(None))

    def test_upstream_missing_count_is_not_converted_to_zero(self):
        from apt_today_closings_fetch import build_digest as upstream_digest
        summary=dict(since='2026-11-26T20:00:00Z',totalCount=1250,allTimeHighCount=245)
        _,text=upstream_digest(summary)
        self.assertIn('분양권/입주권 집계 미확인',text)
        self.assertNotIn('분양권/입주권 0건',text)
        summary['preconstructedSaleCount']=0
        self.assertIn('분양권/입주권 0건',upstream_digest(summary)[1])

    def test_presale_count_does_not_change_apartment_total_or_regions(self):
        text=build_digest(TODAY,[APT,RIGHT])
        self.assertIn('전국 1건 (🔥1)',text)
        self.assertIn('서울 1건 (🔥1)',text)
        self.assertIn('분양권/입주권 1건',text)
        summary=build_digest(TODAY,[APT],presale_count=110)
        self.assertIn('전국 1건 (🔥1)',summary)
        self.assertIn('분양권/입주권 110건',summary)

    def test_health_records_partial_auxiliary_status_without_failing_apartment_publication(self):
        from datetime import datetime
        from html import escape
        from briefing_health import inspect, KST
        body=build_digest(TODAY,[APT],presale_status='timeout')
        page='<section class="card" data-slot="19"><textarea id="ta-transactions">'+escape(body)+'</textarea></section>'
        row=next(r for r in inspect(page,datetime(2026,11,27,10,tzinfo=KST)) if r['key']=='transactions')
        self.assertEqual(row['status'],'partial')
        self.assertIn('presale count unverified',row['issues'][0])

    def test_repair_updates_all_aliases_without_changing_verified_apartment_body(self):
        with TemporaryDirectory() as folder:
            before=self.write_fixture(folder)
            self.assertTrue(presale.repair_outputs(TODAY,folder))
            expected=before.replace('분양권/입주권 0건',presale.count_line(None,'timeout'))
            for path in Path(folder).glob('transactions*.txt'):
                self.assertEqual(path.read_text(encoding='utf8'),expected)
            self.assertTrue(recover(TODAY,folder,fetch=Mock(side_effect=AssertionError('no recollection'))))

    def test_auxiliary_retry_has_a_hard_budget_and_does_not_pass_api_key(self):
        with patch.dict('os.environ',{'MOLIT_API_KEY':'mock-secret'}), patch.object(presale.subprocess,'run') as run:
            run.side_effect=subprocess.TimeoutExpired('worker',20)
            with self.assertRaises(subprocess.TimeoutExpired):presale.fetch_rows(TODAY)
            self.assertEqual(run.call_args.kwargs['timeout'],20)
            self.assertNotIn('MOLIT_API_KEY',run.call_args.kwargs['env'])

    def test_worker_timeout_is_distinguished_from_explicit_access_restriction(self):
        timed_out=subprocess.CalledProcessError(1,'worker',stderr='Traceback\nURLError: <urlopen error timed out>')
        restricted=subprocess.CalledProcessError(1,'worker',stderr='get(timeout=4)\nPermissionError: official source restricted')
        self.assertEqual(presale.failure_status(timed_out),'timeout')
        self.assertEqual(presale.failure_status(restricted),'failed')

    def test_retry_timeout_preserves_apartments_and_seen_tokens(self):
        with TemporaryDirectory() as folder:
            before=self.write_fixture(folder)
            original=json.loads((Path(folder)/'transactions-state.json').read_text(encoding='utf8'))
            fetch=Mock(side_effect=TimeoutError('upstream timed out'))
            self.assertFalse(presale.refresh(TODAY,folder,fetch))
            state=json.loads((Path(folder)/'transactions-state.json').read_text(encoding='utf8'))
            self.assertEqual(state['today_new_records'],original['today_new_records'])
            self.assertEqual(state['seen_tokens'],original['seen_tokens'])
            self.assertEqual(state['presale_status'],'timeout')
            self.assertIn('집계 미확인(수집 시간초과)',(Path(folder)/'transactions.txt').read_text(encoding='utf8'))

    def test_verified_empty_delta_can_be_reported_as_zero(self):
        with TemporaryDirectory() as folder:
            before=self.write_fixture(folder,presale_baseline_date='2026-11-26',presale_baseline_started_date='2026-11-25')
            self.assertTrue(presale.refresh(TODAY,folder,Mock(return_value=[RIGHT])))
            self.assertEqual((Path(folder)/'transactions.txt').read_text(encoding='utf8'),before)
            state=json.loads((Path(folder)/'transactions-state.json').read_text(encoding='utf8'))
            self.assertEqual(state['presale_status'],'ok')

    def test_same_day_full_collection_keeps_a_verified_auxiliary_count(self):
        import os
        from datetime import datetime
        import realestate_transactions_fetch as collection
        with TemporaryDirectory() as folder:
            self.write_fixture(folder,presale_baseline_date='2026-11-26',presale_baseline_started_date='2026-11-25',today_presale_count=110)
            previous=os.getcwd()
            try:
                os.chdir(folder)
                with patch.object(collection,'STATE_PATH',Path('transactions-state.json')), \
                     patch.object(collection,'collect_transaction_rows',return_value=([APT,RIGHT],'verified sources',True,'ok')), \
                     patch.object(collection,'datetime') as clock:
                    clock.now.return_value=datetime(2026,11,27,12,tzinfo=collection.KST)
                    collection.main([])
                self.assertIn('분양권/입주권 110건',Path('transactions.txt').read_text(encoding='utf8'))
            finally:
                os.chdir(previous)

    def test_download_without_previous_baseline_is_not_fabricated_daily_zero(self):
        with TemporaryDirectory() as folder:
            self.write_fixture(folder)
            presale.refresh(TODAY,folder,Mock(return_value=[RIGHT]))
            text=(Path(folder)/'transactions.txt').read_text(encoding='utf8')
            self.assertIn('집계 미확인(비교 기준 미확보)',text)
            self.assertNotIn('분양권/입주권 0건',text)

    def test_stale_state_cannot_rewrite_today_output(self):
        with TemporaryDirectory() as folder:
            before=self.write_fixture(folder,last_output_date='2026-11-26')
            self.assertFalse(presale.repair_outputs(TODAY,folder))
            self.assertEqual((Path(folder)/'transactions.txt').read_text(encoding='utf8'),before)

    def test_access_restriction_is_not_retried_with_another_transport(self):
        with patch('curl_cffi.requests.Session') as factory, patch('realestate_transactions_fetch.fetch_nationwide_transactions') as fallback:
            factory.return_value.__enter__.return_value.get.return_value.status_code=403
            with self.assertRaises(PermissionError):presale.fetch_payload(TODAY)
            fallback.assert_not_called()

    def test_browser_session_success_preserves_official_form_and_validates_csv(self):
        with patch('curl_cffi.requests.Session') as factory, patch('realestate_transactions_fetch.parse_government_csv', return_value=[RIGHT]) as parse:
            session=factory.return_value.__enter__.return_value
            session.get.return_value.status_code=200
            session.post.return_value.status_code=200
            session.post.return_value.content=b'verified csv'
            self.assertEqual(presale.fetch_payload(TODAY),[RIGHT])
            self.assertEqual(session.post.call_args.kwargs['data']['srhThingNo'],'E')
            self.assertEqual(session.post.call_args.kwargs['timeout'],(4,10))
            parse.assert_called_once_with(b'verified csv','분양권/입주권')

    def test_transient_transport_failure_has_one_independent_fallback(self):
        with patch('curl_cffi.requests.Session') as factory, patch('realestate_transactions_fetch.fetch_nationwide_transactions',return_value=[RIGHT]) as fallback:
            factory.return_value.__enter__.return_value.get.side_effect=TimeoutError('timeout')
            self.assertEqual(presale.fetch_payload(TODAY),[RIGHT])
            fallback.assert_called_once()
