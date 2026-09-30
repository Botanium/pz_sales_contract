from datetime import date
from types import SimpleNamespace
import unittest
from pz_sales_contract.calendar import add_open_hours


class TestCalendar(unittest.TestCase):
    def setUp(self):
        self.doc=SimpleNamespace(timezone='Asia/Baghdad',business_days='Monday,Tuesday,Wednesday,Thursday,Friday',opens_at='09:00:00',closes_at='17:00:00')

    def deadline(self,stamp,holidays=()):
        return add_open_hours(stamp,24,self.doc,holidays,date(2026,1,1),date(2026,12,31))

    def test_open_hours_across_weekend_and_holiday(self):
        self.assertEqual(self.deadline('2026-10-02T16:00:00+03:00',[date(2026,10,5)]),'2026-10-08T16:00:00+03:00')

    def test_closed_receipt_starts_next_open(self):
        self.assertEqual(self.deadline('2026-10-03T14:00:00+03:00'),'2026-10-07T17:00:00+03:00')

    def test_missing_offset_and_exhausted_calendar_fail(self):
        with self.assertRaises(ValueError): self.deadline('2026-10-02T16:00:00')
        with self.assertRaises(ValueError): self.deadline('2026-12-31T16:00:00+03:00')

    def test_dst_is_elapsed_open_hours(self):
        self.doc.timezone='America/New_York'
        self.doc.business_days='Sunday'
        self.doc.opens_at='00:00:00'
        self.doc.closes_at='08:00:00'
        result=add_open_hours('2026-11-01T00:00:00-04:00',9,self.doc,(),date(2026,1,1),date(2026,12,31))
        self.assertEqual(result,'2026-11-01T08:00:00-05:00')

if __name__=='__main__': unittest.main()
