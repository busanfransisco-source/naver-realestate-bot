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
        periods = ['2026-09-21', '2026-09-28', '2026-10-05', '2026-10-12'] if name.startswith('weekly') else ['2026-08', '2026-09']
        series[name] = {region: [dict(period=p, value=90 + n + i / 100,
                                     components=[30, 50 - n - i / 100, 20 + n + i / 100])
                                 for n, p in enumerate(periods)] for i, region in enumerate(sd.REGIONS)}
    return dict(schemaVersion=2, providerId='kb', provider='KB부동산', housingType='중개업소 시장동향 설문',
                checkedAtKst=NOW.isoformat(), accessMode='public_kb_datahub', regionCodes=sd.REGION_CODES,
                sourceUpdates={k: '2026-10-12' if k.startswith('weekly') else '2026-09-14' for k in sd.TABLES},
                tableIds={k: v[0] for k, v in sd.TABLES.items()}, series=series)


def fake_session(truncated=False):
    sample = snapshot()
    session = Mock()

    def get(url, params, headers, timeout):
        response = Mock()
        name = next(k for k, v in sd.TABLES.items() if v[1:3] == (params['월간주간구분코드'], params['메뉴코드']))
        weekly = name.startswith('weekly')
        _, _, _, value_column, columns = sd.TABLES[name]
        rows = []
        for region in sd.REGIONS:
            points = []
            for point in sample['series'][name][region]:
                points.append(dict(기준날짜=point['period'].replace('-', ''),
                                   **{value_column: point['value']}, **dict(zip(columns, point['components']))))
            rows.append(dict(지역명=region, 지역코드=sd.REGION_CODES[region], dataList=points))
        if truncated:
            rows = rows[:1]
        payload = {'dataHeader': {'resultCode': '10000'}, 'dataBody': {'data': {
            '업데이트일자': sample['sourceUpdates'][name].replace('-', ''),
            '날짜리스트': [p['period'].replace('-', '') for p in sample['series'][name]['전국']],
            '데이터리스트': rows}}}
        response.json.return_value = payload
        return response

    session.get.side_effect = get
    return session


class SupplyDemandTests(unittest.TestCase):
    def test_complete_two_jeonse_series_validated(self):
        self.assertTrue(sd.valid_snapshot(snapshot(), NOW))
        self.assertEqual(sd.freshness_issues(snapshot(), NOW), [])

    def test_legacy_buying_fields_are_neither_required_nor_used(self):
        original = snapshot()
        legacy = copy.deepcopy(original)
        for name in ('weekly_sale', 'monthly_sale'):
            legacy['tableIds'][name] = 'unused legacy buying table'
            legacy['sourceUpdates'][name] = 'not used'
            legacy['series'][name] = {'broken': None}
        self.assertTrue(sd.valid_snapshot(legacy, NOW))
        self.assertEqual(sd.format_digest(original, NOW), sd.format_digest(legacy, NOW))
        for body in (sd.format_digest(legacy, NOW), sd.PENDING):
            for removed in ('매수', '매도', '매매'):
                self.assertNotIn(removed, body)
        self.assertEqual(set(sd.TABLES), {'weekly_jeonse', 'monthly_jeonse'})

    def test_optional_buying_data_does_not_change_jeonse_validation(self):
        value = snapshot()
        value['series']['weekly_sale'] = {'서울': []}
        del value['series']['weekly_jeonse']['서울']
        self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_missing_region_and_duplicate_period_rejected(self):
        value = snapshot()
        del value['series']['weekly_jeonse']['서울']
        self.assertFalse(sd.valid_snapshot(value, NOW))
        value = snapshot()
        value['series']['weekly_jeonse']['서울'].append(value['series']['weekly_jeonse']['서울'][-1])
        self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_wrong_table_provider_type_and_bad_values_rejected(self):
        for bad in (-1, 201, float('nan'), float('inf'), True, '100'):
            value = snapshot()
            value['series']['weekly_jeonse']['서울'][-1]['value'] = bad
            self.assertFalse(sd.valid_snapshot(value, NOW))
        for key, bad in [('provider', '한국부동산원 R-ONE'), ('providerId', 'rone'), ('schemaVersion', 1),
                         ('housingType', '아파트'), ('tableIds', {}), ('regionCodes', {})]:
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
        for name, period in [('weekly_jeonse', '2026-10-26'), ('monthly_jeonse', '2026-11')]:
            value = snapshot()
            for values in value['series'][name].values():
                values[-1]['period'] = period
            self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_mismatched_region_or_sale_jeonse_period_rejected(self):
        value = snapshot()
        value['series']['weekly_jeonse']['서울'] = value['series']['weekly_jeonse']['서울'][:-1]
        self.assertFalse(sd.valid_snapshot(value, NOW))
        value = snapshot()
        for values in value['series']['monthly_jeonse'].values():
            values.pop()
        self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_missing_previous_week_or_month_not_mislabeled(self):
        for name in ('weekly_jeonse', 'monthly_jeonse'):
            value = snapshot()
            for values in value['series'][name].values():
                values.pop(-2)
                if name.startswith('weekly'):
                    values.pop(-2)
            self.assertFalse(sd.valid_snapshot(value, NOW))

    def test_stale_source_and_unchecked_cache_marked(self):
        later = NOW + timedelta(days=10)
        self.assertTrue(sd.valid_snapshot(snapshot(), later))
        self.assertEqual(len(sd.freshness_issues(snapshot(), later)), 2)
        self.assertIn(sd.DELAY_NOTICE, sd.format_digest(snapshot(), later))
        self.assertIn('2026-10-12', sd.format_digest(snapshot(), later))
        self.assertIn('2026년 9월', sd.format_digest(snapshot(), later))

    def test_public_kb_fetch_is_two_jeonse_requests_without_credentials(self):
        session = fake_session()
        value = sd.fetch_snapshot(NOW, session=session)
        self.assertTrue(sd.valid_snapshot(value, NOW))
        calls = session.get.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c.args[0] == sd.BASE and 'KEY' not in c.kwargs['params'] for c in calls))
        self.assertEqual(value['series'], snapshot()['series'])

    def test_every_public_series_uses_its_own_cycle_and_menu(self):
        session = fake_session()
        value = sd.fetch_snapshot(NOW, session=session)
        self.assertEqual(value['series'], snapshot()['series'])
        actual = {(c.kwargs['params']['월간주간구분코드'], c.kwargs['params']['메뉴코드']) for c in session.get.call_args_list}
        self.assertEqual(actual, {('01', '03'), ('02', '03')})

    def test_truncated_api_response_is_rejected(self):
        with self.assertRaises(ValueError):
            sd.fetch_snapshot(NOW, session=fake_session(truncated=True))

    def test_month_window_rolls_over_year(self):
        self.assertEqual(sd.month_shift(NOW.date().replace(month=1), -1).isoformat(), '2025-12-01')
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

    def test_reading_guide_contains_only_scale_baseline_and_units(self):
        body = sd.format_digest(snapshot(), NOW)
        guide = body.split('📖 읽는 법\n', 1)[1].split('\n\n출처:', 1)[0]
        self.assertEqual(guide, '지수 범위: 0~200 · 기준: 100\n'
                               '전세수급 100 초과: 공급부족 · 100 미만: 공급충분\n'
                               '100: 공급부족·공급충분 응답 비중이 같음\n증감 단위: 포인트(p)')
        for removed in ('뜻은 아닙니다', '다릅니다', '가격 전망', '실제 입주물량'):
            self.assertNotIn(removed, guide)

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
            for name in ('weekly_jeonse',):
                for rows in older['series'][name].values():
                    rows.pop()
                older['sourceUpdates'][name] = older['series'][name]['전국'][-1]['period']
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
            malformed['series']['weekly_jeonse'] = list(sd.REGIONS)
            path.write_text(json.dumps(malformed), encoding='utf-8')
            self.assertEqual(sd.load_digest(path, NOW), sd.PENDING)

    def test_new_30_keeps_legacy_numbers_and_copy_bodies_exact(self):
        body = sd.format_digest(snapshot(), NOW)
        with patch('supply_demand.load_digest', return_value=body):
            page = gen_briefing.build_html(new_data_contents={k: label for k, label in gen_briefing.NEW_DATA_SECTIONS})
        soup = BeautifulSoup(page, 'html.parser')
        sections = soup.select('section.card')
        self.assertEqual([s['data-slot'] for s in sections], [str(gen_briefing.SLOT_BY_KEY[k]) for k in gen_briefing.LIVE_KEYS])
        self.assertEqual([int(s['data-slot']) for s in sections], list(range(1, 31)))
        self.assertEqual([s.select_one('textarea')['id'][3:] for s in sections], gen_briefing.LIVE_KEYS)
        self.assertEqual(sections[-1].select_one('textarea')['id'], 'ta-supplydemand')
        self.assertEqual(sections[-1]['data-slot'], '30')
        self.assertEqual(sections[18].select_one('textarea')['id'], 'ta-transactions')
        self.assertEqual(sections[28].select_one('textarea')['id'], 'ta-analysis7')
        self.assertEqual(sections[18]['data-slot'], '19')
        self.assertEqual(sections[28]['data-slot'], '29')
        self.assertEqual(soup.select_one('#ta-supplydemand').get_text(), body)
        copied = json.loads(re.search(r'window.__content_supplydemand = (.*?);</script>', page).group(1))
        self.assertEqual(copied, body)

    def test_supply_demand_stays_last_in_core_layout_too(self):
        soup = BeautifulSoup(gen_briefing.build_html(), 'html.parser')
        sections = soup.select('section.card')
        self.assertEqual(sections[-1].select_one('textarea')['id'], 'ta-supplydemand')
        numbers = [int(section['data-slot']) for section in sections]
        self.assertEqual(numbers, sorted(numbers))

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
            step = workflow.split('- name: Refresh KB jeonse', 1)[1].split('- name:', 1)[0]
            self.assertNotIn('RONE_KEY', step)
            self.assertIn('git add supply-demand-cache.json', workflow)

    def test_source_failure_status_and_partial_date_or_region_are_rejected(self):
        payload = fake_session().get(sd.BASE, params={'월간주간구분코드': '02', '메뉴코드': '03'}, headers={}, timeout=1).json()
        changes = []
        bad = copy.deepcopy(payload)
        bad['dataHeader']['resultCode'] = '10402'
        changes.append(bad)
        bad = copy.deepcopy(payload)
        bad['dataBody']['data']['데이터리스트'][0]['지역코드'] = 'wrong'
        changes.append(bad)
        bad = copy.deepcopy(payload)
        bad['dataBody']['data']['데이터리스트'][0]['dataList'].pop()
        changes.append(bad)
        bad = copy.deepcopy(payload)
        bad['dataBody']['data']['데이터리스트'].append(copy.deepcopy(bad['dataBody']['data']['데이터리스트'][0]))
        changes.append(bad)
        bad = copy.deepcopy(payload)
        bad['dataBody']['data']['업데이트일자'] = '20261019'
        changes.append(bad)
        for bad in changes:
            with self.assertRaises(ValueError):
                sd.parse_series(bad, 'weekly_jeonse')

    def test_response_shares_and_index_formula_are_verified_not_just_range(self):
        for parts in ([30, 50, 99], [30, 50, None], [True, 49, 21], [30, 40, 30]):
            bad = snapshot()
            bad['series']['monthly_jeonse']['부산'][-1]['components'] = parts
            self.assertFalse(sd.valid_snapshot(bad, NOW))
        bad = snapshot()
        bad['series']['monthly_jeonse']['부산'][-1]['value'] = 176.38
        self.assertFalse(sd.valid_snapshot(bad, NOW))

    def test_holiday_skipped_week_is_labeled_previous_publication_not_previous_week(self):
        value = snapshot()
        for name in ('weekly_jeonse',):
            for rows in value['series'][name].values():
                rows.pop(-2)
        self.assertTrue(sd.valid_snapshot(value, NOW))
        body = sd.format_digest(value, NOW)
        self.assertIn('직전 발표 기준일 2026-09-28 대비', body)
        self.assertNotIn('전주 대비', body)

    def test_rechecks_change_no_source_values_or_display_body(self):
        first = snapshot()
        second = copy.deepcopy(first)
        second['checkedAtKst'] = (NOW + timedelta(hours=1)).isoformat()
        self.assertEqual(sd.format_digest(first, NOW), sd.format_digest(second, NOW + timedelta(hours=1)))

    def test_only_two_jeonse_indices_and_every_region_are_printed(self):
        body = sd.format_digest(snapshot(), NOW)
        for title in ('주간 전세수급지수', '월간 전세수급지수'):
            self.assertIn(title, body)
        for region in sd.REGIONS:
            self.assertEqual(sum(line.startswith(region + ' ') for line in body.splitlines()), 2)
        self.assertNotIn('아파트 · 한국부동산원', body)


if __name__ == '__main__':
    unittest.main()
