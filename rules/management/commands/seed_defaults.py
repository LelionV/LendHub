from decimal import Decimal

from django.core.management.base import BaseCommand

from accounts.models import Role, User, UserRole
from ledger.services import system_account
from rules.models import DEFAULT_SETTINGS, DistributionPolicy, LoanProduct, PlatformSetting, ScoreBand, ScoreFactor

FACTORS = [("repayment_history", 3), ("late_payments", 2), ("previous_loans", "1.5"),
           ("outstanding_balance", "1.5"), ("loan_frequency", 1)]
BANDS = [("Very low", 300, 449, 30, 5000, 3), ("Low", 450, 549, 24, 20000, 6), ("Fair", 550, 649, 20, 50000, 12),
         ("Good", 650, 749, 16, 100000, 18), ("Excellent", 750, 850, 12, 250000, 24)]


class Command(BaseCommand):
    help = "Create default (editable) rules, system ledger accounts; --demo adds demo users."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true")

    def handle(self, *args, **opts):
        for code, w in FACTORS:
            ScoreFactor.objects.get_or_create(code=code, defaults={"weight": Decimal(str(w))})
        for name, lo, hi, rate, mx, term in BANDS:
            ScoreBand.objects.get_or_create(name=name, defaults=dict(
                min_score=lo, max_score=hi, interest_rate_pct=rate, max_loan_amount=mx, max_term_months=term))
        LoanProduct.objects.get_or_create(name="Standard loan", defaults=dict(
            min_amount=1000, max_amount=250000, allowed_terms="3,6,12,18,24", origination_fee_pct=2,
            late_fee_pct=5, grace_days=3, default_after_days=60, guarantor_liability_pct=100))
        if not DistributionPolicy.objects.exists():
            DistributionPolicy.objects.create(name="Default split", investor_pct=60, guarantor_pct=10, platform_pct=30)
        for k, (v, d) in DEFAULT_SETTINGS.items():
            PlatformSetting.objects.get_or_create(key=k, defaults={"value": v, "description": d})
        for code in ("CASH", "RECEIVABLE", "POOL", "REVENUE"):
            system_account(code)
        self.stdout.write(self.style.SUCCESS("Defaults seeded."))
        if opts["demo"]:
            for uname, roles in [("demo_borrower", [Role.BORROWER]), ("demo_guarantor", [Role.GUARANTOR]),
                                 ("demo_investor", [Role.INVESTOR])]:
                u, created = User.objects.get_or_create(username=uname, defaults={"email": f"{uname}@example.com"})
                if created:
                    u.set_password("demo12345")
                    u.save()
                for r in roles:
                    UserRole.objects.get_or_create(user=u, role=r)
            self.stdout.write("Demo users created (password: demo12345).")
