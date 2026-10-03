from django.contrib import admin

from .models import Account, Entry, Transaction


class EntryInline(admin.TabularInline):
    model = Entry
    extra = 0
    can_delete = False
    readonly_fields = ("account", "debit", "credit")

    def has_add_permission(self, request, obj=None): return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "type", "loan", "amount", "description")
    list_filter = ("type",)
    inlines = [EntryInline]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "user", "balance")
    search_fields = ("code", "name", "user__username")

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
