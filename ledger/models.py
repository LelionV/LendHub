from django.conf import settings
from django.db import models
from django.db.models import Sum


class Account(models.Model):
    class Kind(models.TextChoices):
        ASSET = "ASSET", "Asset"
        LIABILITY = "LIABILITY", "Liability"
        INCOME = "INCOME", "Income"

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name="ledger_accounts")

    @property
    def balance(self):
        agg = self.entries.aggregate(d=Sum("debit"), c=Sum("credit"))
        d, c = agg["d"] or 0, agg["c"] or 0
        return d - c if self.kind == self.Kind.ASSET else c - d

    def __str__(self):
        return self.code


class Transaction(models.Model):
    class Type(models.TextChoices):
        INVESTMENT = "INVESTMENT", "Investment"
        INVESTMENT_WITHDRAWAL = "INVESTMENT_WITHDRAWAL", "Investment withdrawal"
        DISBURSEMENT = "DISBURSEMENT", "Loan disbursement"
        REPAYMENT = "REPAYMENT", "Repayment"
        GUARANTOR_PAYMENT = "GUARANTOR_PAYMENT", "Guarantor payment"
        EARNINGS_WITHDRAWAL = "EARNINGS_WITHDRAWAL", "Earnings withdrawal"

    type = models.CharField(max_length=32, choices=Type.choices)
    loan = models.ForeignKey("loans.Loan", null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    description = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-id"]

    @property
    def amount(self):
        return self.entries.aggregate(d=Sum("debit"))["d"] or 0


class Entry(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        verbose_name_plural = "entries"

    def save(self, *args, **kwargs):
        if self.pk:
            raise RuntimeError("Ledger entries are append-only; post a reversing transaction instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Ledger entries cannot be deleted.")
