from django.contrib import admin

from .models import Earning, Investment, LoanFunding


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ("id", "investor", "amount", "allocated", "status", "created_at")
    list_filter = ("status",)

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Earning)
class EarningAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "role", "loan", "amount", "created_at")
    list_filter = ("role",)

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


admin.site.register(LoanFunding)
