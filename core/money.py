import calendar
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def q2(x) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def q2_down(x) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_DOWN)


def split_pro_rata(total, weights):
    """Split `total` by weights; shares sum exactly to total (remainder goes to the last share)."""
    total = D(total)
    weights = [D(w) for w in weights]
    s = sum(weights)
    if not weights or s <= 0:
        return [ZERO for _ in weights]
    out, acc = [], ZERO
    for i, w in enumerate(weights):
        share = total - acc if i == len(weights) - 1 else q2_down(total * w / s)
        out.append(share)
        acc += share
    return out


def split_equal(total, n):
    total = D(total)
    base = q2_down(total / n)
    parts = [base] * (n - 1)
    parts.append(total - base * (n - 1))
    return parts


def add_months(d: date, m: int) -> date:
    y = d.year + (d.month - 1 + m) // 12
    mo = (d.month - 1 + m) % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))
