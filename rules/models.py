from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ScoreFactor(models.Model):
    """Weight/enable each scoring factor. Weights are relative (they are normalised)."""
    class Code(models.TextChoices):
        REPAYMENT_HISTORY = "repayment_history", "Repayment history"
        PREVIOUS_LOANS = "previous_loans", "Previous (completed) loans"
        LATE_PAYMENTS = "late_payments", "Late payments / defaults"
        OUTSTANDING_BALANCE = "outstanding_balance", "Outstanding balance"
        LOAN_FREQUENCY = "loan_frequency", "Loan frequency (last 12 months)"

    code = models.CharField(max_length=32, choices=Code.choices, unique=True)
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    active = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.get_code_display()


class ScoreBand(models.Model):
    """Credit-score range -> pricing and limits."""
    name = models.CharField(max_length=60)
    min_score = models.PositiveIntegerField()
    max_score = models.PositiveIntegerField()
    interest_rate_pct = models.DecimalField("Annual flat interest %", max_digits=5, decimal_places=2)
    max_loan_amount = models.DecimalField(max_digits=14, decimal_places=2)
    max_term_months = models.PositiveIntegerField()
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["min_score"]

    def clean(self):
        if self.min_score > self.max_score:
            raise ValidationError("min_score must be <= max_score.")
        overlap = ScoreBand.objects.filter(active=True, min_score__lte=self.max_score, max_score__gte=self.min_score)
        if self.pk:
            overlap = overlap.exclude(pk=self.pk)
        if self.active and overlap.exists():
            raise ValidationError(f"Score range overlaps with band '{overlap.first().name}'.")

    def __str__(self):
        return f"{self.name} ({self.min_score}-{self.max_score})"


class LoanProduct(models.Model):
    name = models.CharField(max_length=80)
    min_amount = models.DecimalField(max_digits=14, decimal_places=2)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2)
    allowed_terms = models.CharField("Allowed terms (months, comma separated)", max_length=100, default="3,6,12")
    origination_fee_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    late_fee_pct = models.DecimalField("Late fee % of installment (charged once)", max_digits=5, decimal_places=2, default=0)
    grace_days = models.PositiveIntegerField(default=0)
    default_after_days = models.PositiveIntegerField("Days past due before default", default=60)
    guarantor_liability_pct = models.DecimalField("Guarantor liability % of outstanding on default",
                                                  max_digits=5, decimal_places=2, default=100)
    active = models.BooleanField(default=True)

    def terms(self):
        return [int(t) for t in self.allowed_terms.replace(" ", "").split(",") if t]

    def __str__(self):
        return self.name


class DistributionPolicy(models.Model):
    """How the interest earned on a repayment is shared. Newest active policy applies to new loans."""
    name = models.CharField(max_length=80)
    investor_pct = models.DecimalField(max_digits=5, decimal_places=2)
    guarantor_pct = models.DecimalField(max_digits=5, decimal_places=2)
    platform_pct = models.DecimalField(max_digits=5, decimal_places=2)
    effective_from = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "distribution policies"
        ordering = ["-effective_from", "-id"]

    def clean(self):
        total = (self.investor_pct or 0) + (self.guarantor_pct or 0) + (self.platform_pct or 0)
        if Decimal(total) != Decimal("100"):
            raise ValidationError(f"Percentages must add up to 100 (currently {total}).")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name}: {self.investor_pct}/{self.guarantor_pct}/{self.platform_pct}"


class PlatformSetting(models.Model):
    key = models.CharField(max_length=64, unique=True)
    value = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.key}={self.value}"


DEFAULT_SETTINGS = {
    "CURRENCY": ("KES", "Display currency code"),
    "MAX_ACTIVE_LOANS": ("1", "Max simultaneous open loans per borrower"),
    "GUARANTOR_MAX_EXPOSURE": ("0", "Max total principal one guarantor can back at once (0 = unlimited)"),
    "NEW_BORROWER_SCORE": ("500", "Score given to borrowers with no loan history"),
    "SCORE_BALANCE_REFERENCE": ("100000", "Outstanding principal that scores 0 on the balance factor"),
    "MIN_INVESTMENT": ("1000", "Minimum single investment"),
}
