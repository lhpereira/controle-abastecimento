from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


class OptionalLoginRequiredMiddleware:
    """Protege a aplicação quando APP_REQUIRE_LOGIN estiver ativado."""

    public_prefixes = ("/conta/", "/admin/login/", "/health/", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.APP_REQUIRE_LOGIN
            and not request.user.is_authenticated
            and not request.path.startswith(self.public_prefixes)
        ):
            login_url = reverse(settings.LOGIN_URL)
            return redirect(f"{login_url}?{urlencode({'next': request.path})}")
        return self.get_response(request)
