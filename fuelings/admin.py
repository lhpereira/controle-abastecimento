from django.contrib import admin

from .models import Fueling, Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("name", "tank_capacity_l", "year", "updated_at")


@admin.register(Fueling)
class FuelingAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "station",
        "route",
        "odometer_km",
        "total_liters",
        "efficiency_km_l",
        "cost_per_km",
        "recommendation",
    )
    list_filter = ("route", "air_conditioning", "recommendation", "gasoline_type")
    search_fields = ("station", "notes")
    readonly_fields = [field.name for field in Fueling._meta.fields if not field.editable]
