from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import TestCase, override_settings

from .analytics import optimizer_model
from .models import Fueling, Vehicle
from .services import recalculate_all


class CalculationTests(TestCase):
    def setUp(self):
        self.vehicle = Vehicle.objects.create(name="Nissan Versa 2023")

    def create_row(self, **overrides):
        defaults = {
            "vehicle": self.vehicle,
            "date": date(2026, 3, 8),
            "station": "Posto teste",
            "route": Fueling.Route.CITY,
            "air_conditioning": Fueling.AirConditioning.ALWAYS,
            "odometer_km": 38180,
            "gasoline_liters": Decimal("38.015"),
            "gasoline_price": Decimal("6.39"),
            "ethanol_liters": Decimal("0"),
            "ethanol_price": Decimal("4.19"),
            "anhydrous_rate": Decimal("0.30"),
        }
        defaults.update(overrides)
        return Fueling.objects.create(**defaults)

    def test_reproduces_sequential_sheet_formulas(self):
        first = self.create_row()
        second = self.create_row(
            date=date(2026, 3, 13),
            odometer_km=38401,
            gasoline_liters=Decimal("29.55"),
            gasoline_price=Decimal("6.05"),
            ethanol_price=Decimal("4.17"),
        )
        recalculate_all(self.vehicle)
        first.refresh_from_db()
        second.refresh_from_db()

        self.assertEqual(first.total_liters, Decimal("38.015"))
        self.assertAlmostEqual(float(first.gas_c_tank_share), 1.0, places=7)
        self.assertEqual(second.distance_km, 221)
        self.assertAlmostEqual(float(second.efficiency_km_l), 221 / 29.55, places=5)
        self.assertAlmostEqual(float(second.burned_gas_c_share), 1.0, places=7)
        self.assertAlmostEqual(float(second.cost_per_km), 29.55 * 6.39 / 221, places=5)
        self.assertEqual(second.recommendation, Fueling.Recommendation.NEUTRAL)

    def test_health_endpoint(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @override_settings(APP_REQUIRE_LOGIN=True)
    def test_optional_login_protection(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/conta/login/?next=%2F", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/health/").status_code, 200)


class OptimizerTests(TestCase):
    def test_optimizer_requires_coverage_and_eight_cycles(self):
        rows = []
        for share, efficiency in [(0.0, 6.2), (0.1, 6.4), (0.2, 6.6), (0.4, 6.9), (0.6, 7.1), (0.8, 7.4), (0.9, 7.5), (1.0, 7.7)]:
            rows.append(
                SimpleNamespace(
                    route=Fueling.Route.CITY,
                    burned_gas_c_share=Decimal(str(share)),
                    efficiency_km_l=Decimal(str(efficiency)),
                )
            )
        result = optimizer_model(rows, Fueling.Route.CITY, Decimal("6.65"), Decimal("3.87"), Decimal("0.05"))
        self.assertTrue(result["ready"])
        self.assertIsNotNone(result["best"])
        self.assertIsNotNone(result["balanced"])
