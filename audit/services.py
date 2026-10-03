from .models import AuditEvent


def log(action, actor=None, obj=None, **data):
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        data=data,
    )
