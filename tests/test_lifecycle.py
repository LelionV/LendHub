from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Role
from core.exceptions import DomainError
from funding import services as funding
from funding.models import Earning, Investment
from ledger.models import Account, Entry
from ledger.services import system_account, wallet_balance
from loans import services
from loans.models import GuaranteeClaim, Loan
from rules.models import DistributionPolicy, LoanProduct, PlatformSetting, ScoreBand
from tests.conftest import client_for, make_user

D = Decimal


def product(): return LoanProduct.objects.first()


def assert_books_balance():
    t = Entry.objects.aggregate(d=Sum("debit"), c=Sum("credit"))
    assert t["d"] == t["c"]


def new_loan(borrower, guarantor, amount="10000", term=6):
    return services.apply_for_loan(borrower=borrower, guarantor=guarantor, product=product(), amount=amount,
                                   term_months=term)


def test_registration_and_login_via_api(seeded):
    from rest_framework.test import APIClient
    c = APIClient()
    r = c.post("/api/v1/auth/register/", {"username": "amy", "password": "S3cure-pass!", "roles": ["BORROWER", "INVESTOR"]}, format="json")
    assert r.status_code == 201 and set(r.data["roles"]) == {"BORROWER", "INVESTOR"}
    tok = c.post("/api/v1/auth/login/", {"username": "amy", "password": "S3cure-pass!"}, format="json")
    assert tok.status_code == 200 and "access" in tok.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok.data['access']}")
    assert c.get("/api/v1/me/").data["username"] == "amy"
    assert c.get("/api/v1/credit-score/").data["score"] == 500


def test_guarantor_rules(borrower, guarantor, investor):
    with pytest.raises(DomainError, match="guarantor is required"):
        services.apply_for_loan(borrower=borrower, guarantor=None, product=product(), amount=5000, term_months=3)
    with pytest.raises(DomainError, match="own loan"):
        services.apply_for_loan(borrower=borrower, guarantor=borrower, product=product(), amount=5000, term_months=3)
    with pytest.raises(DomainError, match="not a registered guarantor"):
        services.apply_for_loan(borrower=borrower, guarantor=investor, product=product(), amount=5000, term_months=3)


def test_limits_come_from_database(borrower, guarantor):
    with pytest.raises(DomainError, match="at most"):  # new borrower scores 500 -> 'Low' band max 20000
        new_loan(borrower, guarantor, amount="30000", term=6)
    band = ScoreBand.objects.get(name="Low")
    band.max_loan_amount = D("40000")
    band.save()
    assert new_loan(borrower, guarantor, amount="30000", term=6).status == Loan.Status.PENDING_GUARANTOR


def test_guarantor_reject_blocks_funding(borrower, guarantor, admin):
    loan = new_loan(borrower, guarantor)
    services.guarantor_decide(loan, guarantor, False, "no")
    loan.refresh_from_db()
    assert loan.status == Loan.Status.GUARANTOR_REJECTED
    with pytest.raises(DomainError):
        services.admin_decide(loan, admin, True)


def test_only_addressed_guarantor_can_decide(borrower, guarantor):
    loan = new_loan(borrower, guarantor)
    other = make_user("other", Role.GUARANTOR)
    with pytest.raises(DomainError, match="not addressed"):
        services.guarantor_decide(loan, other, True)


def test_admin_cannot_skip_guarantor(borrower, guarantor, admin):
    loan = new_loan(borrower, guarantor)
    with pytest.raises(DomainError):
        services.admin_decide(loan, admin, True)


def test_full_lifecycle_and_profit_distribution(borrower, guarantor, investor, admin):
    inv2 = make_user("iris", Role.INVESTOR)
    funding.invest(investor, "30000")
    funding.invest(inv2, "10000")
    loan = new_loan(borrower, guarantor, "10000", 6)
    # 'Low' band: 24% annual flat, 6 months => 1200 interest; 2% fee => 200
    assert loan.total_interest == D("1200.00") and loan.origination_fee == D("200.00")
    services.guarantor_decide(loan, guarantor, True)
    services.admin_decide(loan, admin, True)
    loan.refresh_from_db()
    assert loan.status == Loan.Status.ACTIVE
    assert loan.installments.count() == 6
    assert sum(i.principal_due for i in loan.installments.all()) == D("10000.00")
    # pro-rata funding 75/25
    assert sorted(f.amount for f in loan.fundings.all()) == [D("2500.00"), D("7500.00")]
    assert system_account("RECEIVABLE").balance == D("10000.00")

    # policy changes after application must not affect this loan
    DistributionPolicy.objects.create(name="Greedy", investor_pct=10, guarantor_pct=10, platform_pct=80)

    services.record_repayment(loan=loan, amount=loan.total_repayable, recorded_by=borrower)
    loan.refresh_from_db()
    assert loan.status == Loan.Status.COMPLETED
    assert wallet_balance(investor) == D("540.00")      # 60% of 1200 = 720 -> 75% of it
    assert wallet_balance(inv2) == D("180.00")
    assert wallet_balance(guarantor) == D("120.00")     # 10%
    assert system_account("REVENUE").balance == D("200.00") + D("360.00")  # fee + 30% platform
    assert system_account("RECEIVABLE").balance == 0
    assert all(i.allocated == 0 for i in Investment.objects.all())  # principal back in the pool
    assert Earning.objects.filter(role="GUARANTOR").aggregate(t=Sum("amount"))["t"] == D("120.00")
    assert_books_balance()
    # earnings can be withdrawn, but not more than the balance
    funding.withdraw_earnings(investor, "540")
    with pytest.raises(DomainError):
        funding.withdraw_earnings(investor, "1")
    assert_books_balance()


def test_partial_payments_and_overpayment(borrower, guarantor, investor, admin):
    funding.invest(investor, "50000")
    loan = new_loan(borrower, guarantor, "6000", 3)
    services.guarantor_decide(loan, guarantor, True)
    services.admin_decide(loan, admin, True)
    rep = services.record_repayment(loan=loan, amount="1000", recorded_by=borrower)
    assert rep.interest_part + rep.principal_part == D("1000.00")
    first = loan.installments.get(number=1)
    assert first.status == "PARTIAL"
    with pytest.raises(DomainError, match="exceeds"):
        services.record_repayment(loan=loan, amount="999999", recorded_by=borrower)
    assert_books_balance()


def test_loan_waits_for_funding_then_auto_funds(borrower, guarantor, investor, admin):
    loan = new_loan(borrower, guarantor, "5000", 3)
    services.guarantor_decide(loan, guarantor, True)
    services.admin_decide(loan, admin, True)
    loan.refresh_from_db()
    assert loan.status == Loan.Status.FUNDING
    funding.invest(investor, "5000")
    loan.refresh_from_db()
    assert loan.status == Loan.Status.ACTIVE


def test_overdue_default_claim_and_settlement(borrower, guarantor, investor, admin):
    funding.invest(investor, "50000")
    loan = new_loan(borrower, guarantor, "6000", 3)
    services.guarantor_decide(loan, guarantor, True)
    services.admin_decide(loan, admin, True)
    today = timezone.now().date()

    services.process_overdue(today + timedelta(days=40))   # first installment ~30d due, grace 3d
    loan.refresh_from_db()
    assert loan.status == Loan.Status.OVERDUE
    assert loan.installments.get(number=1).late_fee_due > 0
    services.process_overdue(today + timedelta(days=40))   # idempotent: fee charged once
    fee = loan.installments.get(number=1).late_fee_due

    services.process_overdue(today + timedelta(days=120))
    loan.refresh_from_db()
    assert loan.status == Loan.Status.DEFAULTED
    assert loan.installments.get(number=1).late_fee_due == fee
    claim = GuaranteeClaim.objects.get(loan=loan)
    assert claim.guarantor == guarantor and claim.amount == loan.outstanding_principal()
    with pytest.raises(DomainError):  # defaulted borrower cannot take a new loan
        new_loan(borrower, guarantor, "1000", 3)

    services.settle_claim(claim, claim.amount, admin)
    claim.refresh_from_db()
    assert claim.status == GuaranteeClaim.Status.SETTLED
    assert_books_balance()


def test_distribution_policy_must_total_100(seeded):
    with pytest.raises(Exception):
        DistributionPolicy.objects.create(name="bad", investor_pct=50, guarantor_pct=10, platform_pct=30)


def test_guarantor_exposure_cap(borrower, guarantor):
    PlatformSetting.objects.filter(key="GUARANTOR_MAX_EXPOSURE").update(value="6000")
    loan = new_loan(borrower, guarantor, "5000", 3)
    services.guarantor_decide(loan, guarantor, True)
    b2 = make_user("bea", Role.BORROWER)
    with pytest.raises(DomainError, match="limit"):
        new_loan(b2, guarantor, "5000", 3)


def test_score_improves_after_repaying(borrower, guarantor, investor, admin):
    funding.invest(investor, "50000")
    loan = new_loan(borrower, guarantor, "5000", 3)
    services.guarantor_decide(loan, guarantor, True)
    services.admin_decide(loan, admin, True)
    before = loan.score_at_application
    services.record_repayment(loan=loan, amount=loan.total_repayable, recorded_by=borrower)
    from scoring.services import compute_score
    assert compute_score(borrower, persist=False)["score"] > before


def test_api_end_to_end(borrower, guarantor, investor, admin):
    b, g, i = client_for(borrower), client_for(guarantor), client_for(investor)
    assert i.post("/api/v1/investments/", {"amount": "20000"}, format="json").status_code == 201
    assert i.get("/api/v1/investments/summary/").data["available"] == D("20000.00")
    gs = b.get("/api/v1/guarantors/?q=gin").data["results"]
    assert gs[0]["username"] == "gina"
    prod = b.get("/api/v1/loan-products/").data[0]
    q = b.post("/api/v1/loans/quote/", {"product_id": prod["id"], "amount": "5000", "term_months": 6}, format="json")
    assert q.status_code == 200 and q.data["rate"] == D("24.00")
    r = b.post("/api/v1/loans/", {"product_id": prod["id"], "amount": "5000", "term_months": 6,
                                  "guarantor_id": guarantor.pk}, format="json")
    assert r.status_code == 201, r.data
    loan_id = r.data["id"]
    assert g.get("/api/v1/guarantees/requests/?status=pending").data["results"][0]["id"] == loan_id
    assert g.get("/api/v1/notifications/").data["results"][0]["kind"] == "guarantee_request"
    # borrower cannot approve their own request
    assert b.post(f"/api/v1/guarantees/requests/{loan_id}/approve/").status_code == 404
    assert g.post(f"/api/v1/guarantees/requests/{loan_id}/approve/", {"note": "known him"}, format="json").status_code == 200
    services.admin_decide(Loan.objects.get(pk=loan_id), admin, True)
    d = b.get(f"/api/v1/loans/{loan_id}/").data
    assert d["status"] == "ACTIVE" and len(d["installments"]) == 6
    pay = b.post(f"/api/v1/loans/{loan_id}/repay/", {"amount": "1000", "reference": "TX1"}, format="json")
    assert pay.status_code == 201
    assert b.get("/api/v1/transactions/").data["count"] >= 2
    assert i.get("/api/v1/investments/earnings/").data["total"] > 0
    assert g.get("/api/v1/guarantor/earnings/").data["total"] > 0
    assert i.get("/api/v1/guarantees/requests/").data["results"] == []
    # unrelated users cannot read the loan
    assert i.get(f"/api/v1/loans/{loan_id}/").status_code == 404


def test_dashboard_access_and_review(borrower, guarantor, investor, admin):
    from django.test import Client
    funding.invest(investor, "20000")
    loan = new_loan(borrower, guarantor, "5000", 3)
    services.guarantor_decide(loan, guarantor, True)
    c = Client()
    assert c.get("/dashboard/").status_code == 302  # anonymous -> login
    c.force_login(admin)
    assert c.get("/dashboard/").status_code == 200
    assert c.get("/dashboard/loans/").status_code == 200
    assert c.post(f"/dashboard/loans/{loan.pk}/decide/", {"action": "approve"}).status_code == 302
    loan.refresh_from_db()
    assert loan.status == Loan.Status.ACTIVE
    assert c.get("/dashboard/export/loans.csv").status_code == 200
    assert c.get("/dashboard/export/transactions.csv").status_code == 200
    assert c.get("/admin/loans/loan/").status_code == 200
