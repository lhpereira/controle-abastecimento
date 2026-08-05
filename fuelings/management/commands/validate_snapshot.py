import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from fuelings.services import get_default_vehicle


FIELDS = {
    9: "total_liters",
    10: "amount_paid",
    11: "tank_cost_per_liter",
    12: "gas_c_tank_share",
    13: "distance_km",
    14: "efficiency_km_l",
    15: "burned_gas_c_share",
    16: "burned_price_per_liter",
    17: "cost_per_km",
    18: "price_ratio",
    19: "days_since_previous",
    21: "gasoline_a_tank_share",
    22: "ethanol_anhydrous_tank_share",
    23: "ethanol_hydrated_tank_share",
    24: "ethanol_total_tank_share",
    25: "burned_ethanol_total_share",
    26: "applicable_limit",
    27: "recommendation",
    28: "margin_to_limit",
    29: "personal_limit",
}


class Command(BaseCommand):
    help = "Compara os cálculos locais com um snapshot JSON exportado da planilha."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--tolerance", type=Decimal, default=Decimal("0.00002"))

    def handle(self, *args, **options):
        path = options["path"].resolve()
        if not path.exists():
            raise CommandError(f"Arquivo não encontrado: {path}")
        values = json.loads(path.read_text(encoding="utf-8"))["values"][1:]
        rows = {row.odometer_km: row for row in get_default_vehicle().fuelings.all()}
        failures = []
        checked = 0
        for source in values:
            row = rows.get(int(source[4]))
            if not row:
                failures.append(f"Hodômetro {source[4]} não encontrado")
                continue
            for index, field in FIELDS.items():
                expected = source[index] if index < len(source) else None
                actual = getattr(row, field)
                if expected in (None, ""):
                    if actual not in (None, ""):
                        failures.append(f"{row.odometer_km} {field}: esperado vazio, obtido {actual}")
                    continue
                checked += 1
                if field == "recommendation":
                    if str(actual) != str(expected):
                        failures.append(f"{row.odometer_km} {field}: {actual} != {expected}")
                    continue
                if actual is None:
                    if field == "personal_limit" and Decimal(str(expected)) == 0:
                        continue
                    failures.append(f"{row.odometer_km} {field}: vazio != {expected}")
                    continue
                if abs(Decimal(str(actual)) - Decimal(str(expected))) > options["tolerance"]:
                    failures.append(f"{row.odometer_km} {field}: {actual} != {expected}")
        if failures:
            raise CommandError("Validação falhou:\n" + "\n".join(failures[:30]))
        self.stdout.write(self.style.SUCCESS(f"Snapshot validado: {checked} valores conferidos."))
