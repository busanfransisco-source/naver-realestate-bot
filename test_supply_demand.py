import copy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import requests

import gen_briefing
import supply_demand as sd


NOW = datetime(2026, 10, 20, 15, tzinfo=sd.KST)


def snapshot():
    series = {}
    for name in sd.TABLES:
        periods = ['2026-09-21', '2026-09-28', '2026-10-05', '2026-10-12'] if name.startswith('weekly') else ['2026-07', '2026-08', '2026-09']
        series[name] = {region: [dict(period=p, value=90 + n + i / 100)
                                 for n, p in enumerate(periods)] for i, region in enumerate(sd.REGIONS)}
    return dict(schemaVersion=1, provider='한국부동산원 R-ONE', housingType='아파트',
                checkedAtKst=NOW.isoformat(), accessMode='authenticated',
                tableIds={k: v[0] for k, v in sd.TABLES.items()}, series=series)


def fake_session(truncated=False):
    sample = snapshot()
    session = Mock()

    def get(url, params, timeout):
        response = Mock()
        table = params.get('statblId') or params.get('STATBL_ID')
        name = next(k for k, v in sd.TABLES.items() if v[0] == table)
        weekly = name.startswith('weekly')
        first_code, item = (50001, 10001) if weekly else (500001, 100001)
        codes = {r: first_code + i for i, r in enumerate(sd.REGIONS)}
        if 'selectOpenApiItmCd' in url:
            payload = {'data': [dict(itmTag='분류', itmNm=r, itmId=c) for r, c in codes.items()]
                       + [dict(itmTag='항목', itmNm='지수', itmId=item)]}
        else:
            regions = [r for r, c in codes.items() if str(c) == params['CLS_ID']] if 'CLS_ID' in params else sd.REGIONS
            rows = []
            for region in regions:
                for point in sample['series'][name][region]:
                    period = point['period']
                    if not weekly:
                        y, m = period.split('-')
                        period = f'{y}년 {int(m)}월'
                    rows.append(dict(CLS_NM=region, CLS_ID=codes[region], ITM_ID=item, STATBL_ID=table,
                                     DTACYCLE_CD='WK' if weekly else 'MM', WRTTIME_DESC=period, DTA_VAL=point['value']))
            total = len(rows)
            if truncated:
                rows = rows[:1]
            payload = {'SttsApiTblData': [{'head': [{'list_total_count': total}]}, {'row': rows}]}
        response.json.return_value = payload
        return response

    session.get.side_effect = get
    return session


class SupplyDemandTests(unittest.TestCase):
    def test_complete_four_series_validated(self):
        self.assertTrue(sd.valid_snapshot(snapshot(), NOW))
        self.assertEqual(sd.freshness_issues(snapshot(), NOW), [])

    def test_missing_region_and_duplicate_period_rejected(self):
        value = snapshot()
        del value['series']['weekly_sale']['서울']
        self.assertFalse(sd.valid_snapshot(value, NOW))
        value = snapshot()
        value['series']['weekly_sale']['서울'].append(value['series']['weekly_sale']['서울'][-1])
        self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_wrong_table_provider_type_and_bad_values_rejected(self):
        for bad in (-1, 201, float('nan'), float('inf'), True, '100'):
            value = snapshot()
            value['series']['weekly_sale']['서울'][-1]['value'] = bad
            self.assertFalse(sd.valid_snapshot(value, NOW))
        for key, bad in [('provider', 'KB'), ('housingType', '주택종합'), ('tableIds', {})]:
            value = snapshot()
            value[key] = bad
            self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_future_timestamp_or_future_source_and_current_month_rejected(self):
        value = snapshot()
        value['checkedAtKst'] = (NOW + timedelta(days=1)).isoformat()
        self.assertFalse(sd.valid_snapshot(value, NOW))
        value = snapshot()
        value['checkedAtKst'] = NOW.replace(tzinfo=None).isoformat()
        self.assertFalse(sd.valid_snapshot(value, NOW))
        for name, period in [('weekly_sale', '2026-10-26'), ('monthly_sale', '2026-10')]:
            value = snapshot()
            for values in value['series'][name].values():
                values[-1]['period'] = period
            self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_mismatched_region_or_sale_jeonse_period_rejected(self):
        value = snapshot()
        value['series']['weekly_sale']['서울'] = value['series']['weekly_sale']['서울'][:-1]
        self.assertFalse(sd.valid_snapshot(value, NOW))
        value = snapshot()
        for values in value['series']['monthly_jeonse'].values():
            values.pop()
        self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_missing_previous_week_or_month_not_mislabeled(self):
        for name in ('weekly_sale', 'monthly_sale'):
            value = snapshot()
            for values in value['series'][name].values():
                values.pop(-2)
            self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_stale_source_and_unchecked_cache_marked(self):
        later = NOW + timedelta(days=10)
        self.assertTrue(sd.valid_snapshot(snapshot(), later))
        self.assertEqual(len(sd.freshness_issues(snapshot(), later)), 2)
        self.assertIn(sd.DELAY_NOTICE, sd.format_digest(snapshot(), later))
        self.assertIn('2026-10-12', sd.format_digest(snapshot(), later))
        self.assertIn('2026년 9월', sd.format_digest(snapshot(), later))

    def test_authenticated_fetch_is_four_complete_requests_without_key_storage(self):
        session = fake_session()
        value = sd.fetch_snapshot(NOW, key='private-test-secret', session=session)
        self.assertTrue(sd.valid_snapshot(value, NOW))
        calls = [c for c in session.get.call_args_list if 'SttsApiTblData' in c.args[0]]
        self.assertEqual(len(calls), 4)
        self.assertNotIn('private-test-secret', json.dumps(value))
        self.assertEqual(value['series'], snapshot()['series'])

    def test_public_filtered_requests_are_complete_not_first_sample_reused(self):
        session = fake_session()
        value = sd.fetch_snapshot(NOW, key='', session=session)
        self.assertEqual(value['series'], snapshot()['series'])
        calls = [c for c in session.get.call_args_list if 'SttsApiTblData' in c.args[0]]
        self.assertEqual(len(calls), 76)
        self.assertTrue(all('CLS_ID' in c.kwargs['params'] and 'END_WRTTIME' in c.kwargs['params'] for c in calls))

    def test_truncated_api_response_is_rejected(self):
        for key in ('', 'private-test-secret'):
            with self.assertRaises(ValueError):
                sd.fetch_snapshot(NOW, key=key, session=fake_session(truncated=True))

    def test_month_window_rolls_over_year(self):
        self.assertEqual(sd.request_window('MM', NOW.date().replace(month=1)), ('202510', '202512'))
        self.assertEqual(sd.month_shift(NOW.date(), -10).isoformat(), '2025-12-01')

    def test_output_dates_units_regions_and_rounding(self):
        body = sd.format_digest(snapshot(), NOW)
        self.assertIn('주간 기준일: 2026-10-12', body)
        self.assertIn('월간 기준월: 2026년 9월', body)
        self.assertIn('전주 대비', body)
        self.assertIn('전월 대비', body)
        self.assertNotIn('%', body)
        for r in sd.REGIONS:
            self.assertIn('지방' if r == '지방권' else r, body)
        self.assertEqual(sd.delta_text(0), '변동 없음')
        self.assertEqual(sd.delta_text(-0.001), '0.01p 미만 하락')
        self.assertNotIn('-0.00', sd.delta_text(-0.001))

    def test_collection_retries_then_recovers(self):
        with tempfile.TemporaryDirectory() as temp, patch('supply_demand.time.sleep'):
            fetcher = Mock(side_effect=[ValueError('invalid'), snapshot()])
            path = Path(temp) / 'cache.json'
            self.assertTrue(sd.collect(path, NOW, fetcher=fetcher))
            self.assertEqual(fetcher.call_count, 2)
            self.assertEqual(sd.read_snapshot(path), snapshot())

    def test_failure_preserves_exact_previous_source_and_never_leaks_key(self):
        with tempfile.TemporaryDirectory() as temp, patch('supply_demand.time.sleep'):
            path = Path(temp) / 'cache.json'
            raw = json.dumps(snapshot(), ensure_ascii=False)
            path.write_text(raw, encoding='utf-8')
            output = io.StringIO()
            with patch('sys.stdout', output):
                ok = sd.collect(path, NOW, force=True, fetcher=Mock(side_effect=requests.RequestException('KEY=private-test-secret')))
            self.assertFalse(ok)
            self.assertNotIn('private-test-secret', output.getvalue())
            self.assertEqual(path.read_text(encoding='utf-8'), raw)

    def test_recent_check_throttled_but_force_rechecks(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cache.json'
            path.write_text(json.dumps(snapshot()), encoding='utf-8')
            fetcher = Mock(return_value=snapshot())
            self.assertTrue(sd.collect(path, NOW, fetcher=fetcher))
            fetcher.assert_not_called()
            self.assertTrue(sd.collect(path, NOW, force=True, fetcher=fetcher))
            fetcher.assert_called_once()

    def test_source_regression_cannot_overwrite_newer_cache(self):
        with tempfile.TemporaryDirectory() as temp, patch('supply_demand.time.sleep'):
            path = Path(temp) / 'cache.json'
            value = snapshot()
            path.write_text(json.dumps(value), encoding='utf-8')
            older = copy.deepcopy(value)
            for name in ('weekly_sale', 'weekly_jeonse'):
                for rows in older['series'][name].values():
                    rows.pop()
            self.assertTrue(sd.valid_snapshot(older, NOW))
            self.assertFalse(sd.collect(path, NOW, force=True, fetcher=Mock(return_value=older)))
            self.assertEqual(sd.read_snapshot(path), value)

    def test_bad_or_missing_cache_shows_pending_not_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cache.json'
            for value in ([], {'bad': True}, None):
                path.write_text(json.dumps(value), encoding='utf-8')
                self.assertEqual(sd.load_digest(path, NOW), sd.PENDING)
            malformed = snapshot()
            malformed['series']['weekly_sale'] = list(sd.REGIONS)
            path.write_text(json.dumps(malformed), encoding='utf-8')
            self.assertEqual(sd.load_digest(path, NOW), sd.PENDING)

    def test_new_30_keeps_legacy_numbers_and_copy_bodies_exact(self):
        body = sd.format_digest(snapshot(), NOW)
        with patch('supply_demand.load_digest', return_value=body):
            page = gen_briefing.build_html(new_data_contents={k: label for k, label in gen_briefing.NEW_DATA_SECTIONS})
        soup = BeautifulSoup(page, 'html.parser')
        sections = soup.select('section.card')
        self.assertEqual([s['data-slot'] for s in sections], [str(gen_briefing.SLOT_BY_KEY[k]) for k in gen_briefing.LIVE_KEYS])
        self.assertEqual(sorted(int(s['data-slot']) for s in sections), list(range(1, 31)))
        self.assertEqual([s.select_one('textarea')['id'][3:] for s in sections], gen_briefing.LIVE_KEYS)
        self.assertEqual(sections[5].select_one('textarea')['id'], 'ta-supplydemand')
        self.assertEqual(sections[5]['data-slot'], '30')
        self.assertEqual(sections[19].select_one('textarea')['id'], 'ta-transactions')
        self.assertEqual(sections[29].select_one('textarea')['id'], 'ta-analysis7')
        self.assertEqual(sections[19]['data-slot'], '19')
        self.assertEqual(sections[29]['data-slot'], '29')
        self.assertEqual(soup.select_one('#ta-supplydemand').get_text(), body)
        copied = json.loads(re.search(r'window.__content_supplydemand = (.*?);</script>', page).group(1))
        self.assertEqual(copied, body)

    def test_health_checks_source_and_actual_body(self):
        from briefing_health import inspect, REPAIR
        body = sd.format_digest(snapshot(), NOW)
        with patch('supply_demand.load_digest', return_value=body), patch('supply_demand.read_snapshot', return_value=snapshot()):
            page = gen_briefing.build_html(new_data_contents={k: label for k, label in gen_briefing.NEW_DATA_SECTIONS})
            row = next(r for r in inspect(page, NOW) if r['key'] == 'supplydemand')
            self.assertEqual(row['status'], 'ok')
            page = page.replace('전국 93.00', '전국 999.00', 1)
            row = next(r for r in inspect(page, NOW) if r['key'] == 'supplydemand')
            self.assertEqual(row['status'], 'failed')
        self.assertEqual(REPAIR['supplydemand'], 'supply_demand.py')

    def test_legacy_sender_contract_numbers_stay_frozen(self):
        legacy = ('fortune weather shortnews subs trend fuelfx metalcoin books realestate world finance ai '
                  'daily19 daily20 daily21 daily22 daily23 daily24 transactions seoulcommerce cryptofear '
                  'wikiinterest analysis3 analysis4 analysis5 analysis2 analysis6 analysis1 analysis7').split()
        self.assertEqual({key: gen_briefing.SLOT_BY_KEY[key] for key in legacy},
                         {key: number for number, key in enumerate(legacy, 1)})
        self.assertEqual(gen_briefing.SLOT_BY_KEY['supplydemand'], 30)

    def test_existing_cloud_workflows_collect_and_persist_new_cache(self):
        for name in ('manual-briefing', 'naver-realestate', 'daily-data-cards'):
            workflow = Path(f'.github/workflows/{name}.yml').read_text(encoding='utf-8')
            self.assertIn('python supply_demand.py', workflow)
            self.assertIn('RONE_KEY: ${{ secrets.RONE_KEY }}', workflow)
            self.assertIn('git add supply-demand-cache.json', workflow)


if __name__ == '__main__':
    unittest.main()
