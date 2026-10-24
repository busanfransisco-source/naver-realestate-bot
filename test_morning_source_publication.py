import copy
from datetime import timedelta
from html import escape
import json
from pathlib import Path
import tempfile
import unittest

from morning_briefing_contract import BOX_KEYS, validate_snapshot
from morning_source_publication import (
    OUTPUT, apply_publication, build_publication, publication_sha256,
    validate_publication, verify_publication, verify_publication_page,
)
from test_morning_cloud_prepare import NOW, fixture_sources


def page(boxes):
    return '\n'.join(
        f'<section class="card" data-slot="{box["number"]}">'
        f'<button class="copy-btn" onclick="copySection(\'{box["key"]}\', this)"></button>'
        f'<textarea id="ta-{box["key"]}">{escape(box["body"])}</textarea></section>'
        f'<script>window.__content_{box["key"]} = {json.dumps(box["body"], ensure_ascii=False)};</script>'
        for box in boxes)


class MorningSourcePublicationTests(unittest.TestCase):
    def setUp(self):
        self.bodies, self.evidence, self.trend = fixture_sources()

    def build(self, **kwargs):
        return build_publication(self.bodies, NOW, evidence=self.evidence, **kwargs)

    def resign(self, artifact):
        artifact['publicationSha256'] = publication_sha256(artifact)
        return artifact

    def test_missing_one_daily_box_keeps_other_eight_without_sender_ready(self):
        self.bodies[1] = '수집 실패'
        artifact = self.build()
        self.assertEqual(len(validate_publication(artifact, NOW)), 8)
        self.assertNotIn('weather', [box['key'] for box in artifact['boxes']])
        self.assertEqual([box['number'] for box in artifact['boxes']], [1,3,4,5,6,7,8,9])
        with self.assertRaises(ValueError):
            validate_snapshot(artifact, NOW)

    def test_cached_valid_weekly_books_keep_real_header_period_and_mode(self):
        self.bodies[7] = self.bodies[7].replace('10월 21일', '10월 20일')
        artifact = self.build()
        box = next(box for box in artifact['boxes'] if box['key']=='books')
        self.assertEqual(box['body'], self.bodies[7])
        self.assertEqual(box['sourceMode'], 'retained_weekly')
        self.assertIn('2026-10-12 ~ 2026-10-18', box['body'])
        self.assertNotIn('10월 21일', box['body'])

    def test_stale_daily_header_not_relabelled_or_included(self):
        self.bodies[2] = self.bodies[2].replace('10월 21일', '10월 20일')
        artifact = self.build()
        self.assertNotIn('shortnews', [box['key'] for box in artifact['boxes']])

    def test_stale_weekly_books_excluded_and_no_sources_rejected(self):
        self.bodies[7] = self.bodies[7].replace('10월 21일', '10월 7일').replace(
            '2026-10-12 ~ 2026-10-18', '2026-09-28 ~ 2026-10-04')
        artifact = self.build()
        self.assertNotIn('books', [box['key'] for box in artifact['boxes']])
        with self.assertRaises(ValueError):
            self.build(eligible_keys=[])

    def test_eligible_keys_prevent_unchanged_daily_source_promotion(self):
        artifact = self.build(eligible_keys=['weather', 'books'])
        self.assertEqual([box['key'] for box in artifact['boxes']], ['weather','books'])
        with self.assertRaises(ValueError):
            self.build(eligible_keys=['analysis7'])

    def test_corrupt_hash_number_duplicate_future_expiry_rejected(self):
        artifact = self.build()
        for mutate in (lambda a:a['boxes'][0].update(body='changed'),
                       lambda a:a['boxes'][0].update(number=2),
                       lambda a:a['boxes'].append(a['boxes'][0]),
                       lambda a:a.update(expiresAtKst=(NOW+timedelta(days=3)).isoformat()),
                       lambda a:a['boxes'][7].update(sourceMode='retained_weekly')):
            bad=copy.deepcopy(artifact)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_publication(self.resign(bad), NOW)
        for now in (NOW-timedelta(seconds=1), NOW+timedelta(hours=4,seconds=1), NOW+timedelta(days=1)):
            with self.assertRaises(ValueError):
                validate_publication(artifact,now)

    def test_apply_preserves_failed_sources_other_boxes_and_strict_ready(self):
        artifact = self.build(eligible_keys=['weather','books'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'artifact.json'
            source.write_text(json.dumps(artifact),encoding='utf-8')
            for name in ('morning-briefing-ready.json','fortune.txt','analysis7-wed.txt','transactions.txt'):
                (root/name).write_text('preserve',encoding='utf-8')
            self.assertTrue(apply_publication(source,root=root,now=NOW))
            for name in ('morning-briefing-ready.json','fortune.txt','analysis7-wed.txt','transactions.txt'):
                self.assertEqual((root/name).read_text(encoding='utf-8'),'preserve')
            self.assertEqual((root/'books.txt').read_text(encoding='utf-8'), self.bodies[7])
            self.assertEqual((root/'weather-wed.txt').read_text(encoding='utf-8'), self.bodies[1])
            self.assertFalse(apply_publication(source,root=root,now=NOW))
            self.assertFalse(list(root.glob('*.morning-web-tmp')))

    def test_apply_validates_cache_before_any_write(self):
        artifact=self.build()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'artifact.json'
            source.write_text(json.dumps(artifact),encoding='utf-8')
            cache=root/'trend-input.json'
            changed=copy.deepcopy(self.trend)
            changed['data']['national']['sale']='-0.99'
            cache.write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaises(ValueError):
                apply_publication(source,cache,root=root,now=NOW)
            self.assertFalse((root/'fortune.txt').exists())
            self.assertFalse((root/OUTPUT).exists())

    def test_public_textarea_clipboard_and_slot_must_match(self):
        artifact=self.build(eligible_keys=['weather','books'])
        html=page(artifact['boxes'])
        self.assertEqual(verify_publication_page(artifact,html,NOW),artifact['publicationSha256'])
        for bad in (html.replace('ta-weather','ta-fortune'),
                    html.replace('data-slot="2"','data-slot="3"'),
                    html.replace("copySection('weather',","copySection('fortune',"),
                    html.replace('window.__content_weather = ','window.__content_fortune = ')):
            with self.assertRaises(ValueError):
                verify_publication_page(artifact,bad,NOW)

    def test_public_network_verification_cache_busts_and_reads_only(self):
        artifact=self.build(eligible_keys=['weather','books'])
        html=page(artifact['boxes'])
        class Response:
            content=b'public'
            text=html
            def raise_for_status(self):
                pass
            def json(self):
                return artifact
        calls=[]
        def get(url,**kwargs):
            calls.append((url,kwargs))
            return Response()
        self.assertEqual(verify_publication(artifact,get=get,now_fn=lambda:NOW,timeout=0),
                         artifact['publicationSha256'])
        self.assertEqual(len(calls),2)
        self.assertTrue(all('morningSourceVerify' in kwargs['params'] for _,kwargs in calls))
        self.assertTrue(all(kwargs['headers']['Cache-Control']=='no-cache' for _,kwargs in calls))

    def test_public_verification_timeout_is_bounded_and_diagnostics_safe(self):
        import requests
        artifact=self.build(eligible_keys=['weather'])
        calls=[]
        def get(url,**kwargs):
            calls.append(url)
            raise requests.Timeout('private URL or credentials never echo')
        with self.assertRaisesRegex(ValueError,'did not complete before deadline') as error:
            verify_publication(artifact,get=get,now_fn=lambda:NOW,timeout=0)
        self.assertEqual(len(calls),1)
        self.assertNotIn('private',str(error.exception))
        with self.assertRaises(ValueError):
            verify_publication(artifact,timeout=121)


if __name__=='__main__':
    unittest.main()
