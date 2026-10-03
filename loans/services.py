from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction as dbtx
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Role, User
from audit.services import log
from core.exceptions import DomainError
from core.money import ZERO, D, add_months, q2, split_equal, split_pro_rata
from funding import services as funding
from funding.models import Earning
from ledger import services as ledger
from ledger.models import Transaction
from notifications.services import notify
from rules.models import ScoreBand
from rules.services import current_policy, get_setting
from scoring.services import compute_score

from .models import GuaranteeClaim, Installment, Loan, Repayment

S = Loan.Status


# ---------------------------------------------------------------- state machine
def transition(loan, new_status, actor=None, note=""):
    if new_status not in Loan.TRANSITIONS.get(loan.status, set()):
        raise DomainError(f"Cannot move a loan from {loan.status} to {new_status}.")
    old = loan.status
    loan.status = new_status
    loan.save()
    log("loan.transition", actor, loan, **{"from": old, "to": new_status, "note": note})


# ---------------------------------------------------------------- quote / apply
def guarantor_exposure(guarantor, exclude=None):
    qs = Loan.objects.filter(guarantor=guarantor, status__in=Loan.EXPOSURE_STATES)
    if exclude:
        qs = qs.exclude(pk=exclude.pk)
    return qs.aggregate(t=Sum("amount"))["t"] or ZERO


def quote(borrower, product, amount, term_months, persist_score=False):
    amount, term_months = q2(D(amount)), int(term_months)
    if not product.active:
        raise DomainError("This loan product is not available.")
    if not (product.min_amount <= amount <= product.max_amount):
        raise DomainError(f"Amount must be between {product.min_amount} and {product.max_amount}.")
    if term_months not in product.terms():
        raise DomainError(f"Term must be one of {product.terms()} months.")
    result = compute_score(borrower, persist=persist_score)
    band = result["band"]
    if not band:
        raise DomainError("Your credit score is not eligible for a loan right now.")
    if amount > band.max_loan_amount:
        raise DomainError(f"Your credit band allows at most {band.max_loan_amount}.")
    if term_months > band.max_term_months:
        raise DomainError(f"Your credit band allows at most {band.max_term_months} months.")
    interest = q2(amount * band.interest_rate_pct / 100 * term_months / 12)
    fee = q2(amount * product.origination_fee_pct / 100)
    return {"score": result["score"], "band": band, "rate": band.interest_rate_pct, "fee": fee,
            "total_interest": interest, "total_repayable": amount + interest,
            "installment": q2((amount + interest) / term_months)}


@dbtx.atomic
def apply_for_loan(*, borrower, guarantor, product, amount, term_months, purpose=""):
    if not borrower.has_role(Role.BORROWER):
        raise DomainError("Only borrowers can apply for loans.")
    if guarantor is None:
        raise DomainError("A guarantor is required.")
    if guarantor.pk == borrower.pk:
        raise DomainError("You cannot guarantee your own loan.")
    if not (guarantor.is_active and guarantor.has_role(Role.GUARANTOR)):
        raise DomainError("The selected user is not a registered guarantor.")
    if Loan.objects.filter(borrower=borrower, status=S.DEFAULTED).exists():
        raise DomainError("You have an unresolved defaulted loan.")
    if Loan.objects.filter(borrower=borrower, status__in=Loan.OPEN_STATES).count() >= get_setting("MAX_ACTIVE_LOANS", int):
        raise DomainError("You have reached the maximum number of open loans.")
    q = quote(borrower, product, amount, term_months, persist_score=True)
    cap = get_setting("GUARANTOR_MAX_EXPOSURE", Decimal)
    if cap and guarantor_exposure(guarantor) + q2(D(amount)) > cap:
        raise DomainError("This guarantor has reached their guarantee limit.")
    policy = current_policy()
    loan = Loan.objects.create(
        borrower=borrower, guarantor=guarantor, product=product, band=q["band"], policy=policy,
        amount=q2(D(amount)), term_months=int(term_months), purpose=purpose, score_at_application=q["score"],
        interest_rate_pct=q["rate"], investor_pct=policy.investor_pct, guarantor_pct=policy.guarantor_pct,
        platform_pct=policy.platform_pct, late_fee_pct=product.late_fee_pct, grace_days=product.grace_days,
        default_after_days=product.default_after_days, guarantor_liability_pct=product.guarantor_liability_pct,
        origination_fee=q["fee"], total_interest=q["total_interest"], total_repayable=q["total_repayable"],
    )
    log("loan.applied", borrower, loan, amount=loan.amount, term=loan.term_months, guarantor=guarantor.pk)
    notify(guarantor, "Guarantee request", f"{borrower} asks you to guarantee a loan of {loan.amount}.",
           kind="guarantee_request", loan_id=loan.pk)
    return loan


# ---------------------------------------------------------------- decisions
@dbtx.atomic
def guarantor_decide(loan, guarantor, approve, note=""):
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.guarantor_id != guarantor.pk:
        raise DomainError("This request is not addressed to you.")
    if loan.status != S.PENDING_GUARANTOR:
        raise DomainError("This request has already been decided.")
    if approve:
        cap = get_setting("GUARANTOR_MAX_EXPOSURE", Decimal)
        if cap and guarantor_exposure(guarantor, exclude=loan) + loan.amount > cap:
            raise DomainError("Approving would exceed your guarantee limit.")
    loan.guarantor_decided_at = timezone.now()
    loan.guarantor_note = note[:255]
    transition(loan, S.ADMIN_REVIEW if approve else S.GUARANTOR_REJECTED, guarantor, note)
    notify(loan.borrower, "Guarantor " + ("approved" if approve else "declined"),
           f"{guarantor} {'approved' if approve else 'declined'} your loan request.",
           kind="guarantor_decision", loan_id=loan.pk)
    return loan


@dbtx.atomic
def admin_decide(loan, admin, approve, note=""):
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.status != S.ADMIN_REVIEW:
        raise DomainError("Only loans awaiting admin approval can be decided.")
    loan.reviewed_by, loan.reviewed_at, loan.admin_note = admin, timezone.now(), note[:255]
    transition(loan, S.FUNDING if approve else S.REJECTED, admin, note)
    notify(loan.borrower, "Loan " + ("approved" if approve else "rejected"),
           "Your loan was approved and is being funded." if approve else "Your loan request was rejected.",
           kind="loan_decision", loan_id=loan.pk)
    if approve:
        fund_loan(loan)
    return loan


# ---------------------------------------------------------------- funding & disbursement
@dbtx.atomic
def fund_loan(loan) -> bool:
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.status != S.FUNDING or not funding.allocate(loan):
        return False
    _disburse(loan)
    return True


def fund_waiting_loans():
    for loan in Loan.objects.filter(status=S.FUNDING).order_by("id"):
        fund_loan(loan)


def _disburse(loan):
    now = timezone.now()
    start = now.date()
    for n, (p, i) in enumerate(zip(split_equal(loan.amount, loan.term_months),
                                   split_equal(loan.total_interest, loan.term_months)), start=1):
        Installment.objects.create(loan=loan, number=n, due_date=add_months(start, n), principal_due=p, interest_due=i)
    ledger.post(Transaction.Type.DISBURSEMENT, [
        (ledger.system_account("RECEIVABLE"), loan.amount, 0),
        (ledger.system_account("CASH"), 0, loan.amount - loan.origination_fee),
        (ledger.system_account("REVENUE"), 0, loan.origination_fee),
    ], loan=loan, description=f"Disbursement of loan #{loan.pk}")
    loan.disbursed_at = now
    transition(loan, S.ACTIVE, note="disbursed")
    notify(loan.borrower, "Loan disbursed", f"{loan.amount - loan.origination_fee} has been paid out. "
           f"First installment due {loan.installments.first().due_date}.", kind="disbursed", loan_id=loan.pk)
    notify(loan.guarantor, "Guaranteed loan is active", f"Loan #{loan.pk} for {loan.borrower} is now active.",
           kind="loan_active", loan_id=loan.pk)


# ---------------------------------------------------------------- repayments
@dbtx.atomic
def record_repayment(*, loan, amount, source=Repayment.Source.BORROWER, reference="", recorded_by=None):
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.status not in Loan.REPAYABLE_STATES:
        raise DomainError("This loan is not open for repayment.")
    amount = q2(D(amount))
    if amount <= 0:
        raise DomainError("Amount must be positive.")
    outstanding = loan.outstanding_total()
    if amount > outstanding:
        raise DomainError(f"Amount exceeds the outstanding balance of {outstanding}.")

    now, remaining = timezone.now(), amount
    fee_t = int_t = prin_t = ZERO
    for inst in loan.installments.select_for_update().exclude(status=Installment.Status.PAID).order_by("number"):
        if remaining <= 0:
            break
        for due_f, paid_f in (("late_fee_due", "late_fee_paid"), ("interest_due", "interest_paid"),
                              ("principal_due", "principal_paid")):
            pay = min(remaining, getattr(inst, due_f) - getattr(inst, paid_f))
            if pay > 0:
                setattr(inst, paid_f, getattr(inst, paid_f) + pay)
                remaining -= pay
                if paid_f == "late_fee_paid": fee_t += pay
                elif paid_f == "interest_paid": int_t += pay
                else: prin_t += pay
        if inst.outstanding == 0:
            inst.status, inst.paid_at = Installment.Status.PAID, now
            if now.date() > inst.due_date + timedelta(days=loan.grace_days):
                inst.was_late = True
        elif inst.status == Installment.Status.PENDING:
            inst.status = Installment.Status.PARTIAL
        inst.save()

    rep = Repayment.objects.create(loan=loan, amount=amount, principal_part=prin_t, interest_part=int_t,
                                   fee_part=fee_t, source=source, reference=reference, recorded_by=recorded_by)

    # ---- profit distribution (interest only; late fees are platform income) ----
    inv_amt = q2(int_t * loan.investor_pct / 100)
    gua_amt = q2(int_t * loan.guarantor_pct / 100)
    plat_amt = int_t - inv_amt - gua_amt  # remainder to platform keeps the books exact
    fundings = list(loan.fundings.select_related("investment"))
    per_investor = defaultdict(lambda: ZERO)
    for f, share in zip(fundings, split_pro_rata(inv_amt, [f.amount for f in fundings])):
        per_investor[f.investment.investor_id] += share
    if not fundings:
        plat_amt += inv_amt

    lines = [(ledger.system_account("CASH"), amount, 0),
             (ledger.system_account("RECEIVABLE"), 0, prin_t),
             (ledger.system_account("REVENUE"), 0, plat_amt + fee_t)]
    for uid, share in per_investor.items():
        if share > 0:
            user = User.objects.get(pk=uid)
            lines.append((ledger.get_wallet(user), 0, share))
            Earning.objects.create(user=user, role=Earning.Role.INVESTOR, loan=loan, repayment=rep, amount=share)
    if gua_amt > 0:
        lines.append((ledger.get_wallet(loan.guarantor), 0, gua_amt))
        Earning.objects.create(user=loan.guarantor, role=Earning.Role.GUARANTOR, loan=loan, repayment=rep, amount=gua_amt)
    tx_type = (Transaction.Type.GUARANTOR_PAYMENT if source == Repayment.Source.GUARANTOR
               else Transaction.Type.REPAYMENT)
    ledger.post(tx_type, lines, loan=loan, description=f"Repayment on loan #{loan.pk}", reference=reference,
                created_by=recorded_by)
    funding.release(loan, prin_t)
    log("loan.repayment", recorded_by, loan, amount=amount, principal=prin_t, interest=int_t, fees=fee_t, source=source)

    # ---- loan status ----
    if not loan.installments.exclude(status=Installment.Status.PAID).exists():
        loan.completed_at = now
        transition(loan, S.COMPLETED, recorded_by, "fully repaid")
        loan.claims.filter(status=GuaranteeClaim.Status.OPEN).update(status=GuaranteeClaim.Status.SETTLED, settled_at=now)
        notify(loan.borrower, "Loan fully repaid", f"Loan #{loan.pk} is complete.", kind="loan_completed", loan_id=loan.pk)
    elif loan.status == S.OVERDUE and not loan.installments.filter(status=Installment.Status.OVERDUE).exists():
        transition(loan, S.ACTIVE, recorded_by, "caught up")
    compute_score(loan.borrower)
    fund_waiting_loans()  # returned principal may unlock queued loans
    return rep


@dbtx.atomic
def settle_claim(claim, amount, admin):
    """Guarantor pays toward a defaulted loan; applied through the normal repayment waterfall."""
    claim = GuaranteeClaim.objects.select_for_update().get(pk=claim.pk)
    if claim.status != GuaranteeClaim.Status.OPEN:
        raise DomainError("Claim is not open.")
    amount = q2(D(amount))
    if amount > claim.amount - claim.amount_paid:
        raise DomainError("Amount exceeds the remaining claim.")
    rep = record_repayment(loan=claim.loan, amount=amount, source=Repayment.Source.GUARANTOR,
                           reference=f"claim#{claim.pk}", recorded_by=admin)
    claim.refresh_from_db()
    claim.amount_paid += amount
    if claim.amount_paid >= claim.amount and claim.status == GuaranteeClaim.Status.OPEN:
        claim.status, claim.settled_at = GuaranteeClaim.Status.SETTLED, timezone.now()
    claim.save()
    return rep


# ---------------------------------------------------------------- overdue / default processing
@dbtx.atomic
def process_overdue(today=None):
    today = today or timezone.now().date()
    marked = defaulted = 0
    loans = Loan.objects.select_for_update().filter(status__in=[S.ACTIVE, S.OVERDUE])
    for loan in loans:
        grace = timedelta(days=loan.grace_days)
        late = loan.installments.filter(status__in=[Installment.Status.PENDING, Installment.Status.PARTIAL,
                                                    Installment.Status.OVERDUE], due_date__lt=today - grace)
        for inst in late:
            if inst.status != Installment.Status.OVERDUE:
                inst.status, inst.was_late = Installment.Status.OVERDUE, True
                if inst.late_fee_due == 0 and loan.late_fee_pct:
                    inst.late_fee_due = q2(inst.amount_due * loan.late_fee_pct / 100)
                inst.save()
                marked += 1
        if late.exists() and loan.status == S.ACTIVE:
            transition(loan, S.OVERDUE, note="installment overdue")
            notify(loan.borrower, "Payment overdue", f"An installment on loan #{loan.pk} is overdue.",
                   kind="overdue", loan_id=loan.pk)
        worst = loan.installments.filter(status=Installment.Status.OVERDUE).order_by("due_date").first()
        if worst and today > worst.due_date + timedelta(days=loan.default_after_days):
            transition(loan, S.DEFAULTED, note="default threshold passed")
            claim_amt = q2(loan.outstanding_principal() * loan.guarantor_liability_pct / 100)
            GuaranteeClaim.objects.create(loan=loan, guarantor=loan.guarantor, amount=claim_amt)
            notify(loan.guarantor, "Guarantee called", f"Loan #{loan.pk} defaulted; claim of {claim_amt} opened.",
                   kind="guarantee_claim", loan_id=loan.pk)
            notify(loan.borrower, "Loan defaulted", f"Loan #{loan.pk} is in default.", kind="default", loan_id=loan.pk)
            compute_score(loan.borrower)
            defaulted += 1
    return {"installments_marked": marked, "loans_defaulted": defaulted}
