"""Validated contract payment percentages and rounded amount splits."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


DEFAULT_ADVANCE_PERCENTAGE = Decimal('30')
PERCENTAGE_TOTAL = Decimal('100')


def normalize_advance_percentage(value):
    """Return a finite 0..100 advance percentage; absent legacy values mean 30."""
    if value is None or value == '':
        return DEFAULT_ADVANCE_PERCENTAGE
    try:
        percentage = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Advance percentage must be a finite number from 0 to 100') from None
    if not percentage.is_finite() or not Decimal('0') <= percentage <= PERCENTAGE_TOTAL:
        raise ValueError('Advance percentage must be a finite number from 0 to 100')
    return percentage


def format_percentage(value):
    """Format a validated percentage without unnecessary trailing zeroes."""
    percentage = normalize_advance_percentage(value)
    formatted = format(percentage.normalize(), 'f')
    return formatted.rstrip('0').rstrip('.') if '.' in formatted else formatted


def calculate_payment_split(contract_total, advance_percentage, precision=2):
    """Split the rounded contract total, rounding the advance half up to money precision."""
    percentage = normalize_advance_percentage(advance_percentage)
    try:
        digits = int(precision)
        total = Decimal(str(contract_total if contract_total is not None else 0))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError('Contract total and currency precision must be finite numbers') from None
    if digits < 0 or not total.is_finite():
        raise ValueError('Contract total and currency precision must be finite numbers')
    quantum = Decimal(1).scaleb(-digits)
    rounded_total = total.quantize(quantum, rounding=ROUND_HALF_UP)
    advance = (rounded_total * percentage / PERCENTAGE_TOTAL).quantize(
        quantum, rounding=ROUND_HALF_UP
    )
    return percentage, PERCENTAGE_TOTAL - percentage, advance, rounded_total - advance
