from collections import defaultdict
from decimal import Decimal

from django.db import transaction

from .models import Fueling, Vehicle


ZERO = Decimal("0")
ONE = Decimal("1")

DERIVED_FIELDS = [
    "total_liters",
    "amount_paid",
    "tank_cost_per_liter",
    "gas_c_tank_share",
    "distance_km",
    "efficiency_km_l",
    "burned_gas_c_share",
    "burned_price_per_liter",
    "cost_per_km",
    "price_ratio",
    "days_since_previous",
    "gasoline_a_tank_share",
    "ethanol_anhydrous_tank_share",
    "ethanol_hydrated_tank_share",
    "ethanol_total_tank_share",
    "burned_ethanol_total_share",
    "applicable_limit",
    "recommendation",
    "margin_to_limit",
    "personal_limit",
    "mix_band",
]


def get_default_vehicle() -> Vehicle:
    vehicle = Vehicle.objects.order_by("pk").first()
    if vehicle:
        return vehicle
    return Vehicle.objects.create(
        name="Nissan Versa 2023",
        brand="Nissan",
        model="Versa",
        year=2023,
        tank_capacity_l=Decimal("41"),
    )


def _recommendation(ratio: Decimal, limit: Decimal, neutral_band: Decimal) -> str:
    if ratio < limit - neutral_band:
        return Fueling.Recommendation.ETHANOL
    if ratio > limit + neutral_band:
        return Fueling.Recommendation.GASOLINE
    return Fueling.Recommendation.NEUTRAL


@transaction.atomic
def recalculate_all(vehicle: Vehicle) -> None:
    rows = list(
        Fueling.objects.select_for_update()
        .filter(vehicle=vehicle)
        .order_by("odometer_km", "date", "pk")
    )
    capacity = vehicle.tank_capacity_l
    previous = None

    for row in rows:
        total = row.gasoline_liters + row.ethanol_liters
        paid = row.gasoline_liters * row.gasoline_price + row.ethanol_liters * row.ethanol_price
        residual = capacity - total

        row.total_liters = total
        row.amount_paid = paid
        row.price_ratio = row.ethanol_price / row.gasoline_price
        row.applicable_limit = vehicle.official_limit_for(row.route)
        row.margin_to_limit = row.applicable_limit - row.price_ratio
        row.recommendation = _recommendation(row.price_ratio, row.applicable_limit, vehicle.neutral_band)

        if previous is None:
            # Mantém o mesmo marco inicial adotado na planilha validada.
            row.tank_cost_per_liter = paid / total
            row.gas_c_tank_share = row.gasoline_liters / total
            row.distance_km = None
            row.efficiency_km_l = None
            row.burned_gas_c_share = None
            row.burned_price_per_liter = None
            row.cost_per_km = None
            row.days_since_previous = None
            row.gasoline_a_tank_share = row.gasoline_liters * (ONE - row.anhydrous_rate) / capacity
            row.ethanol_anhydrous_tank_share = row.gasoline_liters * row.anhydrous_rate / capacity
            row.ethanol_hydrated_tank_share = (row.ethanol_liters + residual) / capacity
            row.burned_ethanol_total_share = None
            row.mix_band = Fueling.MixBand.INITIAL
        else:
            row.tank_cost_per_liter = (residual * previous.tank_cost_per_liter + paid) / capacity
            row.gas_c_tank_share = (residual * previous.gas_c_tank_share + row.gasoline_liters) / capacity
            row.distance_km = row.odometer_km - previous.odometer_km
            row.efficiency_km_l = Decimal(row.distance_km) / total if row.distance_km > 0 else None
            row.burned_gas_c_share = previous.gas_c_tank_share
            row.burned_price_per_liter = previous.tank_cost_per_liter
            row.cost_per_km = (
                total * row.burned_price_per_liter / Decimal(row.distance_km)
                if row.distance_km > 0
                else None
            )
            row.days_since_previous = (row.date - previous.date).days
            row.gasoline_a_tank_share = (
                residual * previous.gasoline_a_tank_share
                + row.gasoline_liters * (ONE - row.anhydrous_rate)
            ) / capacity
            row.ethanol_anhydrous_tank_share = (
                residual * previous.ethanol_anhydrous_tank_share
                + row.gasoline_liters * row.anhydrous_rate
            ) / capacity
            row.ethanol_hydrated_tank_share = (
                residual * previous.ethanol_hydrated_tank_share + row.ethanol_liters
            ) / capacity
            row.burned_ethanol_total_share = previous.ethanol_total_tank_share
            if row.burned_gas_c_share <= Decimal("0.20"):
                row.mix_band = Fueling.MixBand.ETHANOL
            elif row.burned_gas_c_share >= Decimal("0.80"):
                row.mix_band = Fueling.MixBand.GASOLINE
            else:
                row.mix_band = Fueling.MixBand.MIX

        row.ethanol_total_tank_share = (
            row.ethanol_anhydrous_tank_share + row.ethanol_hydrated_tank_share
        )
        row.personal_limit = None
        row.save(update_fields=DERIVED_FIELDS + ["updated_at"])
        previous = row

    aggregates = defaultdict(lambda: {"eth_km": 0, "eth_l": ZERO, "gas_km": 0, "gas_l": ZERO})
    for row in rows:
        if row.distance_km is None or row.burned_gas_c_share is None:
            continue
        target = aggregates[row.route]
        if row.burned_gas_c_share <= Decimal("0.20"):
            target["eth_km"] += row.distance_km
            target["eth_l"] += row.total_liters
        elif row.burned_gas_c_share >= Decimal("0.80"):
            target["gas_km"] += row.distance_km
            target["gas_l"] += row.total_liters

    personal = {}
    for route, values in aggregates.items():
        if values["eth_l"] and values["gas_l"]:
            eth_kml = Decimal(values["eth_km"]) / values["eth_l"]
            gas_kml = Decimal(values["gas_km"]) / values["gas_l"]
            personal[route] = eth_kml / gas_kml

    for row in rows:
        row.personal_limit = personal.get(row.route)
        row.save(update_fields=["personal_limit", "updated_at"])
