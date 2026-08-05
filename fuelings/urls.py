from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("abastecimentos/", views.fueling_list, name="fueling_list"),
    path("abastecimentos/novo/", views.fueling_form, name="fueling_create"),
    path("abastecimentos/<int:pk>/", views.fueling_detail, name="fueling_detail"),
    path("abastecimentos/<int:pk>/editar/", views.fueling_form, name="fueling_update"),
    path("abastecimentos/<int:pk>/excluir/", views.fueling_delete, name="fueling_delete"),
    path("configuracoes/", views.vehicle_settings, name="vehicle_settings"),
    path("otimizador/", views.optimizer, name="optimizer"),
    path("exportar/csv/", views.export_csv, name="export_csv"),
    path("backup/", views.download_backup, name="download_backup"),
    path("health/", views.health, name="health"),
]

