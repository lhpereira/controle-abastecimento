from decimal import Decimal

from django import template


register = template.Library()


@register.filter
def br_number(value, places=2):
    if value is None or value == "":
        return "—"
    rendered = f"{float(value):,.{int(places)}f}"
    return rendered.replace(",", "§").replace(".", ",").replace("§", ".")


@register.filter
def money(value, places=2):
    if value is None or value == "":
        return "—"
    return f"R$ {br_number(value, places)}"


@register.filter
def percent(value, places=1):
    if value is None or value == "":
        return "—"
    return f"{br_number(Decimal(value) * 100, places)}%"


@register.filter
def positive_class(value):
    if value is None:
        return "neutral"
    return "positive" if value >= 0 else "negative"

