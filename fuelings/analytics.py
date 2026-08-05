import math
from collections import Counter
from decimal import Decimal

from .models import Fueling, Vehicle


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


def personal_limit_summary(rows):
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
        output.append(
            {
                "route": label,
                "ethanol_kml": eth_metrics["efficiency"],
                "gasoline_kml": gas_metrics["efficiency"],
                "personal": personal,
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


def dashboard_context(vehicle: Vehicle):
    rows = list(vehicle.fuelings.all())
    intervals = [row for row in rows if row.distance_km is not None]
    latest = rows[-1] if rows else None
    overall = weighted_metrics(intervals)
    bands = []
    for band, label in [
        (Fueling.MixBand.ETHANOL, "Etanol dominante"),
        (Fueling.MixBand.MIX, "Mistura"),
        (Fueling.MixBand.GASOLINE, "Gasolina dominante"),
    ]:
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

    chart_data = {
        "efficiency": [
            {"x": _number(row.burned_gas_c_share) * 100, "y": _number(row.efficiency_km_l), "route": row.route}
            for row in intervals
        ],
        "cost": [
            {"x": _number(row.burned_gas_c_share) * 100, "y": _number(row.cost_per_km), "route": row.route}
            for row in intervals
        ],
        "bands": {
            "labels": [item["label"] for item in bands],
            "values": [_number(item["cost_per_km"]) for item in bands],
        },
        "routes": {
            "labels": [item["label"] for item in routes],
            "values": [_number(item["efficiency"]) for item in routes],
        },
        "ratio": {
            "labels": [row.date.strftime("%d/%m/%y") for row in rows],
            "values": [_number(row.price_ratio) * 100 for row in rows],
            "limits": [_number(row.applicable_limit) * 100 for row in rows],
        },
        "composition": {
            "labels": [row.date.strftime("%d/%m/%y") for row in rows],
            "gasoline_a": [_number(row.gasoline_a_tank_share) * 100 for row in rows],
            "anhydrous": [_number(row.ethanol_anhydrous_tank_share) * 100 for row in rows],
            "hydrated": [_number(row.ethanol_hydrated_tank_share) * 100 for row in rows],
        },
    }

    recommendations = Counter(row.recommendation for row in rows)
    return {
        "vehicle": vehicle,
        "rows": rows,
        "recent_rows": list(reversed(rows[-8:])),
        "latest": latest,
        "overall": overall,
        "total_paid": sum((row.amount_paid or 0 for row in rows), Decimal("0")),
        "bands": bands,
        "routes": routes,
        "personal_limits": personal_limit_summary(intervals),
        "city_saving": city_saving,
        "city_saving_1000": city_saving_1000,
        "city_cost_correlation": correlation(city_rows, "burned_gas_c_share", "cost_per_km"),
        "city_efficiency_correlation": correlation(city_rows, "burned_gas_c_share", "efficiency_km_l"),
        "recommendations": recommendations,
        "chart_data": chart_data,
    }

