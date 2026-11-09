import csv
import os
import sqlite3
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import User
from django.http import QueryDict
from django.test import RequestFactory, TestCase, override_settings

from .analytics import dashboard_context, linear_fit, optimizer_model, parse_filters
from .models import Fueling, Vehicle
from .security import client_ip, csv_safe
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
        self.client.force_login(User.objects.create_user("dono"))

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

def make_row(vehicle, **overrides):
    values = {
        "vehicle": vehicle,
        "date": date(2026, 3, 8),
        "station": "Posto teste",
        "route": Fueling.Route.CITY,
        "air_conditioning": Fueling.AirConditioning.ALWAYS,
        "odometer_km": 38180,
        "gasoline_liters": Decimal("38"),
        "gasoline_price": Decimal("6.39"),
        "ethanol_liters": Decimal("0"),
        "ethanol_price": Decimal("4.19"),
    }
    values.update(overrides)
    return Fueling.objects.create(**values)


class AuthenticationTests(TestCase):
    """SEG-01 / SEG-05 / SEG-09."""

    def setUp(self):
        self.user = User.objects.create_user("dono", password="senha-de-teste-longa")

    def test_every_page_requires_login(self):
        for url in ["/", "/abastecimentos/", "/abastecimentos/novo/", "/configuracoes/",
                    "/otimizador/", "/exportar/csv/", "/backup/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/conta/login/"))

    def test_public_endpoints(self):
        self.assertEqual(self.client.get("/health/").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/conta/login/").status_code, 200)
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)

    def test_password_reset_routes_are_not_exposed(self):
        self.client.force_login(self.user)
        for url in ["/conta/password_reset/", "/conta/password_change/", "/conta/reset/done/"]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_logout_button_ends_session(self):
        self.client.force_login(self.user)
        page = self.client.get("/abastecimentos/")
        self.assertContains(page, 'action="/conta/logout/"')
        self.client.post("/conta/logout/")
        self.assertEqual(self.client.get("/abastecimentos/").status_code, 302)

    def test_login_page_has_no_navigation_for_anonymous(self):
        self.assertNotContains(self.client.get("/conta/login/"), "/conta/logout/")

    def test_brute_force_lockout(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.client.post("/conta/login/", {"username": "dono", "password": "errada"})
        response = self.client.post("/conta/login/", {"username": "dono", "password": "senha-de-teste-longa"})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "temporariamente bloqueado", status_code=429)

    def test_successful_login(self):
        response = self.client.post("/conta/login/", {"username": "dono", "password": "senha-de-teste-longa"})
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class ClientIpTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, remote, cf_ip):
        return self.factory.get("/", REMOTE_ADDR=remote, HTTP_CF_CONNECTING_IP=cf_ip)

    @override_settings(APP_BEHIND_CLOUDFLARE=True)
    def test_uses_cloudflare_header_from_tunnel(self):
        self.assertEqual(client_ip(self.request("172.18.0.1", "203.0.113.7")), "203.0.113.7")

    @override_settings(APP_BEHIND_CLOUDFLARE=True)
    def test_ignores_header_from_external_address(self):
        self.assertEqual(client_ip(self.request("8.8.8.8", "203.0.113.7")), "8.8.8.8")

    @override_settings(APP_BEHIND_CLOUDFLARE=False)
    def test_ignores_header_when_not_behind_cloudflare(self):
        self.assertEqual(client_ip(self.request("127.0.0.1", "203.0.113.7")), "127.0.0.1")


class BackupTests(TestCase):
    """SEG-02."""

    def setUp(self):
        self.vehicle = Vehicle.objects.create(name="Carro")
        make_row(self.vehicle)
        self.admin = User.objects.create_superuser("admin", password="senha-de-teste-longa")
        self.common = User.objects.create_user("comum", password="senha-de-teste-longa")

    def test_common_user_is_forbidden(self):
        self.client.force_login(self.common)
        self.assertEqual(self.client.get("/backup/").status_code, 403)

    def test_superuser_backup_has_data_but_no_sessions(self):
        self.client.force_login(self.admin)
        response = self.client.get("/backup/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        backup = sqlite3.connect(":memory:")
        backup.deserialize(response.content)
        self.assertEqual(backup.execute("SELECT COUNT(*) FROM fuelings_fueling").fetchone()[0], 1)
        self.assertEqual(backup.execute("SELECT COUNT(*) FROM django_session").fetchone()[0], 0)
        self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertNotIn(self.client.session.session_key.encode(), response.content)

    def test_backup_button_only_for_superuser(self):
        self.client.force_login(self.common)
        self.assertNotContains(self.client.get("/configuracoes/"), "/backup/")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/configuracoes/"), "/backup/")


class CsvExportTests(TestCase):
    """SEG-07."""

    def test_csv_safe(self):
        self.assertEqual(csv_safe('=HYPERLINK("x")'), "'=HYPERLINK(\"x\")")
        for prefix in "+-@\t\r":
            self.assertTrue(csv_safe(prefix + "1").startswith("'"))
        self.assertEqual(csv_safe("Posto Shell"), "Posto Shell")
        self.assertEqual(csv_safe(Decimal("-1.5")), Decimal("-1.5"))

    def test_export_neutralizes_formulas(self):
        vehicle = Vehicle.objects.create(name="Carro")
        make_row(vehicle, station='=HYPERLINK("http://x";"clique")')
        recalculate_all(vehicle)
        self.client.force_login(User.objects.create_user("dono"))
        content = self.client.get("/exportar/csv/").content.decode("utf-8-sig")
        row = list(csv.reader(content.splitlines(), delimiter=";"))[1]
        self.assertEqual(row[1], "'=HYPERLINK(\"http://x\";\"clique\")")


class ContentSecurityPolicyTests(TestCase):
    """SEG-06."""

    def setUp(self):
        vehicle = Vehicle.objects.create(name="Carro")
        make_row(vehicle)
        make_row(vehicle, odometer_km=38500, date=date(2026, 3, 15), gasoline_liters=Decimal("30"))
        recalculate_all(vehicle)
        self.client.force_login(User.objects.create_user("dono"))

    def test_policy_header(self):
        policy = self.client.get("/conta/login/")["Content-Security-Policy"]
        self.assertIn("script-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def test_pages_use_only_local_scripts(self):
        for url in ["/", "/otimizador/"]:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn("cdn.jsdelivr.net", html)
                self.assertNotIn("onclick=", html)
                # Só JSON de dados (json_script) pode aparecer como script sem src.
                self.assertNotRegex(html, r"<script>(?!\s*$)")
        self.assertIn("vendor/chartjs/chart.umd.js", self.client.get("/").content.decode())

    def test_vendored_chartjs_exists(self):
        self.assertTrue((Path(settings.BASE_DIR) / "static/vendor/chartjs/chart.umd.js").is_file())

    def test_production_collectstatic(self):
        """O storage com manifest (produção) falha se um arquivo referenciado não existir."""
        import tempfile

        from django.core.management import call_command

        storages = {**settings.STORAGES, "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
        with tempfile.TemporaryDirectory() as root, override_settings(STATIC_ROOT=root, STORAGES=storages):
            call_command("collectstatic", interactive=False, verbosity=0)
            self.assertTrue((Path(root) / "staticfiles.json").is_file())


class SecretKeyTests(TestCase):
    """SEG-03: sem DEBUG, o settings recusa chave ausente ou de exemplo."""

    def load_settings(self, **env):
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean_env.update(env)
        return subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            cwd=settings.BASE_DIR, env=clean_env, capture_output=True, text=True,
        )

    def test_missing_key_is_rejected(self):
        result = self.load_settings()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_example_key_is_rejected(self):
        result = self.load_settings(DJANGO_SECRET_KEY="change-me-generate-a-long-random-secret")
        self.assertNotEqual(result.returncode, 0)

    def test_strong_key_is_accepted(self):
        result = self.load_settings(DJANGO_SECRET_KEY="k" * 20 + "abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_debug_allows_missing_key(self):
        self.assertEqual(self.load_settings(DJANGO_DEBUG="True").returncode, 0)
