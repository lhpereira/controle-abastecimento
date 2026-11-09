from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    # Apenas login e logout: não há e-mail configurado para redefinição de senha.
    path("conta/login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("conta/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("fuelings.urls")),
]
