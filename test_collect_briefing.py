import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import collect_briefing as collection
import briefing_health


class CollectionTests(unittest.TestCase):
    def test_three_workers_preserve_dependencies_and_attempt_every_script_once(self):
        active = peak = 0
        lock = threading.Lock()
        completed = set()
        def runner(command, **options):
            nonlocal active, peak
            script = command[-1]
            self.assertEqual(options["timeout"], 180)
            with lock:
                if script == "naver_realestate_analysis_fetch.py":
                    self.assertIn("naver_realestate_fetch.py", completed)
                if script == "ensure_seoul_daily.py":
                    self.assertIn("ensure_wiki_daily.py", completed)
                active += 1
                peak = max(peak, active)
            time.sleep(.01)
            with lock:
                active -= 1
                completed.add(script)
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as directory:
            results = collection.collect(directory, runner=runner)
        self.assertEqual(completed, collection.SCRIPTS)
        self.assertEqual(sum(len(group["scripts"]) for group in results), len(completed))
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 3)
        self.assertTrue(all(row["status"] == "ok" for group in results for row in group["scripts"]))

    def test_failed_or_timed_out_script_does_not_skip_other_sources(self):
        def runner(command, **options):
            if command[-1] == "weather_fetch.py":
                raise subprocess.TimeoutExpired(command, 180)
            return subprocess.CompletedProcess(command, 1 if command[-1] == "market_fetch.py" else 0)
        with tempfile.TemporaryDirectory() as directory:
            results = collection.collect(directory, runner=runner)
        outcomes = {row["script"]: row["status"] for group in results for row in group["scripts"]}
        self.assertEqual(outcomes["weather_fetch.py"], "failed")
        self.assertEqual(outcomes["market_fetch.py"], "failed")
        self.assertEqual(outcomes["fortune_fetch.py"], "ok")
        self.assertEqual(outcomes["ensure_seoul_daily.py"], "ok")
        self.assertEqual(len(outcomes), len(collection.SCRIPTS))

    def test_source_credentials_stay_with_their_existing_collectors(self):
        def runner(command, **options):
            script = command[-1]
            for key, owner in collection.SECRET_OWNERS.items():
                self.assertEqual(key in options["env"], script == owner)
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"RONE_KEY": "mock-rone", "SEOUL_OPEN_DATA_KEY": "mock-seoul"}):
            collection.collect(directory, runner=runner)

    def test_real_collection_is_refused_on_delivery_pc(self):
        with patch.object(collection, "collection_allowed", return_value=False):
            with self.assertRaises(ValueError):
                collection.collect()

    def test_health_repair_skips_sources_already_attempted_by_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                Path("briefing.html").write_text("<html></html>")
                rows = [dict(key="books", issues=["source failed"], status="failed", slot=8, sha256="x"),
                        dict(key="supplydemand", issues=["source delayed"], status="failed", slot=30, sha256="y")]
                with patch.object(sys, "argv", ["briefing_health.py", "--repair", "--skip-collected"]), \
                     patch.object(briefing_health, "inspect", return_value=rows), \
                     patch.object(briefing_health.subprocess, "run") as runner:
                    with self.assertRaises(SystemExit) as result:
                        briefing_health.main()
                self.assertEqual(result.exception.code, True)
                runner.assert_not_called()
            finally:
                os.chdir(previous)

    def test_generated_pages_are_published_only_after_merging_latest_sources(self):
        import yaml
        workflow = yaml.safe_load(Path(".github/workflows/manual-briefing.yml").read_text(encoding="utf8"))
        step = next(step["run"] for step in workflow["jobs"]["refresh"]["steps"]
                    if step.get("name") == "Regenerate pages and commit everything")
        before_merge, after_merge = step.split("git pull --rebase origin main", 1)
        self.assertIn("git restore --worktree -- index.html hub.html briefing.html", before_merge)
        self.assertNotIn("git add index.html", before_merge)
        for line in before_merge.splitlines():
            if line.lstrip().startswith("git add "):
                self.assertNotIn("briefing.html", line)
        self.assertLess(after_merge.index("python gen_briefing.py"), after_merge.index("git add index.html"))
        self.assertLess(after_merge.index("git add index.html"), after_merge.index("git push"))

    def test_workflow_keeps_schedule_and_public_validation(self):
        import yaml
        workflow = yaml.safe_load(Path(".github/workflows/manual-briefing.yml").read_text(encoding="utf8"))
        steps = workflow["jobs"]["refresh"]["steps"]
        self.assertEqual(sum("python collect_briefing.py" in step.get("run", "") for step in steps), 1)
        self.assertTrue(any("--repair --skip-collected" in step.get("run", "") for step in steps))
        self.assertTrue(any("briefing_health.py --url" in step.get("run", "") for step in steps))


if __name__ == "__main__":
    unittest.main()
