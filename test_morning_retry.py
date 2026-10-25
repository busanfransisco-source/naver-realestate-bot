"""Bounded cloud recovery with immutable healthy siblings and visible errors."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import morning_cloud_prepare as cloud
from morning_briefing_contract import BOX_KEYS, validate_snapshot
from test_morning_cloud_prepare import NOW, fixture_sources, write_sources


class MorningRetryTests(unittest.TestCase):
    def test_transient_failure_recovers_and_preserves_error_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);write_sources(root)
            bodies, _, trend=fixture_sources()
            calls={group[1]:0 for group in cloud.GROUPS}
            def runner(command, **kwargs):
                script=command[-1];calls[script]+=1
                keys=next(group[2] for group in cloud.GROUPS if group[1]==script)
                for key in keys:
                    body=bodies[BOX_KEYS.index(key)]
                    if key=='weather' and calls[script]==1:
                        body='수집 실패'
                    for name in (key+'.txt',key+'-wed.txt'):
                        (root/name).write_text(body+'\n',encoding='utf-8')
                if 'trend' in keys:
                    (root/'neonet-trend-cache.json').write_text(json.dumps(trend),encoding='utf-8')
                return subprocess.CompletedProcess(command,0)
            sleep=Mock()
            ready=root/'ready.json'
            report=cloud.prepare(root,ready,root/'report.json',collect=True,now=NOW,runner=runner,sleeper=sleep)
            self.assertTrue(report['snapshotWritten'])
            self.assertEqual(report['omittedKeys'],[])
            self.assertEqual(report['sourceHealth'],'recovered')
            self.assertTrue(report['hadErrors'])
            self.assertEqual(calls['weather_fetch.py'],2)
            self.assertTrue(all(count==1 for name,count in calls.items() if name!='weather_fetch.py'))
            sleep.assert_called_once_with(10)
            weather=next(group for group in report['groups'] if group['group']=='weather')
            self.assertEqual([attempt['status'] for attempt in weather['attemptHistory']],['failed','ok'])
            self.assertEqual(sum(bool(body) for body in validate_snapshot(json.loads(ready.read_text(encoding='utf-8')),NOW)),9)

    def test_market_retry_cannot_corrupt_earlier_successful_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);write_sources(root)
            group=next(group for group in cloud.GROUPS if group[0]=='market')
            original=(root/'fuelfx.txt').read_bytes()
            saved={key:(root/(key+'.txt')).read_bytes() for key in ('fuelfx','books')}
            previous=dict(group='market',boxes=[dict(key=key,status='failed' if key=='metalcoin' else 'ok',reason=None,issueCount=0)
                                               for key in group[2]])
            bodies=fixture_sources()[0]
            def runner(command, **kwargs):
                for key in group[2]:
                    for name in (key+'.txt',key+'-wed.txt'):
                        (root/name).write_text(bodies[BOX_KEYS.index(key)] if key=='metalcoin' else '수집 실패',encoding='utf-8')
                return subprocess.CompletedProcess(command,0)
            import time
            report=cloud._retry_group(root,previous,group,NOW,time.monotonic()+30,runner,True)
            self.assertEqual(report['status'],'ok')
            for key,body in saved.items():
                self.assertEqual((root/(key+'.txt')).read_bytes(),body)
            self.assertEqual((root/'fuelfx.txt').read_bytes(),original)

    def test_persistent_failure_is_omitted_after_three_attempts_without_blocking_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);write_sources(root)
            bodies,_,trend=fixture_sources()
            calls=[]
            def runner(command,**kwargs):
                script=command[-1];calls.append(script)
                if script=='weather_fetch.py':
                    return subprocess.CompletedProcess(command,1)
                keys=next(group[2] for group in cloud.GROUPS if group[1]==script)
                for key in keys:
                    for name in (key+'.txt',key+'-wed.txt'):
                        (root/name).write_text(bodies[BOX_KEYS.index(key)]+'\n',encoding='utf-8')
                if 'trend' in keys:
                    (root/'neonet-trend-cache.json').write_text(json.dumps(trend),encoding='utf-8')
                return subprocess.CompletedProcess(command,0)
            sleep=Mock()
            report=cloud.prepare(root,root/'ready.json',root/'report.json',collect=True,now=NOW,runner=runner,sleeper=sleep)
            self.assertTrue(report['snapshotWritten'])
            self.assertEqual(report['sourceHealth'],'degraded')
            self.assertEqual(report['omittedKeys'],['weather'])
            self.assertEqual(calls.count('weather_fetch.py'),3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list],[10,20])

    def test_deadline_stops_retries_and_all_healthy_does_not_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);write_sources(root)
            sleep=Mock()
            calls=[]
            def runner(command,**kwargs):
                calls.append(command[-1])
                return subprocess.CompletedProcess(command,1)
            report=cloud.prepare(root,root/'ready.json',root/'report.json',collect=True,now=NOW,
                                 runner=runner,sleeper=sleep,deadline_seconds=1)
            self.assertEqual(len(calls),6)
            sleep.assert_not_called()
            self.assertTrue(report['hadErrors'])


if __name__=='__main__':
    unittest.main()
