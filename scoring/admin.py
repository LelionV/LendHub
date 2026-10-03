from django.contrib import admin

from audit.services import log

from .models import CreditScore, ScoreAdjustment


@admin.register(CreditScore)
class CreditScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "score", "created_at")
    search_fields = ("user__username",)
    readonly_fields = ("user", "score", "breakdown", "created_at")

    def has_add_permission(self, request): return False


@admin.register(ScoreAdjustment)
class ScoreAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("user", "points", "reason", "active", "created_at")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        log("score.adjustment", request.user, obj, user=obj.user_id, points=obj.points, reason=obj.reason)
