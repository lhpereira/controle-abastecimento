import os
import sys
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


# Seguro por padrão: o modo de desenvolvimento precisa ser pedido explicitamente.
DEBUG = env_bool("DJANGO_DEBUG", False)
# "manage.py test" roda sem .env: usa chave descartável e static sem manifest.
TESTING = sys.argv[1:2] == ["test"]

# Valores de exemplo publicados no repositório nunca são aceitos fora do DEBUG.
PUBLIC_PLACEHOLDER_KEYS = {
    "change-me-generate-a-long-random-secret",
    "change-this-before-exposing-the-app",
    "development-only-secret-key",
}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()
if SECRET_KEY in PUBLIC_PLACEHOLDER_KEYS or len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5:
    if not (DEBUG or TESTING):
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY ausente, fraca ou igual ao exemplo do repositório. Gere uma com: "
            'python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
    SECRET_KEY = SECRET_KEY or "insecure-development-only-key-never-use-in-production-0123456789"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "fuelings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "fuelings.security.ContentSecurityPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Toda view exige login, exceto as marcadas com @login_not_required (login e health).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Deve ser o último: bloqueia tentativas de login após falhas repetidas.
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

database_path = Path(os.getenv("SQLITE_PATH", BASE_DIR / "data" / "db.sqlite3"))
database_path.parent.mkdir(parents=True, exist_ok=True)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": database_path,
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.getenv("APP_TIME_ZONE", "America/Cuiaba")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Em desenvolvimento e testes não exige o manifest gerado pelo collectstatic.
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG or TESTING
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Sessão: expira em 14 dias, cookie inacessível ao JavaScript.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# Atrás do Cloudflare Tunnel o TLS termina na borda da Cloudflare; o app recebe HTTP
# do cloudflared com X-Forwarded-Proto/CF-Connecting-IP. Só ative se a porta do app
# não estiver acessível diretamente (veja APP_BIND no compose.yaml).
APP_BEHIND_CLOUDFLARE = env_bool("APP_BEHIND_CLOUDFLARE", False)
if APP_BEHIND_CLOUDFLARE:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
    # O redirecionamento HTTP→HTTPS é feito pela Cloudflare ("Always Use HTTPS").
    SILENCED_SYSTEM_CHECKS = ["security.W008"]

# Proteção contra força bruta (django-axes): 5 falhas pelo mesmo IP bloqueiam por 1 hora.
# Bloquear por IP (e não por usuário) impede que um atacante tranque o dono da conta.
AXES_FAILURE_LIMIT = int(os.getenv("AXES_FAILURE_LIMIT", "5"))
AXES_COOLOFF_TIME = timedelta(minutes=int(os.getenv("AXES_COOLOFF_MINUTES", "60")))
AXES_LOCKOUT_PARAMETERS = ["ip_address"]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/locked.html"
AXES_CLIENT_IP_CALLABLE = "fuelings.security.client_ip"
