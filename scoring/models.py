from django.conf import settings
from django.db import models


class CreditScore(models.Model):
    """Immutable snapshot of a borrower's score and how it was computed."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_scores")
    score = models.PositiveIntegerField()
    breakdown = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class ScoreAdjustment(models.Model):
    """Admin-defined manual criteria: add/subtract points (e.g. verified employer, blacklist)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="score_adjustments")
    points = models.IntegerField(help_text="Positive or negative points added to the computed score")
    reason = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
