import csv
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuelings.models import Fueling
from fuelings.services import DerivedValueOutOfRange, get_default_vehicle, recalculate_all


def excel_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    text = str(value).strip()
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise CommandError(f"Data inválida: {value}")


def decimal_value(value, default="0"):
    if value in (None, ""):
        return Decimal(default)
    return Decimal(str(value).replace("R$", "").replace(" ", "").replace(",", "."))


def rows_from_json(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("values", payload)
    return values[1:] if values and isinstance(values[0], list) else values


def rows_from_xlsx(path):
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=True, read_only=True)
    if "Abastecimentos" not in workbook.sheetnames:
        raise CommandError("A aba 'Abastecimentos' não foi encontrada.")
    return list(workbook["Abastecimentos"].iter_rows(min_row=2, values_only=True))


def rows_from_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = []
        for item in csv.DictReader(source, delimiter=";"):
            values = [None] * 30
            values[0] = item.get("Data")
            values[1] = item.get("Posto") or item.get("Bandeira/Posto")
            values[2] = item.get("Trajeto") or item.get("Tipo Trajeto")
            values[3] = item.get("Uso A/C")
            values[4] = item.get("Hodômetro") or item.get("KM Hodômetro")
            values[5] = item.get("Litros gasolina") or item.get("Litros Gasolina")
            values[6] = item.get("Preço gasolina") or item.get("Preço Gasolina")
            values[7] = item.get("Litros etanol") or item.get("Litros Etanol")
            values[8] = item.get("Preço etanol") or item.get("Preço Etanol")
            values[20] = item.get("Teor anidro") or item.get("Teor de etanol anidro na gasolina C comprada")
            rows.append(values)
        return rows


class Command(BaseCommand):
    help = "Importa abastecimentos de JSON, XLSX ou CSV e recalcula toda a sequência."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--replace", action="store_true", help="Remove registros atuais antes de importar.")

    @transaction.atomic
    def handle(self, *args, **options):
        path = options["path"].resolve()
        if not path.exists():
            raise CommandError(f"Arquivo não encontrado: {path}")
        readers = {".json": rows_from_json, ".xlsx": rows_from_xlsx, ".csv": rows_from_csv}
        if path.suffix.lower() not in readers:
            raise CommandError("Formato não suportado. Use .json, .xlsx ou .csv.")

        rows = readers[path.suffix.lower()](path)
        vehicle = get_default_vehicle()
        if options["replace"]:
            vehicle.fuelings.all().delete()

        imported = 0
        for values in rows:
            values = list(values) + [None] * 30
            if values[0] in (None, "") or values[4] in (None, ""):
                continue
            defaults = {
                "date": excel_date(values[0]),
                "station": str(values[1] or "Não informado").strip(),
                "route": str(values[2] or Fueling.Route.CITY).strip(),
                "air_conditioning": str(values[3] or Fueling.AirConditioning.ALWAYS).strip(),
                "gasoline_liters": decimal_value(values[5]),
                "gasoline_price": decimal_value(values[6]),
                "ethanol_liters": decimal_value(values[7]),
                "ethanol_price": decimal_value(values[8]),
                "anhydrous_rate": decimal_value(values[20], "0.30"),
                "gasoline_type": Fueling.GasolineType.COMMON,
                "full_tank": True,
            }
            Fueling.objects.update_or_create(
                vehicle=vehicle,
                odometer_km=int(values[4]),
                defaults=defaults,
            )
            imported += 1

        try:
            recalculate_all(vehicle)
        except DerivedValueOutOfRange as error:
            # A importação inteira é desfeita (handle é atômico): o banco fica como estava.
            raise CommandError(f"Importação cancelada. {error.message}") from error
        self.stdout.write(self.style.SUCCESS(f"{imported} abastecimentos importados e recalculados."))
