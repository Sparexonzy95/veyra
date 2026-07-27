import uuid
from django.conf import settings
from django.http import JsonResponse
from common.logging import set_request_id

class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex
        request.request_id = request_id
        set_request_id(request_id)
        response = self.get_response(request)
        response['X-Request-ID'] = request_id
        return response

class AllowedOriginMiddleware:
    MUTATING = {'POST', 'PUT', 'PATCH', 'DELETE'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in self.MUTATING:
            origin = request.headers.get('Origin')
            cookie_authenticated = any(
                request.COOKIES.get(cookie_name)
                for cookie_name in (
                    settings.VEYRA_SESSION_COOKIE,
                    settings.VEYRA_ONBOARDING_COOKIE,
                )
            )
            if cookie_authenticated and not origin:
                return JsonResponse(
                    {'detail': 'Origin is required for cookie-authenticated changes.'},
                    status=403,
                )
            if origin and origin not in settings.VEYRA_ALLOWED_ORIGINS:
                return JsonResponse({'detail': 'Origin is not allowed.'}, status=403)
        return self.get_response(request)
