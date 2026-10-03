from decimal import Decimal

from django.db import transaction as dbtx

from accounts.models import Role
from audit.services import log
from core.exceptions import DomainError
from core.money import D, q2, q2_down, split_pro_rata
from ledger import services as ledger
from ledger.models import Transaction
from rules.services import get_setting

from .models import Investment, LoanFunding


@dbtx.atomic
def invest(user, amount):
    amount = q2(D(amount))
    if not user.has_role(Role.INVESTOR):
        raise DomainError("Only investors can fund the pool.")
    if amount < get_setting("MIN_INVESTMENT", Decimal):
        raise DomainError(f"Minimum investment is {get_setting('MIN_INVESTMENT')}.")
    inv = Investment.objects.create(investor=user, amount=amount)
    ledger.post(Transaction.Type.INVESTMENT,
                [(ledger.system_account("CASH"), amount, 0), (ledger.system_account("POOL"), 0, amount)],
                description=f"Investment #{inv.pk} by {user}", created_by=user)
    log("investment.created", user, inv, amount=amount)
    from loans.services import fund_waiting_loans
    fund_waiting_loans()
    return inv


@dbtx.atomic
def withdraw_investment(investment, amount, user):
    inv = Investment.objects.select_for_update().get(pk=investment.pk)
    if inv.investor_id != user.pk:
        raise DomainError("Not your investment.")
    amount = q2(D(amount))
    if amount <= 0 or amount > inv.available:
        raise DomainError(f"You can withdraw at most {inv.available} (the rest is lent out).")
    inv.amount -= amount
    if inv.amount == 0:
        inv.status = Investment.Status.WITHDRAWN
    inv.save()
    ledger.post(Transaction.Type.INVESTMENT_WITHDRAWAL,
                [(ledger.system_account("POOL"), amount, 0), (ledger.system_account("CASH"), 0, amount)],
                description=f"Withdrawal from investment #{inv.pk}", created_by=user)
    log("investment.withdrawn", user, inv, amount=amount)
    return inv


@dbtx.atomic
def withdraw_earnings(user, amount):
    amount = q2(D(amount))
    wallet = ledger.get_wallet(user)
    if amount <= 0 or amount > wallet.balance:
        raise DomainError(f"Insufficient earnings balance ({wallet.balance}).")
    tx = ledger.post(Transaction.Type.EARNINGS_WITHDRAWAL,
                     [(wallet, amount, 0), (ledger.system_account("CASH"), 0, amount)],
                     description="Earnings withdrawal", created_by=user)
    log("earnings.withdrawn", user, wallet, amount=amount)
    return tx


@dbtx.atomic
def allocate(loan) -> bool:
    """Reserve `loan.amount` from the pool pro rata to each investment's free capital."""
    invs = list(Investment.objects.select_for_update().filter(status=Investment.Status.ACTIVE).order_by("id"))
    invs = [i for i in invs if i.available > 0]
    total = sum((i.available for i in invs), Decimal("0"))
    if total < loan.amount:
        return False
    shares = [q2_down(loan.amount * i.available / total) for i in invs]
    left = loan.amount - sum(shares)
    for idx, i in enumerate(invs):  # top up rounding remainder where capacity remains
        if left <= 0:
            break
        add = min(left, i.available - shares[idx])
        shares[idx] += add
        left -= add
    for i, share in zip(invs, shares):
        if share > 0:
            LoanFunding.objects.create(loan=loan, investment=i, amount=share)
            i.allocated += share
            i.save(update_fields=["allocated"])
    return True


@dbtx.atomic
def release(loan, principal):
    """Return repaid principal to the investments that funded the loan, pro rata to what is still lent."""
    fundings = list(loan.fundings.select_for_update().select_related("investment"))
    outstanding = [f.outstanding for f in fundings]
    for f, share in zip(fundings, split_pro_rata(principal, outstanding)):
        share = min(share, f.outstanding)
        f.returned += share
        f.save(update_fields=["returned"])
        f.investment.allocated -= share
        f.investment.save(update_fields=["allocated"])
