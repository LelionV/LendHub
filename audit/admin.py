from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "object_type", "object_id")
    list_filter = ("action", "object_type")
    search_fields = ("action", "object_id", "actor__username")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
