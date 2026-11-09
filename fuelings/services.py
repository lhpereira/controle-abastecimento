from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction

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


FIELD_LABELS = {
    "total_liters": "total de litros",
    "amount_paid": "valor pago",
    "tank_cost_per_liter": "custo médio do tanque",
    "gas_c_tank_share": "participação de gasolina C no tanque",
    "efficiency_km_l": "consumo (km/L)",
    "burned_gas_c_share": "gasolina C consumida",
    "burned_price_per_liter": "preço do litro consumido",
    "cost_per_km": "custo por km",
    "price_ratio": "relação etanol/gasolina",
    "gasoline_a_tank_share": "participação de gasolina A",
    "ethanol_anhydrous_tank_share": "participação de etanol anidro",
    "ethanol_hydrated_tank_share": "participação de etanol hidratado",
    "ethanol_total_tank_share": "participação total de etanol",
    "burned_ethanol_total_share": "etanol consumido",
    "applicable_limit": "limite aplicável",
    "margin_to_limit": "margem até o limite",
    "personal_limit": "limite pessoal",
}


class DerivedValueOutOfRange(ValidationError):
    """Um valor calculado não cabe na coluna do banco.

    O SQLite grava o valor mesmo assim, mas o Django falha ao lê-lo de volta, o que
    derrubaria todas as telas (DAD-01). O recálculo é desfeito e o erro chega ao usuário.
    """

    def __init__(self, row, field_name, value):
        self.row_id = row.pk
        self.odometer_km = row.odometer_km
        self.field_name = field_name
        odometer = f"{row.odometer_km:,}".replace(",", ".")
        super().__init__(
            f"O abastecimento de {row.date:%d/%m/%Y} (hodômetro {odometer} km) resultaria em "
            f"{FIELD_LABELS.get(field_name, field_name)} = {value:.2f}, valor fora da faixa que o "
            "sistema consegue armazenar. Confira o hodômetro, os litros e os preços.",
            code="derived_out_of_range",
        )


def _decimal_limit(field: models.DecimalField) -> Decimal:
    return Decimal(10) ** (field.max_digits - field.decimal_places)


DECIMAL_DERIVED_FIELDS = {
    name: Fueling._meta.get_field(name)
    for name in DERIVED_FIELDS
    if isinstance(Fueling._meta.get_field(name), models.DecimalField)
}


def ensure_storable(row, field_names=DECIMAL_DERIVED_FIELDS) -> None:
    """Garante que cada valor derivado cabe na coluna após o arredondamento do banco.

    Não altera os valores em memória, para não mudar a precisão usada no ciclo seguinte.
    """
    for name in field_names:
        value = getattr(row, name)
        if value is None:
            continue
        field = DECIMAL_DERIVED_FIELDS[name]
        limit = _decimal_limit(field)
        # Compara antes de arredondar: quantize() falharia com números enormes.
        if abs(value) >= limit or abs(value.quantize(Decimal(1).scaleb(-field.decimal_places))) >= limit:
            raise DerivedValueOutOfRange(row, name, value)


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
        ensure_storable(row)
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
        ensure_storable(row, ["personal_limit"])
        row.save(update_fields=["personal_limit", "updated_at"])
