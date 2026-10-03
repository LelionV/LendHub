import csv

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Role, UserRole
from core.exceptions import DomainError
from funding.models import Earning, Investment
from ledger.models import Transaction
from ledger.services import system_account
from loans import services
from loans.models import GuaranteeClaim, Loan, Repayment
from scoring.models import CreditScore

S = Loan.Status


def _sum(qs, f):
    return qs.aggregate(t=Sum(f))["t"] or 0


@staff_member_required
def home(request):
    loans = Loan.objects.all()
    by_status = {r["status"]: r["n"] for r in loans.values("status").annotate(n=Count("id"))}
    disbursed = loans.exclude(status__in=[S.PENDING_GUARANTOR, S.GUARANTOR_REJECTED, S.ADMIN_REVIEW, S.REJECTED,
                                          S.FUNDING, S.CANCELLED])
    n_disb = disbursed.count()
    ctx = {
        "roles": {r.label: UserRole.objects.filter(role=r.value, is_active=True).count() for r in Role},
        "by_status": [(S(k).label, v) for k, v in by_status.items()],
        "pending_review": by_status.get(S.ADMIN_REVIEW, 0),
        "lent_out": _sum(disbursed, "amount"),
        "outstanding": sum(l.outstanding_principal() for l in loans.filter(status__in=Loan.REPAYABLE_STATES)),
        "collected": _sum(Repayment.objects.all(), "amount"),
        "default_rate": round(100 * by_status.get(S.DEFAULTED, 0) / n_disb, 1) if n_disb else 0,
        "platform_revenue": system_account("REVENUE").balance,
        "investor_earnings": _sum(Earning.objects.filter(role="INVESTOR"), "amount"),
        "guarantor_earnings": _sum(Earning.objects.filter(role="GUARANTOR"), "amount"),
        "pool_total": _sum(Investment.objects.filter(status="ACTIVE"), "amount"),
        "pool_available": sum(i.available for i in Investment.objects.filter(status="ACTIVE")),
        "open_claims": GuaranteeClaim.objects.filter(status="OPEN").count(),
    }
    return render(request, "dashboard/home.html", ctx)


@staff_member_required
def loans(request):
    status = request.GET.get("status", S.ADMIN_REVIEW)
    qs = Loan.objects.select_related("borrower", "guarantor", "band")
    if status != "ALL":
        qs = qs.filter(status=status)
    return render(request, "dashboard/loans.html", {"loans": qs[:200], "status": status, "statuses": S.choices})


@staff_member_required
@require_POST
def decide(request, pk):
    loan = get_object_or_404(Loan, pk=pk)
    try:
        services.admin_decide(loan, request.user, request.POST.get("action") == "approve", request.POST.get("note", ""))
        messages.success(request, f"Loan #{pk} updated.")
    except DomainError as e:
        messages.error(request, str(e))
    return redirect("dashboard:loans")


@staff_member_required
@require_POST
def run_overdue(request):
    messages.success(request, f"Processed: {services.process_overdue()}")
    return redirect("dashboard:home")


def _csv(name, header, rows):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    w = csv.writer(resp)
    w.writerow(header)
    w.writerows(rows)
    return resp


@staff_member_required
def export_loans(request):
    return _csv("loan-performance.csv",
                ["id", "borrower", "guarantor", "amount", "term", "rate_pct", "score", "status", "outstanding_principal", "created"],
                [(l.id, l.borrower, l.guarantor, l.amount, l.term_months, l.interest_rate_pct, l.score_at_application,
                  l.status, l.outstanding_principal(), l.created_at.date()) for l in Loan.objects.select_related("borrower", "guarantor")])


@staff_member_required
def export_transactions(request):
    return _csv("transactions.csv", ["id", "date", "type", "loan", "amount", "description"],
                [(t.id, t.created_at.isoformat(), t.type, t.loan_id, t.amount, t.description) for t in Transaction.objects.all()])
