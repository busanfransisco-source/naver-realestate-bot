import copy
from datetime import timedelta
from html import escape
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from morning_briefing_contract import BOX_KEYS, build_snapshot
import morning_cloud_prepare as cloud
from publish_morning_ready import apply_bundle
from test_morning_cloud_prepare import NOW, fixture_sources, write_sources
from verify_morning_publication import verify_pair, verify_publication


def page(bodies):
    return '\n'.join(f'<section class="card"><h2>{n}. {key}</h2>'
                     f'<button class="copy-btn" onclick="copySection(\'{key}\', this)"></button>'
                     f'<textarea id="ta-{key}">{escape(body)}</textarea></section>'
                     for n, (key, body) in enumerate(zip(BOX_KEYS, bodies), 1)) + "document.getElementById('ta-' + key)"


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'artifact'
        self.inputs.mkdir()
        self.bodies, self.evidence, self.trend = fixture_sources()
        self.snapshot = build_snapshot(self.bodies, NOW, evidence=self.evidence)
        self.source = self.inputs / 'morning-briefing-ready.json'
        self.cache = self.inputs / 'neonet-trend-cache.json'
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.source.write_text(json.dumps(self.snapshot), encoding='utf-8')
        self.cache.write_text(json.dumps(self.trend), encoding='utf-8')

    def test_apply_only_approved_files_and_preserve_weekly_period(self):
        self.assertTrue(apply_bundle(self.source, self.cache, root=self.root, now=NOW))
        for key, body in zip(BOX_KEYS, self.bodies):
            self.assertEqual((self.root / f'{key}.txt').read_text(encoding='utf-8').strip(), body.strip())
            self.assertEqual((self.root / f'{key}-wed.txt').read_text(encoding='utf-8').strip(), body.strip())
        self.assertIn('2026-10-12 ~ 2026-10-18', (self.root / 'books.txt').read_text(encoding='utf-8'))
        self.assertFalse((self.root / 'artifact' / '.env').exists())
        self.assertFalse(list(self.root.glob('*.morning-tmp')))

    def test_invalid_artifact_changes_nothing(self):
        (self.root / 'fortune.txt').write_text('preserve', encoding='utf-8')
        self.snapshot['boxes'][0]['body'] = 'changed without hash'
        self.save()
        with self.assertRaises(ValueError):
            apply_bundle(self.source, self.cache, root=self.root, now=NOW)
        self.assertEqual((self.root / 'fortune.txt').read_text(encoding='utf-8'), 'preserve')
        self.assertFalse((self.root / 'morning-briefing-ready.json').exists())

    def test_cache_body_must_match(self):
        self.trend['data']['national']['sale'] = '-0.99'
        self.save()
        with self.assertRaises(ValueError):
            apply_bundle(self.source, self.cache, root=self.root, now=NOW)
        self.assertFalse((self.root / 'fortune.txt').exists())

    def test_newer_existing_bundle_is_not_regressed(self):
        new = build_snapshot(self.bodies, NOW + timedelta(minutes=1), evidence=self.evidence)
        target = self.root / 'morning-briefing-ready.json'
        target.write_text(json.dumps(new), encoding='utf-8')
        before = target.read_bytes()
        self.assertFalse(apply_bundle(self.source, self.cache, root=self.root, now=NOW + timedelta(minutes=2)))
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse((self.root / 'fortune.txt').exists())

    def test_page_and_copy_fields_match(self):
        self.assertEqual(verify_pair(self.snapshot, page(self.bodies), self.snapshot, NOW), self.snapshot['snapshotSha256'])
        for html in (page(self.bodies).replace('ta-fortune', 'ta-wrong'),
                     page(self.bodies).replace("copySection('fortune',", "copySection('weather',"),
                     page(self.bodies).replace('<h2>1.', '<h2>2.')):
            with self.assertRaises(ValueError):
                verify_pair(self.snapshot, html, self.snapshot, NOW)

    def test_old_public_bundle_rejected(self):
        new = build_snapshot(self.bodies, NOW + timedelta(minutes=1), evidence=self.evidence)
        with self.assertRaises(ValueError):
            verify_pair(self.snapshot, page(self.bodies), new, NOW + timedelta(minutes=2))

    def test_public_read_uses_cache_busting_and_no_messages(self):
        class Response:
            content = b'public'
            text = page(self.bodies)
            def raise_for_status(self): pass
            def json(inner): return self.snapshot
        calls = []
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return Response()
        verify_publication(self.snapshot, get=get, now_fn=lambda: NOW, timeout=0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all('morningVerify' in kw['params'] for _, kw in calls))

    def test_source_group_checks_completion_clock_not_start(self):
        write_sources(self.root)
        group = cloud.GROUPS[3]
        later = NOW + timedelta(seconds=30)
        def runner(*args, **kwargs):
            self.trend['checkedAtKst'] = later.isoformat()
            from neonet_trend import format_digest
            for name, text in (('subs.txt', self.bodies[3]), ('subs-wed.txt', self.bodies[3]),
                               ('neonet-trend-cache.json', json.dumps(self.trend))):
                (self.root / name).write_text(text, encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        import time
        with patch.object(cloud, 'datetime') as clock:
            clock.now.return_value = later
            from datetime import datetime
            clock.fromisoformat.side_effect = datetime.fromisoformat
            result = cloud._run_group(self.root, group, NOW, time.monotonic() + 50, runner)
        self.assertEqual(result['status'], 'ok', result)


if __name__ == '__main__':
    unittest.main()
