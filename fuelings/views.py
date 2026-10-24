import csv
from datetime import date

from django.contrib import messages
from django.db import connection, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .analytics import dashboard_context, optimizer_model
from .forms import FuelingForm, OptimizerForm, VehicleForm
from .models import Fueling
from .services import get_default_vehicle, recalculate_all


def dashboard(request):
    return render(request, "fuelings/dashboard.html", dashboard_context(get_default_vehicle(), request.GET))


def fueling_list(request):
    vehicle = get_default_vehicle()
    rows = vehicle.fuelings.all().order_by("-odometer_km")
    route = request.GET.get("route")
    band = request.GET.get("band")
    if route:
        rows = rows.filter(route=route)
    if band:
        rows = rows.filter(mix_band=band)
    return render(request, "fuelings/fueling_list.html", {"rows": rows, "vehicle": vehicle})


def fueling_detail(request, pk):
    row = get_object_or_404(Fueling, pk=pk)
    return render(request, "fuelings/fueling_detail.html", {"row": row})


def fueling_form(request, pk=None):
    vehicle = get_default_vehicle()
    instance = get_object_or_404(Fueling, pk=pk, vehicle=vehicle) if pk else None
    form = FuelingForm(request.POST or None, instance=instance, vehicle=vehicle)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            row = form.save()
            recalculate_all(vehicle)
        messages.success(request, "Abastecimento salvo e sequência recalculada.")
        return redirect("fueling_detail", pk=row.pk)
    return render(
        request,
        "fuelings/fueling_form.html",
        {"form": form, "instance": instance, "vehicle": vehicle},
    )


def fueling_delete(request, pk):
    vehicle = get_default_vehicle()
    row = get_object_or_404(Fueling, pk=pk, vehicle=vehicle)
    if request.method == "POST":
        with transaction.atomic():
            row.delete()
            recalculate_all(vehicle)
        messages.success(request, "Abastecimento removido e sequência recalculada.")
        return redirect("fueling_list")
    return render(request, "fuelings/fueling_confirm_delete.html", {"row": row})


def vehicle_settings(request):
    vehicle = get_default_vehicle()
    form = VehicleForm(request.POST or None, instance=vehicle)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            vehicle = form.save()
            recalculate_all(vehicle)
        messages.success(request, "Configurações atualizadas e histórico recalculado.")
        return redirect("vehicle_settings")
    return render(request, "fuelings/vehicle_settings.html", {"form": form, "vehicle": vehicle})


def optimizer(request):
    vehicle = get_default_vehicle()
    rows = list(vehicle.fuelings.all())
    latest = rows[-1] if rows else None
    initial = {
        "route": Fueling.Route.CITY,
        "gasoline_price": latest.gasoline_price if latest else None,
        "ethanol_price": latest.ethanol_price if latest else None,
    }
    form = OptimizerForm(request.POST or None, initial=initial)
    result = None
    if form.is_valid():
        result = optimizer_model(
            rows,
            form.cleaned_data["route"],
            form.cleaned_data["gasoline_price"],
            form.cleaned_data["ethanol_price"],
            vehicle.optimizer_tolerance,
        )
    return render(
        request,
        "fuelings/optimizer.html",
        {"form": form, "result": result, "vehicle": vehicle},
    )


def export_csv(request):
    vehicle = get_default_vehicle()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="abastecimentos-{date.today():%Y-%m-%d}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(
        [
            "Data", "Posto", "Trajeto", "Uso A/C", "Hodômetro", "Litros gasolina",
            "Preço gasolina", "Litros etanol", "Preço etanol", "Teor anidro", "km rodados",
            "km/L", "% gasolina C consumida", "Custo/km", "Recomendação",
        ]
    )
    for row in vehicle.fuelings.all():
        writer.writerow(
            [
                row.date.strftime("%d/%m/%Y"), row.station, row.route, row.air_conditioning,
                row.odometer_km, row.gasoline_liters, row.gasoline_price, row.ethanol_liters,
                row.ethanol_price, row.anhydrous_rate, row.distance_km, row.efficiency_km_l,
                row.burned_gas_c_share, row.cost_per_km, row.recommendation,
            ]
        )
    return response


def download_backup(request):
    connection.ensure_connection()
    raw_connection = connection.connection
    if not hasattr(raw_connection, "serialize"):
        return HttpResponse("Backup online não suportado por esta versão do SQLite.", status=501)
    payload = raw_connection.serialize()
    response = HttpResponse(payload, content_type="application/x-sqlite3")
    response["Content-Disposition"] = f'attachment; filename="controle-abastecimento-{date.today():%Y-%m-%d}.sqlite3"'
    return response


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"status": "ok"})

