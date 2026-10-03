from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Sum


class Loan(models.Model):
    class Status(models.TextChoices):
        PENDING_GUARANTOR = "PENDING_GUARANTOR", "Awaiting guarantor"
        GUARANTOR_REJECTED = "GUARANTOR_REJECTED", "Rejected by guarantor"
        ADMIN_REVIEW = "ADMIN_REVIEW", "Awaiting admin approval"
        REJECTED = "REJECTED", "Rejected by admin"
        FUNDING = "FUNDING", "Approved, awaiting funding"
        ACTIVE = "ACTIVE", "Active"
        OVERDUE = "OVERDUE", "Overdue"
        DEFAULTED = "DEFAULTED", "Defaulted"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    TRANSITIONS = {
        Status.PENDING_GUARANTOR: {Status.ADMIN_REVIEW, Status.GUARANTOR_REJECTED, Status.CANCELLED},
        Status.ADMIN_REVIEW: {Status.FUNDING, Status.REJECTED, Status.CANCELLED},
        Status.FUNDING: {Status.ACTIVE, Status.CANCELLED},
        Status.ACTIVE: {Status.OVERDUE, Status.COMPLETED},
        Status.OVERDUE: {Status.ACTIVE, Status.DEFAULTED, Status.COMPLETED},
        Status.DEFAULTED: {Status.COMPLETED},
    }
    OPEN_STATES = (Status.PENDING_GUARANTOR, Status.ADMIN_REVIEW, Status.FUNDING, Status.ACTIVE, Status.OVERDUE)
    EXPOSURE_STATES = (Status.ADMIN_REVIEW, Status.FUNDING, Status.ACTIVE, Status.OVERDUE)
    REPAYABLE_STATES = (Status.ACTIVE, Status.OVERDUE, Status.DEFAULTED)

    borrower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loans_borrowed")
    guarantor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loans_guaranteed")
    product = models.ForeignKey("rules.LoanProduct", on_delete=models.PROTECT)
    band = models.ForeignKey("rules.ScoreBand", on_delete=models.PROTECT)
    policy = models.ForeignKey("rules.DistributionPolicy", on_delete=models.PROTECT)

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    term_months = models.PositiveIntegerField()
    purpose = models.CharField(max_length=255, blank=True)
    score_at_application = models.PositiveIntegerField()

    # Snapshots of the rules in force at application time: later admin edits never change existing loans.
    interest_rate_pct = models.DecimalField(max_digits=5, decimal_places=2)
    investor_pct = models.DecimalField(max_digits=5, decimal_places=2)
    guarantor_pct = models.DecimalField(max_digits=5, decimal_places=2)
    platform_pct = models.DecimalField(max_digits=5, decimal_places=2)
    late_fee_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    grace_days = models.PositiveIntegerField(default=0)
    default_after_days = models.PositiveIntegerField(default=60)
    guarantor_liability_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100)

    origination_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_interest = models.DecimalField(max_digits=14, decimal_places=2)
    total_repayable = models.DecimalField(max_digits=14, decimal_places=2)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_GUARANTOR, db_index=True)
    guarantor_decided_at = models.DateTimeField(null=True, blank=True)
    guarantor_note = models.CharField(max_length=255, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.CharField(max_length=255, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        constraints = [models.CheckConstraint(condition=~Q(guarantor=F("borrower")), name="loan_guarantor_not_borrower")]

    def outstanding_principal(self):
        agg = self.installments.aggregate(d=Sum("principal_due"), p=Sum("principal_paid"))
        return (agg["d"] or Decimal("0")) - (agg["p"] or Decimal("0"))

    def outstanding_total(self):
        total = Decimal("0")
        for i in self.installments.all():
            total += i.outstanding
        return total

    def __str__(self):
        return f"Loan #{self.pk} {self.borrower} {self.amount}"


class Installment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PARTIAL = "PARTIAL", "Partially paid"
        PAID = "PAID", "Paid"
        OVERDUE = "OVERDUE", "Overdue"

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveIntegerField()
    due_date = models.DateField()
    principal_due = models.DecimalField(max_digits=14, decimal_places=2)
    interest_due = models.DecimalField(max_digits=14, decimal_places=2)
    late_fee_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    principal_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    interest_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    late_fee_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    was_late = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["loan_id", "number"]
        unique_together = [("loan", "number")]

    @property
    def amount_due(self):
        return self.principal_due + self.interest_due + self.late_fee_due

    @property
    def outstanding(self):
        return self.amount_due - (self.principal_paid + self.interest_paid + self.late_fee_paid)


class Repayment(models.Model):
    class Source(models.TextChoices):
        BORROWER = "BORROWER", "Borrower"
        GUARANTOR = "GUARANTOR", "Guarantor (default claim)"

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="repayments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    principal_part = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    interest_part = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    fee_part = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.BORROWER)
    reference = models.CharField(max_length=120, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class GuaranteeClaim(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        SETTLED = "SETTLED", "Settled"
        WAIVED = "WAIVED", "Waived"

    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="claims")
    guarantor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="claims")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)
