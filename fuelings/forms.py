from decimal import Decimal

from django import forms

from .models import Fueling, Vehicle


class FuelingForm(forms.ModelForm):
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
        super().__init__(*args, **kwargs)
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
        return cleaned

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

