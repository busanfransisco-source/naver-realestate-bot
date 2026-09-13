import unittest
from pathlib import Path


class TransactionScheduleTests(unittest.TestCase):
    def test_transactions_run_at_0510_kst_or_manual_only(self):
        workflow = Path(".github/workflows/manual-briefing.yml").read_text(encoding="utf-8")
        self.assertIn('- cron: "10 20 * * *"', workflow)
        self.assertIn(
            "if: github.event_name == 'workflow_dispatch' || "
            "github.event.schedule == '10 20 * * *'",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
