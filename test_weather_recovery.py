import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from bs4 import BeautifulSoup

import weather_fetch as weather
import gen_briefing
import briefing_health

NOW = datetime(2026, 11, 14, 21, 35, tzinfo=weather.KST)


def response(day=NOW.date()):
    return [dict(daily=dict(time=[day.isoformat()], temperature_2m_min=[9.1], temperature_2m_max=[15.2]),
                 hourly=dict(time=[f'{day.isoformat()}T{h:02d}:00' for h in range(24)],
                             weather_code=[3] * 24)) for _ in weather.CITIES]


def report(day=NOW):
    with patch.object(weather, 'fetch_all_cities', return_value=response(day.date())):
        return weather.build_report(day)


class WeatherRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def run_main(self, payload=None, error=None):
        with patch.object(weather, 'datetime') as clock, patch.object(weather, 'fetch_all_cities', return_value=payload, side_effect=error):
            clock.now.return_value = NOW
            return weather.main()

    def test_timeout_preserves_exact_bytes_and_mtimes_and_returns_failure(self):
        original = report()
        paths = [Path(p) for p in ('weather.txt', 'weather-sat.txt', 'weather-2026-11-14.txt')]
        for path in paths:
            path.write_text(original)
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        self.assertEqual(self.run_main(error=TimeoutError('timeout')), 1)
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])
        visible = weather.load_report(NOW)
        self.assertEqual(visible, weather.DELAY_NOTICE + '\n' + original)
        self.assertEqual(json.loads(Path('weather-status.txt').read_text())['status'], 'failed')

    def test_success_recovers_and_clears_delay_without_extra_requests(self):
        self.run_main(error=TimeoutError())
        self.assertEqual(self.run_main(payload=response()), 0)
        self.assertFalse(weather.load_report(NOW).startswith(weather.DELAY_NOTICE))
        self.assertIn('출처: Open-Meteo · 예보 기준일: 2026-11-14', weather.load_report(NOW))
        self.assertIn('실제 조회시각(KST): 2026-11-14T21:35:00+09:00', weather.load_report(NOW))

    def test_bad_response_never_overwrites_valid_report(self):
        good = report()
        mutations = [response()[:-1], response(NOW.date()-timedelta(days=1))]
        for change in ('temperature', 'hours', 'null_code', 'order', 'nan'):
            data = copy.deepcopy(response())
            if change == 'temperature': data[0]['daily']['temperature_2m_min'] = [None]
            elif change == 'hours': data[0]['hourly']['time'] = []
            elif change == 'null_code': data[0]['hourly']['weather_code'][6] = None
            elif change == 'order': data[0]['daily']['temperature_2m_min'] = [100]
            else: data[0]['daily']['temperature_2m_max'] = [float('nan')]
            mutations.append(data)
        for data in mutations:
            with self.subTest(data=data[0]):
                Path('weather.txt').write_text(good)
                self.assertEqual(self.run_main(payload=data), 1)
                self.assertEqual(Path('weather.txt').read_text(), good)

    def test_missing_today_never_reuses_prior_day_or_future(self):
        for day in (NOW-timedelta(days=2), NOW+timedelta(days=1)):
            for path in ('weather.txt', 'weather-sat.txt', 'weather-thu.txt', 'weather-2026-11-14.txt'):
                Path(path).write_text(report(day))
            self.assertEqual(gen_briefing.read_section_text('weather', 'sat', NOW), weather.UNAVAILABLE)

    def test_dated_today_wins_over_failed_aliases_legacy_bytes_unchanged(self):
        legacy = report().split('\n\n출처:')[0]
        Path('weather-2026-11-14.txt').write_text(legacy)
        Path('weather.txt').write_text('(날씨 데이터를 가져오지 못했습니다)')
        Path('weather-sat.txt').write_text(report(NOW-timedelta(days=7)))
        self.assertEqual(weather.load_report(NOW), legacy)
        self.assertNotIn('실제 조회시각', weather.load_report(NOW))

    def test_partial_or_duplicate_cities_rejected(self):
        for body in (report().replace('✫제주', '✫부산'), report().replace('✫제주(☁️)➠(☁️)  9℃ ~ 15℃', '')):
            self.assertFalse(weather.valid_report(body, NOW.date()))

    def test_html_copy_and_health_show_same_delay(self):
        Path('weather.txt').write_text(report())
        self.run_main(error=TimeoutError())
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW
        with patch.object(gen_briefing, 'datetime', FrozenDateTime):
            page = gen_briefing.build_html(new_data_contents={k: '검증용 자료' for k, _ in gen_briefing.NEW_DATA_SECTIONS})
        soup = BeautifulSoup(page, 'html.parser')
        body = soup.select_one('#ta-weather').get_text().strip()
        self.assertEqual(body, weather.load_report(NOW))
        self.assertEqual(len(soup.select('section.card')), 30)
        self.assertIn(weather.DELAY_NOTICE, soup.select_one('#card2').get_text() if soup.select_one('#card2') else soup.select_one('#ta-weather').find_parent('section').get_text())
        row = next(r for r in briefing_health.inspect(page, NOW) if r['key'] == 'weather')
        self.assertEqual(row['status'], 'failed')
        self.assertIn('weather: latest collection failed; same-day forecast retained', row['issues'])

    def test_status_file_uses_existing_commit_patterns(self):
        root = Path(__file__).resolve().parent
        for name in ('weather', 'manual-briefing', 'morning-briefing', 'naver-realestate'):
            workflow = (root / '.github/workflows' / (name + '.yml')).read_text()
            self.assertTrue('weather-*.txt' in workflow or 'weather*.txt' in workflow)
        workflow = (root / '.github/workflows/weather.yml').read_text()
        self.assertIn('python weather_fetch.py || echo', workflow)
        self.assertIn('python briefing_health.py --url', workflow)

    def test_status_is_not_listed_as_forecast_in_index(self):
        import gen_index
        Path('weather-status.txt').write_text('{}')
        Path('weather-2026-11-14.txt').write_text(report())
        gen_index.main()
        for name in ('index.html', 'hub.html'):
            self.assertNotIn('weather-status.txt', Path(name).read_text())
            self.assertIn('weather-2026-11-14.txt', Path(name).read_text())

    def test_no_today_notice_fails_health(self):
        page = '<section class="card" data-slot="2"><textarea id="ta-weather">' + weather.UNAVAILABLE + '</textarea></section>'
        row = next(r for r in briefing_health.inspect(page, NOW) if r['key'] == 'weather')
        self.assertEqual(row['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
