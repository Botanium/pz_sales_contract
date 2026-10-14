"""Optional calendar-day readiness commitment; no inferred commercial deadline."""
from decimal import Decimal, InvalidOperation


def normalize_cargo_ready_days(value):
    # Native optional Int fields serialize a cleared/blank value as zero.
    if value is None or value == '':
        return None
    try:
        days = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Cargo Ready Within (Days) must be a positive whole number of calendar days, or blank') from None
    if not days.is_finite() or days != days.to_integral_value() or days < 0 or days > 2147483647:
        raise ValueError('Cargo Ready Within (Days) must be a positive whole number of calendar days, or blank')
    return int(days) if days else None


def readiness_clause(value, advance_percentage):
    from pz_sales_contract.payment_split import normalize_advance_percentage

    days = normalize_cargo_ready_days(value)
    if days is None or normalize_advance_percentage(advance_percentage) == 0:
        return None
    return (f'17. Cargo Readiness. The cargo shall be ready for loading within {days} calendar days '
            'after receipt of the agreed advance payment. This commitment concerns cargo readiness for loading; '
            'delivery and risk remain governed by the agreed delivery arrangement.')
