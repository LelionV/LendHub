from django.conf import settings
from django.db import models


class Investment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    investor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="investments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    allocated = models.DecimalField("Currently lent out", max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]

    @property
    def available(self):
        return self.amount - self.allocated


class LoanFunding(models.Model):
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="fundings")
    investment = models.ForeignKey(Investment, on_delete=models.PROTECT, related_name="fundings")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    returned = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    @property
    def outstanding(self):
        return self.amount - self.returned


class Earning(models.Model):
    class Role(models.TextChoices):
        INVESTOR = "INVESTOR", "Investor"
        GUARANTOR = "GUARANTOR", "Guarantor"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="earnings")
    role = models.CharField(max_length=10, choices=Role.choices)
    loan = models.ForeignKey("loans.Loan", on_delete=models.PROTECT, related_name="earnings")
    repayment = models.ForeignKey("loans.Repayment", on_delete=models.PROTECT, related_name="earnings")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
