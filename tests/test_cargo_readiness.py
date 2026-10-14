import unittest
from pz_sales_contract.cargo_readiness import normalize_cargo_ready_days, readiness_clause


class CargoReadinessTests(unittest.TestCase):
    def test_empty_does_not_invent_a_deadline(self):
        for value in (None, '', 0, '0'):
            self.assertIsNone(normalize_cargo_ready_days(value))
            self.assertIsNone(readiness_clause(value, 30))

    def test_freely_entered_calendar_days_and_no_advance_omission(self):
        for days in (1, 30, 50, 60, 137):
            self.assertEqual(normalize_cargo_ready_days(str(days)), days)
            self.assertIn(f'within {days} calendar days after receipt of the agreed advance payment', readiness_clause(days, 50))
            self.assertIsNone(readiness_clause(days, 0))

    def test_invalid_values_fail_without_truncating(self):
        for value in (-1, 'abc', 1.5, '1.5', 'NaN', 'Infinity', True, 2147483648):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_cargo_ready_days(value)
