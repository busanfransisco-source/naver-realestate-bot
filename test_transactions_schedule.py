import unittest
from pathlib import Path


class TransactionScheduleTests(unittest.TestCase):
    def test_transactions_retry_in_an_independent_workflow(self):
        workflow = Path(".github/workflows/transactions.yml").read_text(encoding="utf-8")
        self.assertIn('- cron: "10,30,50 20-23 * * *"', workflow)
        self.assertIn("timeout-minutes: 18", workflow)
        self.assertIn("group: nationwide-transactions", workflow)
        self.assertIn("--skip-if-collected-today", workflow)

    def test_general_briefing_no_longer_collects_transactions(self):
        workflow = Path(".github/workflows/manual-briefing.yml").read_text(encoding="utf-8")
        self.assertNotIn("Fetch nationwide apartment transactions", workflow)


if __name__ == "__main__":
    unittest.main()
