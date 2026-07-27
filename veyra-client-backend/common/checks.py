from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def veyra_deployment_checks(app_configs, **kwargs):
    errors = []
    if settings.DEBUG:
        return errors
    if settings.SECRET_KEY == "dev-only-change-me" or len(settings.SECRET_KEY) < 32:
        errors.append(
            Error(
                "Production must use a strong DJANGO_SECRET_KEY.",
                id="veyra.E001",
            )
        )
    if not settings.SESSION_COOKIE_SECURE:
        errors.append(
            Error(
                "Production session and CSRF cookies must be Secure.",
                hint="Set SESSION_COOKIE_SECURE=True.",
                id="veyra.E002",
            )
        )
    return errors
