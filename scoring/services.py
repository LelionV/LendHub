from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from core.money import D
from rules.models import ScoreBand, ScoreFactor
from rules.services import get_setting

from .models import CreditScore, ScoreAdjustment

SCORE_MIN, SCORE_MAX = 300, 850


def _stats(user):
    from loans.models import Installment, Loan
    loans = Loan.objects.filter(borrower=user)
    disbursed = loans.exclude(status__in=[Loan.Status.PENDING_GUARANTOR, Loan.Status.GUARANTOR_REJECTED,
                                         Loan.Status.ADMIN_REVIEW, Loan.Status.REJECTED,
                                         Loan.Status.FUNDING, Loan.Status.CANCELLED])
    insts = Installment.objects.filter(loan__in=disbursed)
    today = timezone.now().date()
    due = insts.filter(due_date__lt=today) | insts.filter(status=Installment.Status.PAID)
    due = due.distinct()
    on_time = due.filter(status=Installment.Status.PAID, was_late=False).count()
    outstanding = 0
    for l in disbursed.filter(status__in=[Loan.Status.ACTIVE, Loan.Status.OVERDUE, Loan.Status.DEFAULTED]):
        outstanding += l.outstanding_principal()
    return {
        "loans_total": disbursed.count(),
        "due_installments": due.count(),
        "on_time": on_time,
        "late": insts.filter(was_late=True).count(),
        "defaults": disbursed.filter(status=Loan.Status.DEFAULTED).count(),
        "completed": disbursed.filter(status=Loan.Status.COMPLETED).count(),
        "recent_loans": disbursed.filter(disbursed_at__gte=timezone.now() - timedelta(days=365)).count(),
        "outstanding": float(outstanding),
    }


def _factor_values(s):
    ref = float(get_setting("SCORE_BALANCE_REFERENCE", float)) or 1
    n = s["recent_loans"]
    return {
        "repayment_history": (s["on_time"] / s["due_installments"]) if s["due_installments"] else 0.5,
        "previous_loans": min(1.0, s["completed"] / 5),
        "late_payments": 1 - min(1.0, (s["late"] + 5 * s["defaults"]) / 5),
        "outstanding_balance": 1 - min(1.0, s["outstanding"] / ref),
        "loan_frequency": 1.0 if n <= 2 else 1 - min(1.0, (n - 2) / 4),
    }


def compute_score(user, persist=True) -> dict:
    s = _stats(user)
    adj = ScoreAdjustment.objects.filter(user=user, active=True).aggregate(p=Sum("points"))["p"] or 0
    if s["loans_total"] == 0:
        base = get_setting("NEW_BORROWER_SCORE", int)
        breakdown = {"new_borrower": True, "base": base}
    else:
        values = _factor_values(s)
        factors = list(ScoreFactor.objects.filter(active=True))
        wsum = sum(float(f.weight) for f in factors) or 1
        weighted = sum(float(f.weight) * values.get(f.code, 0.5) for f in factors) / wsum
        base = round(SCORE_MIN + (SCORE_MAX - SCORE_MIN) * weighted)
        breakdown = {"factors": {f.code: round(values.get(f.code, 0.5), 3) for f in factors}, "stats": s}
    score = max(SCORE_MIN, min(SCORE_MAX, base + adj))
    breakdown["adjustments"] = adj
    band = ScoreBand.objects.filter(active=True, min_score__lte=score, max_score__gte=score).first()
    if persist:
        CreditScore.objects.create(user=user, score=score, breakdown=breakdown)
    return {"score": score, "band": band, "breakdown": breakdown}
