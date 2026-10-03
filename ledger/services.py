from decimal import Decimal

from django.db import transaction as dbtx

from core.exceptions import DomainError
from core.money import D, q2

from .models import Account, Entry, Transaction

SYSTEM = {
    "CASH": ("Platform cash", Account.Kind.ASSET),
    "RECEIVABLE": ("Loans receivable (principal)", Account.Kind.ASSET),
    "POOL": ("Investor pool (funds owed to investors)", Account.Kind.LIABILITY),
    "REVENUE": ("Platform revenue", Account.Kind.INCOME),
}


def system_account(code) -> Account:
    name, kind = SYSTEM[code]
    acc, _ = Account.objects.get_or_create(code=code, defaults={"name": name, "kind": kind})
    return acc


def get_wallet(user) -> Account:
    acc, _ = Account.objects.get_or_create(
        code=f"WALLET:{user.pk}",
        defaults={"name": f"Wallet · {user}", "kind": Account.Kind.LIABILITY, "user": user},
    )
    return acc


@dbtx.atomic
def post(tx_type, lines, *, loan=None, description="", reference="", created_by=None) -> Transaction:
    """lines: iterable of (account, debit, credit). Must balance. Zero lines are skipped."""
    lines = [(a, q2(d), q2(c)) for a, d, c in lines if q2(d) or q2(c)]
    total_d = sum((d for _, d, _ in lines), Decimal("0"))
    total_c = sum((c for _, _, c in lines), Decimal("0"))
    if not lines or total_d != total_c:
        raise DomainError(f"Unbalanced ledger transaction (debit {total_d} vs credit {total_c}).")
    tx = Transaction.objects.create(type=tx_type, loan=loan, description=description, reference=reference,
                                    created_by=created_by if getattr(created_by, "pk", None) else None)
    Entry.objects.bulk_create([Entry(transaction=tx, account=a, debit=d, credit=c) for a, d, c in lines])
    return tx


def wallet_balance(user):
    return get_wallet(user).balance
