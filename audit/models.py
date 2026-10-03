from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise RuntimeError("Audit events are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit events cannot be deleted.")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
