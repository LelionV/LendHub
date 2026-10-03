from django.utils import timezone

from core.exceptions import DomainError

from .models import DEFAULT_SETTINGS, DistributionPolicy, PlatformSetting


def get_setting(key, cast=str):
    try:
        raw = PlatformSetting.objects.get(key=key).value
    except PlatformSetting.DoesNotExist:
        raw = DEFAULT_SETTINGS[key][0]
    return cast(raw)


def current_policy() -> DistributionPolicy:
    p = DistributionPolicy.objects.filter(active=True, effective_from__lte=timezone.now()).first()
    if not p:
        raise DomainError("No active profit-distribution policy is configured.")
    return p
