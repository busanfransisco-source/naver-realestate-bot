import unittest
from datetime import date
from pathlib import Path
from verify_transaction_publication import verify_body

class TransactionWorkflowContract(unittest.TestCase):
    def test_dependencies_and_preflight_before_collection(self):
        text = Path('.github/workflows/transactions.yml').read_text(encoding='utf-8')
        self.assertEqual(text.count('pip install -r requirements.txt'), 2)
        self.assertLess(text.index('Preflight publication'), text.index('Collect nationwide official'))
        self.assertIn('needs: collect', text)
        self.assertIn('actions/download-artifact@v4', text)
        self.assertLess(text.index('Persist source before'), text.index('Render and publish'))
        self.assertIn('python verify_transaction_publication.py', text)
        self.assertEqual(text.count('overwrite: true'), 2)

    def test_today_only_including_true_zero(self):
        self.assertTrue(verify_body('10/7(수) 신규 등록 실거래가\n전국 0건', date(2026, 10, 7)))
        self.assertFalse(verify_body('10/6(화) 신규 등록 실거래가\n전국 114건', date(2026, 10, 7)))
        self.assertFalse(verify_body('10/7(수) 신규 등록 실거래가\n수집 중입니다', date(2026, 10, 7)))

if __name__ == '__main__':
    unittest.main()
