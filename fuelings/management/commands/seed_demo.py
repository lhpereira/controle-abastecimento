import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuelings.models import Fueling
from fuelings.services import get_default_vehicle, recalculate_all


class Command(BaseCommand):
    help = "Gera abastecimentos fictícios para desenvolvimento. Não use com dados reais."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=26)
        parser.add_argument("--replace", action="store_true", help="Remove os registros atuais antes de gerar.")

    @transaction.atomic
    def handle(self, *args, **options):
        vehicle = get_default_vehicle()
        if vehicle.fuelings.exists():
            if not options["replace"]:
                raise CommandError("Já existem registros. Use --replace para substituí-los (apaga os dados atuais).")
            vehicle.fuelings.all().delete()

        rng = random.Random(7)
        day, odometer, gasoline, ethanol = date(2025, 9, 1), 30000, 6.20, 4.10
        for index in range(options["count"]):
            gasoline += rng.uniform(-0.12, 0.15)
            ethanol += rng.uniform(-0.10, 0.12)
            odometer += rng.randint(260, 520)
            day += timedelta(days=rng.randint(6, 16))
            gas_liters, eth_liters = {"e": (0, 38), "g": (38, 0), "m": (19, 19)}[rng.choice("eegm")]
            Fueling.objects.create(
                vehicle=vehicle,
                date=day,
                station=f"Posto demo {index % 4 + 1}",
                route=rng.choice([Fueling.Route.CITY] * 3 + [Fueling.Route.MIXED, Fueling.Route.ROAD]),
                air_conditioning=Fueling.AirConditioning.ALWAYS,
                odometer_km=odometer,
                gasoline_liters=Decimal(gas_liters) + Decimal(rng.randint(0, 30)) / 10 if gas_liters else Decimal(0),
                gasoline_price=Decimal(str(round(gasoline, 3))),
                ethanol_liters=Decimal(eth_liters),
                ethanol_price=Decimal(str(round(ethanol, 3))),
            )
        recalculate_all(vehicle)
        self.stdout.write(self.style.SUCCESS(f"{options['count']} abastecimentos fictícios criados."))
