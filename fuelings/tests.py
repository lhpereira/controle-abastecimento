from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.http import QueryDict
from django.test import TestCase, override_settings

from .analytics import dashboard_context, linear_fit, optimizer_model, parse_filters
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


STATIC_TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STATIC_TEST_STORAGES)
class DashboardFilterTests(TestCase):
    def setUp(self):
        self.vehicle = Vehicle.objects.create(name="Nissan Versa 2023")
        odometer = 10000
        # Alterna etanol/gasolina e trajetos para que existam ciclos em todas as faixas.
        plan = [
            (date(2026, 1, 5), Fueling.Route.CITY, "38", "0"),
            (date(2026, 2, 5), Fueling.Route.CITY, "0", "38"),
            (date(2026, 3, 5), Fueling.Route.CITY, "0", "38"),
            (date(2026, 4, 5), Fueling.Route.ROAD, "38", "0"),
            (date(2026, 5, 5), Fueling.Route.ROAD, "38", "0"),
            (date(2026, 6, 5), Fueling.Route.CITY, "20", "18"),
            (date(2026, 7, 5), Fueling.Route.MIXED, "38", "0"),
        ]
        for index, (day, route, gasoline, ethanol) in enumerate(plan):
            odometer += 300 + index * 10
            Fueling.objects.create(
                vehicle=self.vehicle,
                date=day,
                station="Posto teste",
                route=route,
                air_conditioning=Fueling.AirConditioning.ALWAYS,
                odometer_km=odometer,
                gasoline_liters=Decimal(gasoline),
                gasoline_price=Decimal("6.40"),
                ethanol_liters=Decimal(ethanol),
                ethanol_price=Decimal("4.30"),
            )
        recalculate_all(self.vehicle)

    def context(self, query=""):
        return dashboard_context(self.vehicle, QueryDict(query))

    def test_invalid_filters_fall_back_to_defaults(self):
        filters = parse_filters(QueryDict("periodo=xyz&trajeto=Voo&faixa=nada"))
        self.assertEqual(filters, {"period": "all", "routes": [], "band": ""})

    def test_route_filter_restricts_rows_and_keeps_latest_decision(self):
        context = self.context("trajeto=Estrada")
        self.assertTrue(context["filtered"])
        self.assertTrue(all(row.route == Fueling.Route.ROAD for row in context["filtered_rows"]))
        self.assertEqual(context["latest"].route, Fueling.Route.MIXED)
        self.assertEqual({item["route"] for item in context["chart_data"]["matrix"]}, {"Cidade", "Misto", "Estrada"})

    def test_period_filter_is_relative_to_latest_fueling(self):
        context = self.context("periodo=3")
        dates = [row.date for row in context["filtered_rows"]]
        self.assertTrue(dates)
        self.assertGreaterEqual(min(dates), date(2026, 4, 5))
        self.assertLess(len(dates), context["total_count"])

    def test_band_filter_only_keeps_matching_cycles(self):
        context = self.context("faixa=Etanol dominante")
        self.assertTrue(all(row.mix_band == Fueling.MixBand.ETHANOL for row in context["filtered_rows"]))

    def test_dashboard_renders_with_and_without_filters(self):
        for query in ["", "?trajeto=Cidade&trajeto=Estrada&periodo=6", "?faixa=Gasolina dominante", "?trajeto=Misto&faixa=Etanol dominante"]:
            response = self.client.get("/" + query)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "dashboardFilters")

    def test_empty_filter_result_shows_message(self):
        response = self.client.get("/?trajeto=Misto&faixa=Etanol dominante")
        self.assertContains(response, "Nenhum ciclo com esses filtros")

    def test_linear_fit_needs_three_points(self):
        self.assertIsNone(linear_fit([(0, 1), (1, 2)]))
        fit = linear_fit([(0, 1), (1, 3), (2, 5)])
        self.assertAlmostEqual(fit["slope"], 2)
        self.assertAlmostEqual(fit["r2"], 1)
