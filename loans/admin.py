from django.contrib import admin, messages

from core.exceptions import DomainError

from . import services
from .models import GuaranteeClaim, Installment, Loan, Repayment


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in Installment._meta.fields if f.name != "loan"]

    def has_add_permission(self, request, obj=None): return False


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("id", "borrower", "guarantor", "amount", "term_months", "interest_rate_pct", "status",
                    "score_at_application", "created_at")
    list_filter = ("status", "product", "band")
    search_fields = ("borrower__username", "guarantor__username")
    inlines = [InstallmentInline]
    actions = ["approve_selected", "reject_selected"]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Loan._meta.fields]  # state only changes through services (audited)

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False

    def _decide(self, request, qs, approve):
        for loan in qs:
            try:
                services.admin_decide(loan, request.user, approve)
            except DomainError as e:
                self.message_user(request, f"Loan #{loan.pk}: {e}", messages.WARNING)

    @admin.action(description="Approve selected loans (awaiting admin approval)")
    def approve_selected(self, request, qs): self._decide(request, qs, True)

    @admin.action(description="Reject selected loans")
    def reject_selected(self, request, qs): self._decide(request, qs, False)


@admin.register(Repayment)
class RepaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "loan", "amount", "principal_part", "interest_part", "fee_part", "source", "created_at")

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(GuaranteeClaim)
class GuaranteeClaimAdmin(admin.ModelAdmin):
    list_display = ("id", "loan", "guarantor", "amount", "amount_paid", "status")
    list_filter = ("status",)
    actions = ["waive"]

    @admin.action(description="Waive selected claims")
    def waive(self, request, qs):
        qs.filter(status=GuaranteeClaim.Status.OPEN).update(status=GuaranteeClaim.Status.WAIVED)
