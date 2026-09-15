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

    def test_general_briefing_dispatches_a_morning_transaction_backstop(self):
        workflow = Path(".github/workflows/manual-briefing.yml").read_text(encoding="utf-8")
        self.assertNotIn("Fetch nationwide apartment transactions", workflow)
        self.assertIn("Backstop nationwide transaction refresh", workflow)
        self.assertIn("gh workflow run transactions.yml --ref main", workflow)
        for hour in range(20, 23):
            self.assertIn(f"25 {hour} * * *", workflow)


if __name__ == "__main__":
    unittest.main()
