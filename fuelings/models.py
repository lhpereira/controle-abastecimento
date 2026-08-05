from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Vehicle(models.Model):
    name = models.CharField("Nome", max_length=100, default="Nissan Versa 2023")
    brand = models.CharField("Marca", max_length=60, default="Nissan")
    model = models.CharField("Modelo", max_length=60, default="Versa")
    year = models.PositiveSmallIntegerField("Ano", default=2023)
    tank_capacity_l = models.DecimalField(
        "Capacidade do tanque (L)", max_digits=6, decimal_places=3, default=Decimal("41")
    )
    official_city_limit = models.DecimalField(
        "Limite oficial — cidade", max_digits=7, decimal_places=6, default=Decimal("0.6857")
    )
    official_mixed_limit = models.DecimalField(
        "Limite oficial — misto", max_digits=7, decimal_places=6, default=Decimal("0.6913")
    )
    official_road_limit = models.DecimalField(
        "Limite oficial — estrada", max_digits=7, decimal_places=6, default=Decimal("0.6969")
    )
    neutral_band = models.DecimalField(
        "Faixa neutra", max_digits=5, decimal_places=4, default=Decimal("0.03")
    )
    optimizer_tolerance = models.DecimalField(
        "Tolerância do otimizador", max_digits=5, decimal_places=4, default=Decimal("0.05")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "veículo"
        verbose_name_plural = "veículos"

    def __str__(self):
        return self.name

    def official_limit_for(self, route):
        return {
            Fueling.Route.CITY: self.official_city_limit,
            Fueling.Route.MIXED: self.official_mixed_limit,
            Fueling.Route.ROAD: self.official_road_limit,
        }.get(route)


class Fueling(models.Model):
    class Route(models.TextChoices):
        CITY = "Cidade", "Cidade"
        MIXED = "Misto", "Misto"
        ROAD = "Estrada", "Estrada"

    class AirConditioning(models.TextChoices):
        ALWAYS = "Sempre", "Sempre"
        MOSTLY = "Maior Parte", "Maior parte"
        SOMETIMES = "Menor Parte", "Menor parte"
        NEVER = "Nunca", "Nunca"

    class GasolineType(models.TextChoices):
        COMMON = "Comum", "Comum"
        ADDITIVE = "Aditivada", "Aditivada"
        PREMIUM = "Premium", "Premium"
        PODIUM = "Podium", "Podium"
        OTHER = "Outra", "Outra"

    class Recommendation(models.TextChoices):
        ETHANOL = "Etanol", "Etanol"
        NEUTRAL = "Indiferente", "Indiferente"
        GASOLINE = "Gasolina", "Gasolina"

    class MixBand(models.TextChoices):
        INITIAL = "Base inicial", "Base inicial"
        ETHANOL = "Etanol dominante", "Etanol dominante"
        MIX = "Mistura", "Mistura"
        GASOLINE = "Gasolina dominante", "Gasolina dominante"

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="fuelings")
    date = models.DateField("Data")
    station = models.CharField("Bandeira/Posto", max_length=140)
    route = models.CharField("Tipo de trajeto", max_length=20, choices=Route.choices)
    air_conditioning = models.CharField(
        "Uso do ar-condicionado", max_length=20, choices=AirConditioning.choices
    )
    odometer_km = models.PositiveIntegerField("Hodômetro (km)")
    gasoline_type = models.CharField(
        "Tipo de gasolina", max_length=20, choices=GasolineType.choices, default=GasolineType.COMMON
    )
    gasoline_liters = models.DecimalField("Litros de gasolina", max_digits=7, decimal_places=3, default=0)
    gasoline_price = models.DecimalField("Preço da gasolina", max_digits=7, decimal_places=3)
    ethanol_liters = models.DecimalField("Litros de etanol", max_digits=7, decimal_places=3, default=0)
    ethanol_price = models.DecimalField("Preço do etanol", max_digits=7, decimal_places=3)
    anhydrous_rate = models.DecimalField(
        "Teor de etanol anidro na gasolina C", max_digits=5, decimal_places=4, default=Decimal("0.30")
    )
    full_tank = models.BooleanField("Tanque cheio", default=True)
    notes = models.TextField("Observações", blank=True)

    total_liters = models.DecimalField(max_digits=8, decimal_places=3, null=True, editable=False)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=6, null=True, editable=False)
    tank_cost_per_liter = models.DecimalField(max_digits=9, decimal_places=6, null=True, editable=False)
    gas_c_tank_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    distance_km = models.IntegerField(null=True, editable=False)
    efficiency_km_l = models.DecimalField(max_digits=9, decimal_places=6, null=True, editable=False)
    burned_gas_c_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    burned_price_per_liter = models.DecimalField(max_digits=9, decimal_places=6, null=True, editable=False)
    cost_per_km = models.DecimalField(max_digits=9, decimal_places=6, null=True, editable=False)
    price_ratio = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    days_since_previous = models.IntegerField(null=True, editable=False)
    gasoline_a_tank_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    ethanol_anhydrous_tank_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    ethanol_hydrated_tank_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    ethanol_total_tank_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    burned_ethanol_total_share = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    applicable_limit = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    recommendation = models.CharField(max_length=20, choices=Recommendation.choices, blank=True, editable=False)
    margin_to_limit = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    personal_limit = models.DecimalField(max_digits=9, decimal_places=8, null=True, editable=False)
    mix_band = models.CharField(max_length=24, choices=MixBand.choices, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["odometer_km", "date", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["vehicle", "odometer_km"], name="unique_vehicle_odometer")
        ]
        verbose_name = "abastecimento"
        verbose_name_plural = "abastecimentos"

    def __str__(self):
        return f"{self.date:%d/%m/%Y} — {self.station}"

    def clean(self):
        super().clean()
        total = (self.gasoline_liters or 0) + (self.ethanol_liters or 0)
        if total <= 0:
            raise ValidationError("Informe ao menos um volume de combustível.")
        if self.vehicle_id and total > self.vehicle.tank_capacity_l:
            raise ValidationError({"ethanol_liters": "O total supera a capacidade do tanque."})
        if not self.full_tank:
            raise ValidationError({"full_tank": "O modelo de cálculo atual requer tanque cheio."})
        if self.gasoline_price <= 0 or self.ethanol_price <= 0:
            raise ValidationError("Os dois preços da bomba devem ser maiores que zero.")
        if not Decimal("0") <= self.anhydrous_rate <= Decimal("1"):
            raise ValidationError({"anhydrous_rate": "Informe um percentual entre 0% e 100%."})
