import logging

from .models import Notification

log = logging.getLogger(__name__)


def send_push(user, notification):
    """Push hook. Plug FCM (firebase-admin) or any provider here; devices are in accounts.DeviceToken."""
    tokens = list(user.devices.values_list("token", flat=True))
    if tokens:
        log.info("push -> %s devices for user %s: %s", len(tokens), user.pk, notification.title)


def notify(user, title, body="", kind="", **data):
    n = Notification.objects.create(user=user, title=title, body=body, kind=kind, data=data)
    try:
        send_push(user, n)
    except Exception:  # never let push failure break a money flow
        log.exception("push failed")
    return n
