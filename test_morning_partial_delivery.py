"""Source failures never block the healthy morning subset; no live collection."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import morning_cloud_prepare as cloud
import morning_briefing_contract as contract
from morning_source_publication import apply_collection, build_publication
from test_morning_cloud_prepare import NOW, fixture_sources, write_sources


class PartialMorningTests(unittest.TestCase):
    def setUp(self):
        self.bodies, self.evidence, self.trend = fixture_sources()

    def test_each_source_failure_at_0620_preserves_other_eight_and_numbering(self):
        send_at = NOW.replace(hour=6, minute=20)
        for missing in contract.BOX_KEYS:
            with self.subTest(missing=missing):
                bodies = self.bodies.copy()
                index = contract.BOX_KEYS.index(missing)
                bodies[index] = ''
                snapshot = contract.build_snapshot(bodies, NOW, evidence=self.evidence, omitted_keys=[missing])
                self.assertEqual(contract.validate_snapshot(snapshot, send_at), bodies)
                self.assertEqual(contract.available_bodies(snapshot, send_at), bodies)
                self.assertEqual([box['number'] for box in snapshot['boxes']], list(range(1, 10)))
                self.assertEqual(sum(bool(body) for body in bodies), 8)

    def test_individual_bad_body_clock_or_weekly_evidence_is_not_a_global_failure(self):
        for index in range(9):
            for failure in ('body', 'clock', 'hash'):
                with self.subTest(index=index, failure=failure):
                    snapshot = contract.build_snapshot(self.bodies, NOW, evidence=self.evidence)
                    box = snapshot['boxes'][index]
                    if failure == 'body':
                        box['body'] = '수집 실패'
                        box['sha256'] = contract.body_sha256(box['body'])
                    elif failure == 'clock':
                        box['checkedAtKst'] = (NOW-timedelta(days=1)).isoformat()
                    else:
                        box['sha256'] = 'incorrect'
                    snapshot['snapshotSha256'] = contract.snapshot_sha256(snapshot)
                    expected = self.bodies.copy(); expected[index] = ''
                    self.assertEqual(contract.available_bodies(snapshot, NOW), expected)
        snapshot = contract.build_snapshot(self.bodies, NOW, evidence=self.evidence)
        snapshot['evidence'] = {}
        snapshot['snapshotSha256'] = contract.snapshot_sha256(snapshot)
        expected = self.bodies.copy(); expected[4] = expected[7] = ''
        self.assertEqual(contract.available_bodies(snapshot, NOW), expected)

    def test_invalid_envelope_and_all_missing_remain_rejected(self):
        original = contract.build_snapshot(self.bodies, NOW, evidence=self.evidence)
        for changes in ({'schemaVersion': 2}, {'deliveryDateKst': '2026-10-20'},
                        {'expiresAtKst': '2026-10-25T00:00:00+09:00'},
                        {'generatedAtKst': (NOW-timedelta(hours=5)).isoformat()},
                        {'boxes': list(reversed(original['boxes']))}):
            snapshot = deepcopy(original); snapshot.update(changes)
            snapshot['snapshotSha256'] = contract.snapshot_sha256(snapshot)
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                contract.available_bodies(snapshot, NOW)
        original['snapshotSha256'] = 'incorrect'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            contract.available_bodies(original, NOW)
        with self.assertRaisesRegex(ValueError, 'no available'):
            contract.build_snapshot(['']*9, NOW, evidence={}, omitted_keys=contract.BOX_KEYS)

    def test_multiple_failures_including_trend_publish_without_cache_or_old_file_erasure(self):
        omitted = ['fortune', 'trend', 'metalcoin', 'books']
        bodies = [body if key not in omitted else '' for key, body in zip(contract.BOX_KEYS, self.bodies)]
        snapshot = contract.build_snapshot(bodies, NOW, evidence=self.evidence, omitted_keys=omitted)
        publication = build_publication(bodies, NOW, evidence=snapshot['evidence'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'fortune.txt').write_text('preserved original', encoding='utf-8')
            (root/'neonet-trend-cache.json').write_text('preserved original cache', encoding='utf-8')
            source = root/'publication.json'; source.write_text(json.dumps(publication), encoding='utf-8')
            ready = root/'ready.json'; ready.write_text(json.dumps(snapshot), encoding='utf-8')
            result = apply_collection(source, snapshot_path=ready, root=root, now=NOW)
            self.assertEqual(result, dict(websiteApplied=True, readyApplied=True))
            self.assertEqual((root/'fortune.txt').read_text(encoding='utf-8'), 'preserved original')
            self.assertEqual((root/'neonet-trend-cache.json').read_text(encoding='utf-8'), 'preserved original cache')
            self.assertEqual(contract.validate_snapshot(json.loads((root/'morning-briefing-ready.json').read_text(encoding='utf-8')), NOW), bodies)

    def test_nonzero_or_timeout_after_one_market_output_keeps_that_output(self):
        for outcome in ('nonzero', 'timeout'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); write_sources(root)
                # Neither current nor yesterday books is available for fallback.
                for name in ('books.txt', 'books-wed.txt'):
                    (root/name).write_text('자료 없음', encoding='utf-8')
                def runner(command, **kwargs):
                    group = next(group for group in cloud.GROUPS if group[1] == command[-1])
                    keys = ('fuelfx',) if group[0] == 'market' else group[2]
                    for key in keys:
                        for name in (f'{key}.txt', f'{key}-wed.txt'):
                            (root/name).write_text(self.bodies[contract.BOX_KEYS.index(key)]+'\n', encoding='utf-8')
                    if 'trend' in keys:
                        (root/'neonet-trend-cache.json').write_text(json.dumps(self.trend), encoding='utf-8')
                    if group[0] == 'market':
                        if outcome == 'timeout':
                            raise subprocess.TimeoutExpired(command, 1)
                        return subprocess.CompletedProcess(command, 1)
                    return subprocess.CompletedProcess(command, 0)
                ready = root/'morning-briefing-ready.json'
                result = cloud.prepare(root, ready, root/'report.json', collect=True, now=NOW, runner=runner)
                self.assertTrue(result['snapshotWritten'])
                self.assertEqual(result['omittedKeys'], ['metalcoin', 'books'])
                blocks = contract.validate_snapshot(json.loads(ready.read_text(encoding='utf-8')), NOW)
                self.assertTrue(blocks[5]); self.assertEqual(blocks[6:8], ['', ''])

    def test_every_export_failure_is_omitted_and_all_failed_preserves_original(self):
        for missing in contract.BOX_KEYS:
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); write_sources(root)
                for path in root.glob(missing+'*.txt'):
                    path.write_text('수집 실패', encoding='utf-8')
                if missing == 'trend':
                    (root/'neonet-trend-cache.json').write_text('{}', encoding='utf-8')
                ready = root/'morning-briefing-ready.json'
                result = cloud.prepare(root, ready, root/'report.json', now=NOW)
                self.assertTrue(result['snapshotWritten'])
                self.assertEqual(result['omittedKeys'], [missing])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root/'morning-briefing-ready.json'; ready.write_bytes(b'old ready')
            result = cloud.prepare(root, ready, root/'report.json', now=NOW)
            self.assertFalse(result['snapshotWritten'])
            self.assertEqual(ready.read_bytes(), b'old ready')


if __name__ == '__main__':
    unittest.main()
