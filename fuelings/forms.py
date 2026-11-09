from decimal import Decimal

from django import forms

from .models import Fueling, Vehicle


# Faixas de um ciclo plausível (tanque cheio a tanque cheio). Fora delas o valor
# provavelmente foi digitado errado; o usuário pode confirmar se estiver correto.
CYCLE_DISTANCE_KM = (1, 2000)
CYCLE_EFFICIENCY_KM_L = (Decimal("2"), Decimal("40"))


def _br(value, places=0):
    return f"{value:,.{places}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def cycle_issues(label, start_km, end_km, liters):
    """Problemas de plausibilidade de um ciclo: distância percorrida e consumo resultante."""
    issues = []
    distance = end_km - start_km
    low, high = CYCLE_DISTANCE_KM
    if not low <= distance <= high:
        issues.append(f"{label}: {_br(distance)} km rodados (o esperado é entre {low} e {_br(high)} km).")
    if liters and liters > 0:
        efficiency = Decimal(distance) / liters
        low, high = CYCLE_EFFICIENCY_KM_L
        if not low <= efficiency <= high:
            issues.append(f"{label}: consumo de {_br(efficiency, 1)} km/L (o esperado é entre {low} e {high} km/L).")
    return issues


class FuelingForm(forms.ModelForm):
    confirm_unusual = forms.BooleanField(
        label="Confirmo que os valores estão corretos, mesmo fora do comum",
        required=False,
    )
    anhydrous_percent = forms.DecimalField(
        label="Etanol anidro na gasolina C (%)",
        min_value=0,
        max_value=100,
        max_digits=6,
        decimal_places=2,
        help_text="Informe o teor efetivo da gasolina comprada. Ex.: 30 para 30%.",
    )

    class Meta:
        model = Fueling
        fields = [
            "date",
            "station",
            "route",
            "air_conditioning",
            "odometer_km",
            "gasoline_type",
            "gasoline_liters",
            "gasoline_price",
            "ethanol_liters",
            "ethanol_price",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "gasoline_liters": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "gasoline_price": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "ethanol_liters": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "ethanol_price": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, vehicle=None, **kwargs):
        self.vehicle = vehicle
        self.needs_confirmation = False
        super().__init__(*args, **kwargs)
        self.order_fields([name for name in self.fields if name != "confirm_unusual"] + ["confirm_unusual"])
        rate = self.instance.anhydrous_rate if self.instance and self.instance.pk else Decimal("0.30")
        self.fields["anhydrous_percent"].initial = rate * 100

    def clean(self):
        cleaned = super().clean()
        if self.vehicle:
            total = (cleaned.get("gasoline_liters") or 0) + (cleaned.get("ethanol_liters") or 0)
            if total > self.vehicle.tank_capacity_l:
                raise forms.ValidationError(
                    f"O total informado supera o tanque de {self.vehicle.tank_capacity_l} L."
                )
            self._check_cycle_plausibility(cleaned, total)
        return cleaned

    def _check_cycle_plausibility(self, cleaned, total):
        odometer = cleaned.get("odometer_km")
        if odometer is None:
            return
        # .only(): lê só colunas de entrada, que continuam legíveis mesmo se algum valor
        # derivado estiver corrompido no banco.
        others = Fueling.objects.filter(vehicle=self.vehicle).only(
            "odometer_km", "date", "gasoline_liters", "ethanol_liters"
        )
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        previous = others.filter(odometer_km__lt=odometer).order_by("-odometer_km").first()
        following = others.filter(odometer_km__gt=odometer).order_by("odometer_km").first()

        issues = []
        if previous:
            label = f"Desde o abastecimento de {previous.date:%d/%m/%Y} ({_br(previous.odometer_km)} km)"
            issues += cycle_issues(label, previous.odometer_km, odometer, total)
        if following:
            label = f"Até o abastecimento seguinte, de {following.date:%d/%m/%Y} ({_br(following.odometer_km)} km)"
            issues += cycle_issues(
                label, odometer, following.odometer_km, following.gasoline_liters + following.ethanol_liters
            )
        if not issues:
            return
        self.needs_confirmation = True
        if not cleaned.get("confirm_unusual"):
            raise forms.ValidationError(
                ["Os valores parecem fora do comum. Confira o hodômetro e os litros:"]
                + issues
                + ["Se estiverem corretos, marque a confirmação no fim do formulário e salve de novo."]
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.vehicle = self.vehicle or instance.vehicle
        instance.anhydrous_rate = self.cleaned_data["anhydrous_percent"] / 100
        instance.full_tank = True
        if commit:
            instance.full_clean()
            instance.save()
        return instance


class VehicleForm(forms.ModelForm):
    neutral_band_percent = forms.DecimalField(
        label="Faixa neutra (pontos percentuais)", min_value=0, max_value=20, decimal_places=2
    )
    optimizer_tolerance_percent = forms.DecimalField(
        label="Tolerância do otimizador (%)", min_value=0, max_value=50, decimal_places=2
    )

    class Meta:
        model = Vehicle
        fields = [
            "name",
            "brand",
            "model",
            "year",
            "tank_capacity_l",
            "official_city_limit",
            "official_mixed_limit",
            "official_road_limit",
        ]
        help_texts = {
            "official_city_limit": "Use decimal: 0,6857 equivale a 68,57%.",
            "official_mixed_limit": "Use decimal: 0,6913 equivale a 69,13%.",
            "official_road_limit": "Use decimal: 0,6969 equivale a 69,69%.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["neutral_band_percent"].initial = self.instance.neutral_band * 100
            self.fields["optimizer_tolerance_percent"].initial = self.instance.optimizer_tolerance * 100

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.neutral_band = self.cleaned_data["neutral_band_percent"] / 100
        instance.optimizer_tolerance = self.cleaned_data["optimizer_tolerance_percent"] / 100
        if commit:
            instance.save()
        return instance


class OptimizerForm(forms.Form):
    route = forms.ChoiceField(label="Trajeto", choices=Fueling.Route.choices)
    gasoline_price = forms.DecimalField(
        label="Preço da gasolina", min_value=Decimal("0.001"), max_digits=7, decimal_places=3
    )
    ethanol_price = forms.DecimalField(
        label="Preço do etanol", min_value=Decimal("0.001"), max_digits=7, decimal_places=3
    )

