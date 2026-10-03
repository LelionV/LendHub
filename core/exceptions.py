from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler


class DomainError(Exception):
    """A business-rule violation. Surfaces as HTTP 400 {"detail": ...}."""


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"detail": str(exc)}, status=400)
    if isinstance(exc, ValidationError):
        return Response({"detail": "; ".join(exc.messages)}, status=400)
    return exception_handler(exc, context)
