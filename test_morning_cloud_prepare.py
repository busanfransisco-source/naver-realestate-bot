import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import morning_cloud_prepare as cloud
from morning_briefing_contract import (
    BOX_KEYS, KST, build_snapshot, snapshot_sha256, validate_snapshot,
)
from neonet_trend import REGIONS, URL, format_digest

NOW = datetime(2026, 10, 21, 6, 10, tzinfo=KST)
HEAD = '26년 10월 21일 수요일 '


def fixture_sources():
    trend = dict(schemaVersion=1, sourceUrl=URL, checkedAtKst=NOW.isoformat(),
                 data=dict(national=dict(sale='0.11', jeonse='0.09', salePrice=1884,
                                         jeonsePrice=1055),
                           regions=[dict(region=region, sale='0.01', jeonse='-0.01')
                                    for region in REGIONS]))
    bodies = [
        '오늘의 운세, 10월 21일\n\n' + '\n\n'.join(
            f'〈{animal}띠〉\n\n오늘 해야 할 일을 차분하게 진행하십시오.\n\n\n운세지수 80%. 금전 80 건강 80 애정 80'
            for animal in ('쥐', '소', '범', '토끼', '용', '뱀', '말', '양', '원숭이', '닭', '개', '돼지')),
        '2026년 10월 21일 수요일\n\n❒ 지역별 날씨전망 ❒\n\n' + '\n'.join(
            f'✫{city}(☀️)➠(☁️)  10℃ ~ 20℃' for city in cloud_contract_cities()),
        HEAD + '오늘의 퀵뉴스⚡\n\n' + '\n\n'.join(
            f'📰 ({label}) 경제와 생활에 관한 새로운 소식을 확인했습니다.'
            for label in ('정치', '정치', '경제', '경제', '사회', '사회', '국제', '국제')),
        HEAD + '청약 소식\n\n🏗️ 청약 접수 단지 (전국, 2주 이내)\n\n'
        '[서울·민간] 검증된 아파트 청약 단지 | 접수 10/21~10/23 | 발표 10/30\n',
        format_digest(trend),
        HEAD + '기름값·환율\n\n⛽ 전국 평균 기름값\n휘발유 1,600원/L\n경유 1,500원/L\n\n'
        '💱 주요국 환율\n미국 달러 : 1,400원\n일본 엔(100) : 900원\n',
        HEAD + '금·은·코인\n\n국제 금 선물 4,000달러/온스\n국내 금 170,000원/g\n국제 은 50달러/온스\n\n'
        '🪙 코인 시가총액 상위 10\n\n' + '\n'.join(
            f'{name} 1,000원 (+1.0%)' for name in
            ('비트코인', '이더리움', '리플', '솔라나', '비앤비', '도지코인', '트론', 'XMR', 'ZEC', 'ADA')),
        HEAD + '주간 베스트셀러\n\n📚 YES24 국내도서 주간 베스트 TOP 10\n'
        '📅 집계 기간: 2026-10-12 ~ 2026-10-18\n국내도서 종합 · 온라인·매장 판매 기준\n\n' +
        '\n'.join(f'{i}. 검증된 도서 제목 {i}' for i in range(1, 11)) + '\n\n출처: YES24 주간 베스트',
        HEAD + '부동산 주요뉴스\n\n지역별 주택시장에 관한 첫 번째 기사의 제목입니다\n'
        'https://n.news.naver.com/article/001/123456\n\n'
        '주택 공급과 전세시장에 관한 두 번째 기사의 제목입니다\n'
        'https://n.news.naver.com/article/002/234567\n',
    ]
    evidence = dict(trendCheckedAtKst=NOW.isoformat(), booksPeriodStart='2026-10-12', booksPeriodEnd='2026-10-18')
    return bodies, evidence, trend


def cloud_contract_cities():
    from morning_briefing_contract import WEATHER_CITIES
    return WEATHER_CITIES


def write_sources(directory, bodies=None, trend=None):
    originals, _, original_trend = fixture_sources()
    bodies = originals if bodies is None else bodies
    for key, body in zip(BOX_KEYS, bodies):
        (directory / f'{key}.txt').write_text(body, encoding='utf-8')
        (directory / f'{key}-wed.txt').write_text(body, encoding='utf-8')
    (directory / 'neonet-trend-cache.json').write_text(
        json.dumps(trend or original_trend, ensure_ascii=False), encoding='utf-8')


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bodies, self.evidence, _ = fixture_sources()
        self.snapshot = build_snapshot(self.bodies, NOW, evidence=self.evidence)

    def resign(self, snapshot):
        snapshot['snapshotSha256'] = snapshot_sha256(snapshot)
        return snapshot

    def test_success_returns_only_nine_bodies(self):
        self.assertEqual(validate_snapshot(self.snapshot, NOW), self.bodies)

    def test_missing_or_duplicate_identity_rejected(self):
        for mutate in (lambda value: value['boxes'].pop(),
                       lambda value: value['boxes'][3].update(number=3),
                       lambda value: value['boxes'][0].update(key='weather')):
            value = copy.deepcopy(self.snapshot)
            mutate(value)
            with self.assertRaises(ValueError):
                validate_snapshot(self.resign(value), NOW)

    def test_body_and_bundle_hash_both_checked(self):
        value = copy.deepcopy(self.snapshot)
        value['boxes'][0]['body'] += 'changed'
        with self.assertRaises(ValueError):
            validate_snapshot(self.resign(value), NOW)
        value = copy.deepcopy(self.snapshot)
        value['evidence']['trendCheckedAtKst'] = (NOW - timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            validate_snapshot(value, NOW)

    def test_other_day_expired_future_and_four_hour_age_rejected(self):
        for now in (NOW - timedelta(minutes=1), NOW + timedelta(hours=4, seconds=1),
                    NOW + timedelta(days=1)):
            with self.assertRaises(ValueError):
                validate_snapshot(self.snapshot, now)
        value = copy.deepcopy(self.snapshot)
        value['expiresAtKst'] = (NOW + timedelta(days=3)).isoformat()
        with self.assertRaises(ValueError):
            validate_snapshot(self.resign(value), NOW)

    def test_naive_clock_and_boolean_schema_rejected(self):
        with self.assertRaises(ValueError):
            validate_snapshot(self.snapshot, NOW.replace(tzinfo=None))
        value = copy.deepcopy(self.snapshot)
        value['schemaVersion'] = True
        with self.assertRaises(ValueError):
            validate_snapshot(self.resign(value), NOW)

    def test_old_daily_report_not_relabelled(self):
        for index in (0, 1, 2, 3, 5, 6, 8):
            bodies = self.bodies[:]
            bodies[index] = bodies[index].replace('10월 21일', '10월 20일')
            with self.assertRaises(ValueError):
                build_snapshot(bodies, NOW, evidence=self.evidence)

    def test_valid_weekly_books_preserve_original_date_without_blocking_daily_bundle(self):
        bodies = self.bodies[:]
        bodies[7] = bodies[7].replace('10월 21일', '10월 20일')
        snapshot = build_snapshot(bodies, NOW, evidence=self.evidence)
        self.assertEqual(validate_snapshot(snapshot,NOW)[7],bodies[7])
        self.assertIn('26년 10월 20일',snapshot['boxes'][7]['body'])
        self.assertEqual(snapshot['deliveryDateKst'],'2026-10-21')
        for body in (bodies[7].replace('10월 20일','10월 22일'),
                     bodies[7].replace('YES24','알라딘'),
                     bodies[7].replace('10. 검증된 도서 제목 10','누락')):
            bad=bodies[:]; bad[7]=body
            with self.assertRaises(ValueError):
                build_snapshot(bad,NOW,evidence=self.evidence)

    def test_books_accept_only_original_today_or_yesterday_with_two_or_four_digit_year(self):
        for header in ('26년 10월 21일', '26년 10월 20일', '2026년 10월 20일'):
            bodies = self.bodies[:]
            bodies[7] = bodies[7].replace('26년 10월 21일', header)
            value = build_snapshot(bodies, NOW, evidence=self.evidence)
            self.assertEqual(value['boxes'][7]['body'], bodies[7])
        for header in ('26년 10월 19일', '26년 10월 22일', '026년 10월 20일'):
            bodies = self.bodies[:]
            bodies[7] = bodies[7].replace('26년 10월 21일', header)
            with self.assertRaises(ValueError):
                build_snapshot(bodies, NOW, evidence=self.evidence)

    def test_explicit_books_omission_keeps_nine_slots_and_eight_valid_bodies(self):
        bodies = self.bodies[:]
        bodies[7] = ''
        with self.assertRaises(ValueError):
            build_snapshot(bodies, NOW, evidence=self.evidence)
        value = build_snapshot(bodies, NOW, evidence=self.evidence, omit_books=True)
        returned = validate_snapshot(value, NOW)
        self.assertEqual(len(returned), 9)
        self.assertEqual(returned[7], '')
        self.assertEqual([box['number'] for box in value['boxes']], list(range(1, 10)))
        self.assertEqual([box['key'] for box in value['boxes']], list(BOX_KEYS))
        self.assertTrue(value['boxes'][7]['omitted'])
        self.assertEqual(value['boxes'][7]['omissionReason'], 'source_unavailable')
        self.assertNotIn('booksPeriodStart', value['evidence'])
        self.assertNotIn('booksPeriodEnd', value['evidence'])
        for other in range(9):
            if other == 7:
                continue
            bad = bodies[:]
            bad[other] = ''
            with self.assertRaises(ValueError):
                build_snapshot(bad, NOW, evidence=self.evidence, omit_books=True)

    def test_books_omission_is_explicit_empty_hashed_and_cannot_move_slots(self):
        with self.assertRaises(ValueError):
            build_snapshot(self.bodies, NOW, evidence=self.evidence, omit_books=True)
        bodies = self.bodies[:]
        bodies[7] = ''
        value = build_snapshot(bodies, NOW, evidence=self.evidence, omit_books=True)
        for mutate in (lambda a:a['boxes'][7].update(omitted='true'),
                       lambda a:a['boxes'][7].pop('omitted'),
                       lambda a:a['boxes'][7].update(omissionReason='arbitrary'),
                       lambda a:a['boxes'][7].update(sha256='bad'),
                       lambda a:a['boxes'][7].update(body='stale text'),
                       lambda a:a['boxes'][0].update(omitted=True, omissionReason='source_unavailable'),
                       lambda a:a['boxes'][7].update(number=7, key='metalcoin')):
            bad = copy.deepcopy(value)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_snapshot(self.resign(bad), NOW)

    def test_contract_imports_no_collector_or_network_modules(self):
        import ast
        import morning_briefing_contract as contract
        tree = ast.parse(Path(contract.__file__).read_text(encoding='utf-8'))
        names = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                  for alias in node.names]
        self.assertFalse(any(name and name.split('.')[0] in ('requests','yes24_books','bs4','pathlib')
                             for name in names))

    def test_explicit_verified_zero_subscriptions_allowed(self):
        bodies = self.bodies[:]
        bodies[3] = HEAD + '청약 소식\n\n🏗️ 청약 접수 단지 (전국, 2주 이내)\n\n(2주 이내 접수 예정인 단지가 없습니다)\n'
        # The real collector's complete empty result is shorter than 80 chars.
        self.assertLess(len(bodies[3].strip()), 80)
        build_snapshot(bodies, NOW, evidence=self.evidence)

    def test_partial_zodiac_weather_coins_and_books_rejected(self):
        for index, old, new in ((0, '〈쥐띠〉', '〈누락〉'), (1, '✫서울(', '✫가짜('),
                                (6, '비트코인 1,000원', '코인 미확인'),
                                (7, '10. 검증된 도서 제목 10', '도서 누락')):
            bodies = self.bodies[:]
            bodies[index] = bodies[index].replace(old, new)
            with self.assertRaises(ValueError):
                build_snapshot(bodies, NOW, evidence=self.evidence)

    def test_insufficient_and_impolite_quick_news_rejected(self):
        for body in (self.bodies[2].replace('확인했습니다.', '확인했다.'),
                     '\n'.join(self.bodies[2].splitlines()[:8])):
            bodies = self.bodies[:]
            bodies[2] = body
            with self.assertRaises(ValueError):
                build_snapshot(bodies, NOW, evidence=self.evidence)

    def test_fallback_markers_cannot_be_today_ready(self):
        for marker in ('직전 정상값', '수집 실패', '확인 불가', '아직 찾지 못했습니다'):
            bodies = self.bodies[:]
            bodies[5] += '\n' + marker
            with self.assertRaises(ValueError):
                build_snapshot(bodies, NOW, evidence=self.evidence)

    def test_weekly_period_and_weekly_check_clock_preserved(self):
        for updates in (dict(booksPeriodEnd='2026-10-19'),
                        dict(booksPeriodStart='2026-09-28', booksPeriodEnd='2026-10-04'),
                        dict(trendCheckedAtKst=(NOW - timedelta(days=9)).isoformat())):
            with self.assertRaises(ValueError):
                build_snapshot(self.bodies, NOW, evidence={**self.evidence, **updates})
        valid = {**self.evidence, 'trendCheckedAtKst': (NOW - timedelta(days=7)).isoformat()}
        self.assertEqual(build_snapshot(self.bodies, NOW, evidence=valid)['evidence'], valid)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / 'morning-briefing-ready.json'
        self.report = self.root / 'morning-briefing-report.json'
        write_sources(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def run_prepare(self, **kwargs):
        return cloud.prepare(self.root, self.output, self.report, now=NOW, **kwargs)

    def runner(self, command, **kwargs):
        script = command[-1]
        group = next(row for row in cloud.GROUPS if row[1] == script)
        bodies, _, trend = fixture_sources()
        for key in group[2]:
            for filename in (f'{key}.txt', f'{key}-wed.txt'):
                (self.root / filename).write_text(bodies[BOX_KEYS.index(key)], encoding='utf-8')
        if 'trend' in group[2]:
            (self.root / 'neonet-trend-cache.json').write_text(json.dumps(trend), encoding='utf-8')
        self.assertLessEqual(kwargs['timeout'], 180)
        self.assertTrue(kwargs['capture_output'])
        return subprocess.CompletedProcess(command, 0, stdout=b'not logged', stderr=b'not logged')

    def test_export_collects_nothing_and_exposes_no_host_details(self):
        with patch.object(subprocess, 'run', side_effect=AssertionError('no collection')):
            report = self.run_prepare()
        self.assertEqual(report['status'], 'ok')
        content = self.output.read_text(encoding='utf-8')
        self.assertNotIn(str(self.root), content)
        snapshot = json.loads(content)
        self.assertEqual(set(snapshot), {'schemaVersion', 'deliveryDateKst', 'generatedAtKst',
                                        'expiresAtKst', 'boxes', 'evidence', 'snapshotSha256'})
        self.assertEqual(validate_snapshot(snapshot, NOW), [body.strip() for body in fixture_sources()[0]])

    def test_export_failure_replaces_ready_with_only_that_slot_omitted(self):
        self.run_prepare()
        before = self.output.read_bytes()
        (self.root / 'weather-wed.txt').write_text('수집 실패', encoding='utf-8')
        report = self.run_prepare()
        self.assertEqual(report['status'], 'ok')
        self.assertTrue(report['websiteWritten'])
        self.assertNotIn('weather', report['websiteKeys'])
        self.assertNotEqual(self.output.read_bytes(), before)
        self.assertEqual(validate_snapshot(json.loads(self.output.read_text(encoding='utf-8')), NOW)[1], '')

    def test_cloud_collection_six_groups_no_duplicate_book_fetch(self):
        calls = []
        def runner(command, **kwargs):
            calls.append(command[-1])
            return self.runner(command, **kwargs)
        report = self.run_prepare(collect=True, runner=runner)
        self.assertEqual(report['status'], 'ok', report)
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls.count('market_fetch.py'), 1)
        self.assertNotIn('yes24_books.py', calls)
        self.assertTrue(all(row['status'] == 'ok' for row in report['groups']))

    def test_failed_raw_body_restored_but_only_failed_slot_omitted_from_ready(self):
        self.run_prepare()
        previous = self.output.read_bytes()
        original = (self.root / 'fortune.txt').read_bytes()
        def runner(command, **kwargs):
            result = self.runner(command, **kwargs)
            if command[-1] == 'fortune_fetch.py':
                for name in ('fortune.txt', 'fortune-wed.txt'):
                    (self.root / name).write_text('오늘의 운세, 10월 21일\n수집 실패', encoding='utf-8')
            return result
        report = self.run_prepare(collect=True, runner=runner)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['groups'][0]['reason'], 'source_validation_failed')
        self.assertEqual((self.root / 'fortune.txt').read_bytes(), original)
        self.assertNotEqual(self.output.read_bytes(), previous)
        self.assertEqual(report['omittedKeys'], ['fortune'])

    def test_zero_exit_without_written_source_is_not_success(self):
        runner = lambda command, **kwargs: subprocess.CompletedProcess(command, 0)
        report = self.run_prepare(collect=True, runner=runner)
        self.assertEqual(report['status'], 'ok')
        self.assertTrue(report['snapshotWritten'])
        self.assertEqual(report['websiteKeys'], ['books'])
        self.assertTrue(all(row['reason'] == 'collector_did_not_refresh_required_source'
                            for row in report['groups']))

    def test_missing_books_write_keeps_market_daily_updates_and_weekly_cache(self):
        original = fixture_sources()[0][7].replace('10월 21일', '10월 20일')
        for name in ('books.txt', 'books-wed.txt'):
            (self.root/name).write_text(original, encoding='utf-8')
        # Rewriting the same bytes still counts as a write; emulate actual
        # maintenance by leaving the cached book files entirely untouched.
        def maintenance_runner(command, **kwargs):
            if command[-1] != 'market_fetch.py':
                return self.runner(command, **kwargs)
            bodies = fixture_sources()[0]
            for key in ('fuelfx','metalcoin'):
                for name in (f'{key}.txt',f'{key}-wed.txt'):
                    (self.root/name).write_text(bodies[BOX_KEYS.index(key)]+'\n',encoding='utf-8')
            return subprocess.CompletedProcess(command,0)
        report = self.run_prepare(collect=True, runner=maintenance_runner)
        self.assertEqual(report['status'], 'ok')
        self.assertTrue(report['snapshotWritten'])
        self.assertEqual(len(report['websiteKeys']),9)
        market = next(group for group in report['groups'] if group['group']=='market')
        self.assertEqual(market['status'],'ok')
        self.assertEqual(next(box for box in market['boxes'] if box['key']=='books')['status'],'retained_weekly')
        self.assertEqual((self.root/'books.txt').read_text(encoding='utf-8'),original)

    def test_one_market_box_failure_does_not_restore_other_healthy_market_boxes(self):
        old = (self.root/'fuelfx.txt').read_bytes()
        def runner(command, **kwargs):
            result = self.runner(command, **kwargs)
            if command[-1]=='market_fetch.py':
                for name in ('fuelfx.txt','fuelfx-wed.txt'):
                    (self.root/name).write_text('수집 실패',encoding='utf-8')
                for name in ('metalcoin.txt','metalcoin-wed.txt'):
                    with (self.root/name).open('a',encoding='utf-8') as handle:
                        handle.write('\n정상 수집 검증\n')
            return result
        report = self.run_prepare(collect=True,runner=runner)
        self.assertEqual(report['status'],'ok')
        self.assertTrue(report['snapshotWritten'])
        self.assertEqual(report['omittedKeys'], ['fuelfx'])
        self.assertEqual((self.root/'fuelfx.txt').read_bytes(),old)
        self.assertIn('정상 수집 검증',(self.root/'metalcoin.txt').read_text(encoding='utf-8'))
        self.assertNotIn('fuelfx',report['websiteKeys'])
        self.assertIn('metalcoin',report['websiteKeys'])

    def test_unavailable_books_only_is_omitted_and_eight_sources_are_ready(self):
        self.run_prepare()
        def runner(command, **kwargs):
            result = self.runner(command, **kwargs)
            if command[-1] == 'market_fetch.py':
                for name in ('books.txt','books-wed.txt'):
                    (self.root/name).write_text('수집 실패', encoding='utf-8')
                # Remove the usable old copy too, so no verified week is left.
                for name in ('books.txt','books-wed.txt'):
                    original = fixture_sources()[0][7].replace('10월 21일', '10월 19일')
                    (self.root/name).write_text(original, encoding='utf-8')
            return result
        # The backup also contains an out-of-policy (two-day-old) source.
        old = fixture_sources()[0][7].replace('10월 21일', '10월 19일')
        for name in ('books.txt','books-wed.txt'):
            (self.root/name).write_text(old, encoding='utf-8')
        report = self.run_prepare(collect=True, runner=runner)
        self.assertEqual(report['status'], 'ok', report)
        self.assertTrue(report['snapshotWritten'])
        self.assertEqual(report['omittedKeys'], ['books'])
        self.assertNotIn('books', report['websiteKeys'])
        snapshot = json.loads(self.output.read_text(encoding='utf-8'))
        self.assertEqual(validate_snapshot(snapshot, NOW)[7], '')
        self.assertTrue(snapshot['boxes'][7]['omitted'])
        self.assertNotIn('booksPeriodStart', snapshot['evidence'])
        self.assertEqual((self.root/'books.txt').read_text(encoding='utf-8'), old)

    def test_export_missing_books_and_weather_both_are_independently_omitted(self):
        for name in ('books.txt','books-wed.txt'):
            (self.root/name).write_text('자료 없음', encoding='utf-8')
        report = self.run_prepare()
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['omittedKeys'], ['books'])
        previous = self.output.read_bytes()
        (self.root/'weather-wed.txt').write_text('수집 실패', encoding='utf-8')
        report = self.run_prepare()
        self.assertEqual(report['status'], 'ok')
        self.assertTrue(report['snapshotWritten'])
        self.assertNotEqual(self.output.read_bytes(), previous)
        self.assertEqual(report['omittedKeys'], ['weather', 'books'])

    def test_timeout_and_sensitive_process_output_not_echoed(self):
        secret = 'test-secret-no-print'
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1, output=secret.encode())
        report = self.run_prepare(collect=True, runner=runner)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['websiteKeys'], ['books'])
        self.assertNotIn(secret, self.report.read_text(encoding='utf-8'))
        self.assertTrue(all(row['reason'] == 'collector_timeout' for row in report['groups']))

    def test_global_deadline_and_three_worker_limit(self):
        active = peak = 0
        lock = threading.Lock()
        def runner(command, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.015)
            try:
                return self.runner(command, **kwargs)
            finally:
                with lock:
                    active -= 1
        self.assertEqual(self.run_prepare(collect=True, runner=runner)['status'], 'ok')
        self.assertLessEqual(peak, 3)
        for kwargs in (dict(deadline_seconds=271), dict(max_workers=4)):
            with self.assertRaises(ValueError):
                self.run_prepare(collect=True, runner=runner, **kwargs)

    def test_live_collection_refused_on_delivery_pc(self):
        with patch.object(cloud, 'collection_allowed', return_value=False), \
                patch.object(subprocess, 'run') as collector:
            with self.assertRaises(ValueError):
                self.run_prepare(collect=True)
            collector.assert_not_called()

    def test_cli_requires_explicit_mode(self):
        with self.assertRaises(SystemExit):
            cloud.main([])


if __name__ == '__main__':
    unittest.main()
