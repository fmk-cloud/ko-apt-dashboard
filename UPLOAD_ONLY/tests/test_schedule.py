"""Calendar/snapshot regression cases for monthly collection."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from schedule_due import due, last_closed_month, published_month


class ScheduleTests(unittest.TestCase):
    def test_october_closed_on_november_first_kst(self):
        # 2026-10-31 19:00 UTC = 2026-11-01 04:00 Korea
        when = dt.datetime(2026, 10, 31, 19, tzinfo=dt.timezone.utc)
        self.assertEqual(last_closed_month(when), '2026-10')
        self.assertTrue(due('schedule', when, '2026-09'))
        self.assertFalse(due('schedule', when, '2026-10'))

    def test_daily_retries_when_first_run_was_missed(self):
        when = dt.datetime(2026, 11, 3, 0, tzinfo=dt.timezone.utc)
        self.assertTrue(due('schedule', when, '2026-09'))
        self.assertTrue(due('push', when, '2026-09'))
        self.assertFalse(due('schedule', when, '2026-10'))

    def test_december_rollover_and_leap_year(self):
        self.assertEqual(last_closed_month(dt.datetime(2027, 1, 1, tzinfo=dt.timezone.utc)), '2026-12')
        self.assertEqual(last_closed_month(dt.datetime(2024, 3, 1, tzinfo=dt.timezone.utc)), '2024-02')

    def test_manual_run_always_allowed_and_unknown_event_ignored(self):
        when = dt.datetime(2026, 11, 3, tzinfo=dt.timezone.utc)
        self.assertTrue(due('workflow_dispatch', when, '2026-10'))
        self.assertFalse(due('pull_request', when, '2026-09'))

    def test_manifest_reader(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'site-data.json'
            path.write_text(json.dumps({'meta': {'current_month': '2026-09'}, '_storage': {}}))
            self.assertEqual(published_month(path), '2026-09')
            path.write_text('{bad json')
            self.assertIsNone(published_month(path))


if __name__ == '__main__':
    unittest.main()
