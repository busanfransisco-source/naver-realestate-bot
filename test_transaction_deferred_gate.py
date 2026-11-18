import contextlib,io,os,tempfile,unittest,yaml
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

class DeferredGate(unittest.TestCase):
 def setUp(self):
  self.w=yaml.safe_load(Path('.github/workflows/transactions.yml').read_text())
  self.collect=self.w['jobs']['collect'];self.gate=self.collect['steps'][0]
 def test_actual_clock_boundary(self):
  script=self.gate['run'].split("python - <<'PYCODE'\n")[1].rsplit('\nPYCODE',1)[0]
  for hour,minute,expected in [(0,0,False),(2,30,False),(4,59,False),(5,0,True),(5,10,True),(23,59,True)]:
   clock=datetime(2026,11,19,hour,minute,tzinfo=timezone(timedelta(hours=9)))
   class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return clock.astimezone(tz)
   with self.subTest(hour=hour,minute=minute),tempfile.TemporaryDirectory() as d:
    out=Path(d)/'output'
    with patch('datetime.datetime',Clock),patch.dict(os.environ,{'GITHUB_OUTPUT':str(out)}),contextlib.redirect_stdout(io.StringIO()):
     exec(compile(script,'workflow-window','exec'),{})
    self.assertEqual(out.read_text(),'eligible='+str(expected).lower()+'\n')
 def test_all_collection_steps_and_publish_are_guarded(self):
  self.assertEqual(self.gate['id'],'window')
  self.assertIn('steps.window.outputs.eligible',self.collect['outputs']['eligible'])
  for step in self.collect['steps'][1:]:self.assertIn("steps.window.outputs.eligible == 'true'",step['if'])
  self.assertEqual(self.w['jobs']['publish']['if'],"needs.collect.outputs.eligible == 'true'")
  self.assertEqual(self.w['jobs']['publish']['needs'],'collect')
 def test_no_manual_or_message_side_effects_in_gate(self):
  self.assertNotIn('workflow_dispatch',self.gate['run']);self.assertNotIn('requests',self.gate['run'])
  self.assertNotIn('subprocess',self.gate['run'])

if __name__=='__main__':unittest.main()
