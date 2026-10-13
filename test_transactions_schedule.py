import unittest
from pathlib import Path


class TransactionScheduleTests(unittest.TestCase):
    def test_transactions_retry_in_an_independent_workflow(self):
        workflow = Path(".github/workflows/transactions.yml").read_text(encoding="utf-8")
        for hour in range(20, 24):
            self.assertIn(f'- cron: "10 {hour} * * *"', workflow)
        self.assertIn("timeout-minutes: 28", workflow)
        self.assertIn("group: nationwide-transactions", workflow)
        self.assertNotIn("--skip-if-collected-today", workflow)
        self.assertIn("python realestate_transactions_fetch.py", workflow)
        self.assertIn("MOLIT_API_KEY", workflow)
        self.assertIn('for attempt in 1 2; do', workflow)
        self.assertIn('if python realestate_transactions_fetch.py; then', workflow)
        self.assertIn('sleep 30', workflow)
        self.assertIn('no fabricated zero published', workflow)

    def test_general_briefing_recovers_missing_transactions_in_every_run(self):
        workflow = Path(".github/workflows/manual-briefing.yml").read_text(encoding="utf-8")
        self.assertNotIn("Fetch nationwide apartment transactions", workflow)
        self.assertIn("Backstop nationwide transaction refresh", workflow)
        self.assertIn("python ensure_transactions_daily.py", workflow)
        self.assertNotIn("gh workflow run transactions.yml", workflow)
        self.assertLess(workflow.index('python ensure_transactions_daily.py'), workflow.index('Fetch weather'))
        block = workflow.split('name: Backstop nationwide transaction refresh', 1)[1].split('      - name:', 1)[0]
        self.assertNotIn('if:', block)
        for hour in range(20, 23):
            self.assertIn(f"25 {hour} * * *", workflow)

    def test_dedicated_daytime_retry_and_health_repair_are_present(self):
        workflow = Path('.github/workflows/transactions.yml').read_text(encoding='utf-8')
        self.assertIn('cron: "35 0-8 * * *"', workflow)
        self.assertLess(workflow.index('python ensure_transactions_daily.py'), workflow.index('if python realestate_transactions_fetch.py'))
        health = Path('briefing_health.py').read_text(encoding='utf-8')
        self.assertIn("'transactions': 'ensure_transactions_daily.py'", health)
        self.assertIn('curl_cffi', Path('requirements.txt').read_text(encoding='utf-8'))
        self.assertGreaterEqual(workflow.count('python ensure_transactions_daily.py --check-only'), 2)

    def test_every_health_repair_workflow_persists_recovered_transaction_source(self):
        for path in Path('.github/workflows').glob('*.yml'):
            text = path.read_text(encoding='utf-8')
            if 'briefing_health.py --repair' in text:
                with self.subTest(workflow=path.name):
                    after_repair = text.split('briefing_health.py --repair', 1)[1]
                    self.assertIn('git add transactions.txt transactions-*.txt transactions-state.json', after_repair)


if __name__ == "__main__":
    unittest.main()
