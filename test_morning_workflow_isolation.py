"""A collector's failure may not block unrelated website source publication."""
from pathlib import Path
import unittest


class MorningWorkflowIsolationTests(unittest.TestCase):
    def test_partial_website_artifact_is_published_independently(self):
        text = Path('.github/workflows/morning-briefing.yml').read_text(encoding='utf-8')
        collect = text.split('name: Collect and validate only morning boxes 1 to 9', 1)[1].split('      - name:',1)[0]
        self.assertIn('continue-on-error: true', collect)
        self.assertIn("if: always() && (needs.collect.outputs.publication == 'true' || needs.collect.outputs.weather_status == 'true' || needs.collect.outputs.quicknews_status == 'true')",text)
        self.assertIn('report.get(\'websiteWritten\') is True',text)
        self.assertIn('report.get(\'snapshotWritten\') is True',text)
        self.assertIn('validate_publication(',text)
        self.assertIn('name: morning-quicknews-status',text)
        self.assertIn('git status --porcelain -- weather-status.txt shortnews-status.txt',text)
        self.assertIn("merge_quicknews_status(Path('tmp/morning-quicknews-status/shortnews-status.txt'))",text)
        self.assertIn('validate_snapshot(',text)
        self.assertIn('from morning_source_publication import apply_collection',text)
        self.assertIn('morning_source_publication.py --verify',text)
        self.assertIn("if os.environ['MORNING_READY']=='true' else None",text)
        self.assertIn("if: steps.apply.outputs.ready_applied == 'true'",text)
        self.assertIn('no validated sender snapshot was available',text)

    def test_weather_failure_state_is_exposed_to_the_publication_job(self):
        from datetime import datetime
        import json, os, tempfile, yaml
        from unittest.mock import patch
        from weather_fetch import KST
        workflow = yaml.safe_load(Path('.github/workflows/morning-briefing.yml').read_text(encoding='utf8'))
        stage = next(step['run'] for step in workflow['jobs']['collect']['steps']
                     if step.get('id') == 'stage')
        code = stage.split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                now = datetime.now(KST)
                Path('weather-status.txt').write_text(json.dumps(dict(
                    forecastDate=now.date().isoformat(), attemptedAtKst=now.isoformat(), status='failed')))
                with patch.dict(os.environ, {'GITHUB_OUTPUT': str(Path(directory)/'outputs')}), \
                     patch('subprocess.check_output', return_value=' M weather-status.txt'):
                    exec(compile(code, '<stage>', 'exec'), {})
                self.assertIn('weather_status=true', Path('outputs').read_text())
                self.assertTrue(Path('tmp/weather-status/weather-status.txt').exists())
            finally:
                os.chdir(previous)

    def test_official_recovery_does_not_wait_for_morning_collection(self):
        text = Path('.github/workflows/morning-briefing.yml').read_text(encoding='utf-8')
        recovery = text.split('  transactions:\n',1)[1]
        self.assertIn('uses: ./.github/workflows/transactions.yml',recovery)
        self.assertIn('secrets: inherit',recovery)
        self.assertNotIn('needs:',recovery)
        self.assertIn('workflow_call: {}',Path('.github/workflows/transactions.yml').read_text(encoding='utf-8'))
        self.assertNotIn('MOLIT_API_KEY',text)  # dedicated workflow alone owns the key

    def test_no_old_snapshot_is_blindly_staged_as_new_success(self):
        text = Path('.github/workflows/morning-briefing.yml').read_text(encoding='utf-8')
        staging=text.split('name: Stage only independently validated source artifacts',1)[1].split('      - name:',1)[0]
        self.assertIn('if ready:',staging)
        self.assertIn("shutil.copyfile('morning-briefing-ready.json'",staging)
        upload=text.split('name: Save validated publication bundle',1)[1].split('      - name:',1)[0]
        self.assertIn('path: tmp/morning-publication/',upload)
        self.assertNotIn('path: |',upload)

    def test_weekly_cache_artifact_is_optional_when_trend_is_not_selected(self):
        text = Path('.github/workflows/morning-briefing.yml').read_text(encoding='utf-8')
        self.assertIn("if any(box['key'] == 'trend' for box in boxes):",text)
        self.assertIn('trend if trend.exists() else None',text)


if __name__=='__main__':
    unittest.main()
