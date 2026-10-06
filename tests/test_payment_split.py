import unittest
from decimal import Decimal

from pz_sales_contract.payment_split import (
    calculate_payment_split,
    format_percentage,
    normalize_advance_percentage,
)


class TestPaymentSplit(unittest.TestCase):
    def test_supported_percentages_split_the_contract_total(self):
        cases = [
            (30, '30.00', '70.01'),
            (50, '50.01', '50.00'),
            (20, '20.00', '80.01'),
            (0, '0.00', '100.01'),
            (100, '100.01', '0.00'),
            (12.5, '12.50', '87.51'),
        ]
        for percentage, advance, balance in cases:
            with self.subTest(percentage=percentage):
                pct, remainder, amount, remaining = calculate_payment_split(
                    Decimal('100.01'), percentage, 2
                )
                self.assertEqual(format_percentage(pct), format_percentage(percentage))
                self.assertEqual(format_percentage(remainder), format_percentage(100 - percentage))
                self.assertEqual(amount, Decimal(advance))
                self.assertEqual(remaining, Decimal(balance))
                self.assertEqual(amount + remaining, Decimal('100.01'))

    def test_fractional_percentage_uses_half_up_money_rounding(self):
        percentage, balance_percentage, advance, remaining = calculate_payment_split(
            Decimal('999.99'), '12.5', 2
        )
        self.assertEqual(percentage, Decimal('12.5'))
        self.assertEqual(balance_percentage, Decimal('87.5'))
        self.assertEqual(advance, Decimal('125.00'))
        self.assertEqual(remaining, Decimal('874.99'))

    def test_zero_decimal_currency_precision_preserves_the_total(self):
        _, _, advance, remaining = calculate_payment_split(101, 30, 0)
        self.assertEqual((advance, remaining), (Decimal('30'), Decimal('71')))

    def test_missing_percentage_defaults_to_thirty_but_zero_is_preserved(self):
        self.assertEqual(normalize_advance_percentage(None), Decimal('30'))
        self.assertEqual(normalize_advance_percentage(''), Decimal('30'))
        self.assertEqual(normalize_advance_percentage(0), Decimal('0'))

    def test_nonfinite_and_out_of_range_percentages_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', float('nan'), float('inf'), -0.01, 100.01, 'not a number'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_advance_percentage(value)


if __name__ == '__main__':
    unittest.main()
