import json
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_content_inventory import inventory


class InventoryTests(unittest.TestCase):
    today = date(2026, 11, 25)

    def prepare(self, root, offsets):
        for offset in offsets:
            day = self.today + timedelta(days=offset)
            (Path(root)/(day.isoformat()+'.json')).write_text(json.dumps({'date':day.isoformat()}))

    def validate(self, packet, day):
        if packet['date'] != day.isoformat():
            raise ValueError('wrong date')

    def test_seven_days_are_counted_only_as_complete_dated_packets(self):
        with TemporaryDirectory() as root:
            self.prepare(root, range(7))
            result = inventory(self.today, root, self.validate)
            self.assertEqual(result['manuscripts'], 42)
            self.assertEqual(result['remainingFutureDays'], 6)
            self.assertEqual(result['lastPreparedDate'], '2026-12-01')
            self.assertEqual(result['nextMissingDate'], '2026-12-02')
            self.assertEqual(result['level'], 'ok')

    def test_two_future_days_trigger_warning_before_stock_runs_out(self):
        with TemporaryDirectory() as root:
            self.prepare(root, range(3))
            result = inventory(self.today, root, self.validate)
            self.assertEqual(result['level'], 'low')
            self.assertEqual(result['remainingFutureDays'], 2)

    def test_gaps_and_invalid_packets_are_not_counted_as_usable_stock(self):
        with TemporaryDirectory() as root:
            self.prepare(root, (0, 2, 3))
            result = inventory(self.today, root, self.validate)
            self.assertEqual(result['remainingDaysIncludingToday'], 1)
            self.assertEqual(result['nextMissingDate'], '2026-11-26')
            (Path(root)/'2026-11-25.json').write_text('{bad json')
            self.assertEqual(inventory(self.today, root, self.validate)['level'], 'missing_today')

    def test_invalid_today_is_not_hidden_by_future_stock(self):
        with TemporaryDirectory() as root:
            self.prepare(root, range(7))
            (Path(root)/'2026-11-25.json').write_text(json.dumps({'date':'2026-11-24'}))
            result = inventory(self.today, root, self.validate)
            self.assertEqual(result['level'], 'missing_today')
            self.assertEqual(result['manuscripts'], 0)

    def test_alert_signature_stays_stable_as_low_stock_declines(self):
        with TemporaryDirectory() as root:
            self.prepare(root, range(3))
            first = inventory(self.today, root, self.validate)
            second = inventory(self.today+timedelta(days=1), root, self.validate)
            self.assertEqual(first['alertSignature'], second['alertSignature'])
            missing = inventory(self.today+timedelta(days=3), root, self.validate)
            later = inventory(self.today+timedelta(days=4), root, self.validate)
            self.assertEqual(missing['alertSignature'], later['alertSignature'])
            self.assertNotEqual(first['alertSignature'], missing['alertSignature'])

    def test_inventory_does_not_write_or_change_any_manuscripts(self):
        with TemporaryDirectory() as root:
            self.prepare(root, range(7))
            before = {p.name:p.read_bytes() for p in Path(root).iterdir()}
            inventory(self.today, root, self.validate)
            self.assertEqual(before, {p.name:p.read_bytes() for p in Path(root).iterdir()})
