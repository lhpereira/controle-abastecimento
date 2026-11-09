import math
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from .models import Fueling, Vehicle
from .templatetags.formatting import br_number, money


def _number(value):
    return float(value) if value is not None else None


def weighted_metrics(rows):
    usable = [row for row in rows if row.distance_km and row.burned_price_per_liter is not None]
    distance = sum(row.distance_km for row in usable)
    liters = sum((row.total_liters for row in usable), Decimal("0"))
    cost = sum((row.total_liters * row.burned_price_per_liter for row in usable), Decimal("0"))
    return {
        "count": len(usable),
        "distance": distance,
        "liters": liters,
        "efficiency": Decimal(distance) / liters if liters else None,
        "cost_per_km": cost / Decimal(distance) if distance else None,
        "cost": cost,
    }


def correlation(rows, x_name, y_name):
    points = [
        (float(getattr(row, x_name)), float(getattr(row, y_name)))
        for row in rows
        if getattr(row, x_name) is not None and getattr(row, y_name) is not None
    ]
    if len(points) < 3:
        return None
    xs, ys = zip(*points)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in points) / denominator if denominator else None


def personal_limit_summary(rows, vehicle=None):
    output = []
    for route, label in Fueling.Route.choices:
        route_rows = [row for row in rows if row.route == route and row.distance_km]
        ethanol = [row for row in route_rows if row.burned_gas_c_share <= Decimal("0.20")]
        gasoline = [row for row in route_rows if row.burned_gas_c_share >= Decimal("0.80")]
        eth_metrics = weighted_metrics(ethanol)
        gas_metrics = weighted_metrics(gasoline)
        personal = (
            eth_metrics["efficiency"] / gas_metrics["efficiency"]
            if eth_metrics["efficiency"] and gas_metrics["efficiency"]
            else None
        )
        saving = (
            Decimal("1") - eth_metrics["cost_per_km"] / gas_metrics["cost_per_km"]
            if eth_metrics["cost_per_km"] and gas_metrics["cost_per_km"]
            else None
        )
        official = vehicle.official_limit_for(route) if vehicle else None
        output.append(
            {
                "route": label,
                "ethanol_kml": eth_metrics["efficiency"],
                "gasoline_kml": gas_metrics["efficiency"],
                "ethanol_cost": eth_metrics["cost_per_km"],
                "gasoline_cost": gas_metrics["cost_per_km"],
                "saving": saving,
                "personal": personal,
                "official": official,
                "gap": personal - official if personal is not None and official is not None else None,
                "ethanol_count": len(ethanol),
                "gasoline_count": len(gasoline),
            }
        )
    return output


def optimizer_model(rows, route, gasoline_price, ethanol_price, tolerance):
    route_rows = [
        row
        for row in rows
        if row.route == route and row.burned_gas_c_share is not None and row.efficiency_km_l is not None
    ]
    if len(route_rows) < 2:
        return {"ready": False, "status": "Faltam ciclos para estimar a curva", "grid": [], "count": len(route_rows)}

    xs = [float(row.burned_gas_c_share) for row in route_rows]
    ys = [float(row.efficiency_km_l) for row in route_rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator if denominator else 0
    intercept = my - slope * mx
    predictions = [intercept + slope * x for x in xs]
    total_variation = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum((y - p) ** 2 for y, p in zip(ys, predictions)) / total_variation if total_variation else None

    grid = []
    for percentage in range(101):
        gas_share = percentage / 100
        efficiency = intercept + slope * gas_share
        if efficiency <= 0:
            continue
        liter_price = float(ethanol_price) + (float(gasoline_price) - float(ethanol_price)) * gas_share
        grid.append(
            {
                "gasoline_share": gas_share,
                "ethanol_share": 1 - gas_share,
                "efficiency": efficiency,
                "cost_per_km": liter_price / efficiency,
            }
        )

    has_ethanol = any(x <= 0.20 for x in xs)
    has_gasoline = any(x >= 0.80 for x in xs)
    ready = len(route_rows) >= 8 and has_ethanol and has_gasoline
    best = min(grid, key=lambda item: item["cost_per_km"]) if ready and grid else None
    balanced = None
    if best:
        ceiling = best["cost_per_km"] * (1 + float(tolerance))
        candidates = [item for item in grid if item["cost_per_km"] <= ceiling]
        balanced = max(candidates, key=lambda item: item["efficiency"], default=None)

    if ready:
        status = "Estimativa disponível"
    elif not has_ethanol:
        status = "Faltam ciclos com etanol dominante"
    elif not has_gasoline:
        status = "Faltam ciclos com gasolina dominante"
    else:
        status = "Amostra pequena; são necessários pelo menos 8 ciclos"

    return {
        "ready": ready,
        "status": status,
        "count": len(route_rows),
        "min_share": min(xs),
        "max_share": max(xs),
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "grid": grid,
        "best": best,
        "balanced": balanced,
    }


BAND_CHOICES = [
    (Fueling.MixBand.ETHANOL, "Etanol dominante"),
    (Fueling.MixBand.MIX, "Mistura"),
    (Fueling.MixBand.GASOLINE, "Gasolina dominante"),
]
PERIOD_CHOICES = [("all", "Todo o histórico", None), ("3", "Últimos 3 meses", 3), ("6", "Últimos 6 meses", 6), ("12", "Últimos 12 meses", 12)]
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def parse_filters(params):
    """Lê os filtros do dashboard a partir de uma QueryDict (ou None)."""
    period = params.get("periodo", "all") if params else "all"
    if period not in {key for key, _, _ in PERIOD_CHOICES}:
        period = "all"
    routes = [value for value in (params.getlist("trajeto") if params else []) if value in Fueling.Route.values]
    band = params.get("faixa", "") if params else ""
    if band not in {value for value, _ in BAND_CHOICES}:
        band = ""
    return {"period": period, "routes": routes, "band": band}


def apply_filters(rows, filters):
    """Filtra os registros mantendo os valores já calculados em cada ciclo."""
    months = next(months for key, _, months in PERIOD_CHOICES if key == filters["period"])
    if months and rows:
        cutoff = max(row.date for row in rows) - timedelta(days=round(months * 30.44))
        rows = [row for row in rows if row.date >= cutoff]
    if filters["routes"]:
        rows = [row for row in rows if row.route in filters["routes"]]
    if filters["band"]:
        rows = [row for row in rows if row.mix_band == filters["band"]]
    return rows


def linear_fit(points):
    """Regressão linear simples sobre pares (x, y); None se não houver base suficiente."""
    if len(points) < 3:
        return None
    xs, ys = zip(*points)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    intercept = my - slope * mx
    total = sum((y - my) ** 2 for y in ys)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    return {
        "slope": slope,
        "intercept": intercept,
        "r2": 1 - residual / total if total else None,
        "n": len(points),
        "x_min": min(xs),
        "x_max": max(xs),
    }


def describe_correlation(r):
    if r is None:
        return "Amostra insuficiente para medir a associação."
    strength = "forte" if abs(r) >= 0.7 else "moderada" if abs(r) >= 0.4 else "fraca"
    if abs(r) < 0.15:
        return "Praticamente nenhuma associação linear entre a mistura consumida e o custo por km."
    direction = "mais gasolina C acompanha custo/km maior" if r > 0 else "mais gasolina C acompanha custo/km menor"
    return f"Associação {strength}: {direction}."


def _fit_line(fit, scale=100):
    if not fit:
        return None
    return {
        "x0": fit["x_min"] * scale,
        "y0": fit["intercept"] + fit["slope"] * fit["x_min"],
        "x1": fit["x_max"] * scale,
        "y1": fit["intercept"] + fit["slope"] * fit["x_max"],
        "r2": fit["r2"],
        "n": fit["n"],
    }


def moving_average(values, window=3):
    output = []
    for index in range(len(values)):
        chunk = [v for v in values[max(0, index - window + 1) : index + 1] if v is not None]
        output.append(sum(chunk) / len(chunk) if chunk else None)
    return output


def monthly_summary(rows):
    buckets = {}
    for row in rows:
        bucket = buckets.setdefault((row.date.year, row.date.month), {"spend": Decimal("0"), "rows": []})
        bucket["spend"] += row.amount_paid or Decimal("0")
        bucket["rows"].append(row)
    summary = []
    for (year, month), bucket in sorted(buckets.items()):
        metrics = weighted_metrics([r for r in bucket["rows"] if r.distance_km is not None])
        summary.append(
            {
                "label": f"{MONTHS[month - 1]}/{str(year)[2:]}",
                "spend": bucket["spend"],
                "distance": metrics["distance"],
                "cost_per_km": metrics["cost_per_km"],
                "efficiency": metrics["efficiency"],
            }
        )
    return summary


def band_matrix(intervals):
    """Eficiência e custo/km para cada combinação trajeto × faixa de mistura."""
    matrix = []
    for route, route_label in Fueling.Route.choices:
        for band, band_label in BAND_CHOICES:
            subset = [row for row in intervals if row.route == route and row.mix_band == band]
            metrics = weighted_metrics(subset)
            matrix.append(
                {
                    "route": route_label,
                    "band": band_label,
                    "count": metrics["count"],
                    "distance": metrics["distance"],
                    "efficiency": _number(metrics["efficiency"]),
                    "cost_per_km": _number(metrics["cost_per_km"]),
                }
            )
    return matrix


def ideal_mix_cards(rows, vehicle, latest, selected_routes=()):
    """Mistura de menor custo por trajeto, estimada com os últimos preços registrados."""
    if latest is None:
        return []
    cards = []
    for route, label in Fueling.Route.choices:
        if selected_routes and route not in selected_routes:
            continue
        model = optimizer_model(rows, route, latest.gasoline_price, latest.ethanol_price, vehicle.optimizer_tolerance)
        cards.append({"route": label, "route_value": route, **model})
    return cards


def build_insights(intervals, fits):
    insights = []

    fit = fits.get("efficiency")
    if fit:
        per_ten = fit["slope"] * 0.1
        signed = f"{'+' if per_ten >= 0 else '−'}{br_number(abs(per_ten), 2)} km/L"
        weak = fit["r2"] is not None and fit["r2"] < 0.2
        insights.append(
            {
                "tone": "blue",
                "title": "Sensibilidade do consumo",
                "value": signed,
                "text": (
                    f"A cada +10 p.p. de gasolina C consumida, o consumo varia {signed} em média "
                    f"(R² {br_number(fit['r2'], 2)}, {fit['n']} ciclos). "
                    + (
                        "R² baixo: a mistura explica pouco do consumo, e fatores como trânsito e ar-condicionado pesam mais."
                        if weak
                        else "Quanto maior o R², mais a mistura explica o consumo."
                    )
                ),
            }
        )

    if len(intervals) >= 6:
        window = min(4, len(intervals) // 2)
        recent = weighted_metrics(intervals[-window:])["cost_per_km"]
        previous = weighted_metrics(intervals[-2 * window : -window])["cost_per_km"]
        if recent and previous:
            change = float(recent / previous - 1)
            insights.append(
                {
                    "tone": "positive" if change <= 0 else "amber",
                    "title": "Tendência de custo/km",
                    "value": f"{'+' if change >= 0 else '−'}{br_number(abs(change) * 100, 1)}%",
                    "text": (
                        f"Custo ponderado dos últimos {window} ciclos ({money(recent, 3)}/km) contra os {window} anteriores "
                        f"({money(previous, 3)}/km)."
                    ),
                }
            )

    priced = [row for row in intervals if row.cost_per_km is not None]
    if priced:
        best = min(priced, key=lambda row: row.cost_per_km)
        worst = max(priced, key=lambda row: row.cost_per_km)
        insights.append(
            {
                "tone": "positive",
                "title": "Ciclo mais barato",
                "value": f"{money(best.cost_per_km, 3)}/km",
                "text": (
                    f"{best.date:%d/%m/%Y} · {best.route} · {br_number(best.burned_gas_c_share * 100, 0)}% gasolina C. "
                    f"O mais caro custou {money(worst.cost_per_km, 3)}/km ({worst.date:%d/%m/%Y})."
                ),
                "pk": best.pk,
            }
        )
    return insights


def dashboard_context(vehicle: Vehicle, params=None):
    all_rows = list(vehicle.fuelings.all())
    filters = parse_filters(params)
    rows = apply_filters(all_rows, filters)
    intervals = [row for row in rows if row.distance_km is not None]
    # A decisão mais recente reflete o último abastecimento real, independentemente dos filtros.
    latest = all_rows[-1] if all_rows else None
    overall = weighted_metrics(intervals)
    bands = []
    for band, label in BAND_CHOICES:
        metrics = weighted_metrics([row for row in intervals if row.mix_band == band])
        bands.append({"label": label, **metrics})

    routes = []
    for route, label in Fueling.Route.choices:
        metrics = weighted_metrics([row for row in intervals if row.route == route])
        routes.append({"label": label, **metrics})

    city_rows = [row for row in intervals if row.route == Fueling.Route.CITY]
    city_eth = weighted_metrics([row for row in city_rows if row.mix_band == Fueling.MixBand.ETHANOL])
    city_gas = weighted_metrics([row for row in city_rows if row.mix_band == Fueling.MixBand.GASOLINE])
    city_saving = None
    city_saving_1000 = None
    if city_eth["cost_per_km"] and city_gas["cost_per_km"]:
        city_saving = Decimal("1") - city_eth["cost_per_km"] / city_gas["cost_per_km"]
        city_saving_1000 = (city_gas["cost_per_km"] - city_eth["cost_per_km"]) * 1000

    def points(metric):
        return [
            (float(row.burned_gas_c_share), float(getattr(row, metric)))
            for row in intervals
            if getattr(row, metric) is not None
        ]

    fits = {"efficiency": linear_fit(points("efficiency_km_l")), "cost": linear_fit(points("cost_per_km"))}
    route_fits = {}
    for route, _ in Fueling.Route.choices:
        route_rows = [row for row in intervals if row.route == route]
        route_fits[route] = {
            "efficiency": _fit_line(linear_fit(list(zip(*_series(route_rows, "efficiency_km_l"))))),
            "cost": _fit_line(linear_fit(list(zip(*_series(route_rows, "cost_per_km"))))),
        }

    def scatter(metric):
        return [
            {
                "x": _number(row.burned_gas_c_share) * 100,
                "y": _number(getattr(row, metric)),
                "route": row.route,
                "date": row.date.strftime("%d/%m/%Y"),
                "km": row.distance_km,
                "url": reverse("fueling_detail", args=[row.pk]),
            }
            for row in intervals
            if getattr(row, metric) is not None
        ]

    efficiency_series = [_number(row.efficiency_km_l) for row in intervals]
    cost_series = [_number(row.cost_per_km) for row in intervals]
    monthly = monthly_summary(rows)

    chart_data = {
        "efficiency": scatter("efficiency_km_l"),
        "cost": scatter("cost_per_km"),
        "fits": route_fits,
        "matrix": band_matrix(intervals),
        "timeline": {
            "labels": [row.date.strftime("%d/%m/%y") for row in intervals],
            "routes": [row.route for row in intervals],
            "urls": [reverse("fueling_detail", args=[row.pk]) for row in intervals],
            "efficiency": efficiency_series,
            "efficiency_avg": moving_average(efficiency_series),
            "cost": cost_series,
            "cost_avg": moving_average(cost_series),
        },
        "monthly": {
            "labels": [item["label"] for item in monthly],
            "spend": [_number(item["spend"]) for item in monthly],
            "cost_per_km": [_number(item["cost_per_km"]) for item in monthly],
            "distance": [item["distance"] for item in monthly],
        },
        "ratio": {
            "labels": [row.date.strftime("%d/%m/%y") for row in rows],
            "values": [_number(row.price_ratio) * 100 for row in rows],
            "limits": [_number(row.applicable_limit) * 100 for row in rows],
            "neutral": _number(vehicle.neutral_band) * 100,
            "gasoline": [_number(row.gasoline_price) for row in rows],
            "ethanol": [_number(row.ethanol_price) for row in rows],
        },
        "composition": {
            "labels": [row.date.strftime("%d/%m/%y") for row in rows],
            "gasoline_a": [_number(row.gasoline_a_tank_share) * 100 for row in rows],
            "anhydrous": [_number(row.ethanol_anhydrous_tank_share) * 100 for row in rows],
            "hydrated": [_number(row.ethanol_hydrated_tank_share) * 100 for row in rows],
        },
    }

    city_cost_correlation = correlation(city_rows, "burned_gas_c_share", "cost_per_km")
    recommendations = Counter(row.recommendation for row in rows)
    filtered = filters["period"] != "all" or bool(filters["routes"]) or bool(filters["band"])
    return {
        "vehicle": vehicle,
        "rows": all_rows,
        "filtered_rows": rows,
        "recent_rows": list(reversed(rows[-8:])),
        "latest": latest,
        "overall": overall,
        "total_paid": sum((row.amount_paid or 0 for row in rows), Decimal("0")),
        "bands": bands,
        "routes": routes,
        "personal_limits": personal_limit_summary(intervals, vehicle),
        "city_saving": city_saving,
        "city_saving_abs": abs(city_saving) if city_saving is not None else None,
        "city_saving_1000": city_saving_1000,
        "city_cost_correlation": city_cost_correlation,
        "city_correlation_text": describe_correlation(city_cost_correlation),
        "city_efficiency_correlation": correlation(city_rows, "burned_gas_c_share", "efficiency_km_l"),
        "insights": build_insights(intervals, fits),
        "ideal_mix": ideal_mix_cards(rows, vehicle, latest, filters["routes"]),
        "recommendations": recommendations,
        "chart_data": chart_data,
        "filters": filters,
        "filtered": filtered,
        "period_choices": [(key, label) for key, label, _ in PERIOD_CHOICES],
        "band_choices": BAND_CHOICES,
        "route_choices": Fueling.Route.choices,
        "interval_count": len(intervals),
        "total_count": sum(1 for row in all_rows if row.distance_km is not None),
    }


def _series(rows, metric):
    usable = [row for row in rows if getattr(row, metric) is not None]
    return [float(row.burned_gas_c_share) for row in usable], [float(getattr(row, metric)) for row in usable]

