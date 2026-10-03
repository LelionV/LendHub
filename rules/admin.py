from django.contrib import admin

from audit.services import log

from .models import DistributionPolicy, LoanProduct, PlatformSetting, ScoreBand, ScoreFactor


class AuditedAdmin(admin.ModelAdmin):
    """Every change to a business rule is written to the audit trail."""
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        log("rule.updated" if change else "rule.created", request.user, obj,
            changed=form.changed_data, repr=str(obj))

    def delete_model(self, request, obj):
        log("rule.deleted", request.user, obj, repr=str(obj))
        super().delete_model(request, obj)


@admin.register(ScoreFactor)
class ScoreFactorAdmin(AuditedAdmin):
    list_display = ("code", "weight", "active", "description")
    list_editable = ("weight", "active")


@admin.register(ScoreBand)
class ScoreBandAdmin(AuditedAdmin):
    list_display = ("name", "min_score", "max_score", "interest_rate_pct", "max_loan_amount", "max_term_months", "active")


@admin.register(LoanProduct)
class LoanProductAdmin(AuditedAdmin):
    list_display = ("name", "min_amount", "max_amount", "allowed_terms", "origination_fee_pct", "late_fee_pct", "active")


@admin.register(DistributionPolicy)
class DistributionPolicyAdmin(AuditedAdmin):
    list_display = ("name", "investor_pct", "guarantor_pct", "platform_pct", "effective_from", "active")


@admin.register(PlatformSetting)
class PlatformSettingAdmin(AuditedAdmin):
    list_display = ("key", "value", "description")
