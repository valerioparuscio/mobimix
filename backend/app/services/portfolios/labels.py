"""Plain-language names and change summaries for generated portfolios.

Both are built from the structured items and changes of a portfolio, never written separately
(CLAUDE.md section 24): what the screen says is what the model holds.
"""

from collections import Counter

from app.data.loader import Catalog
from app.models import (
    ChangeKind,
    Mode,
    OptionType,
    Ownership,
    PortfolioChange,
    PortfolioItem,
)

_TRANSIT_PASSES = (OptionType.PT_ANNUAL, OptionType.PT_MONTHLY)

_VERBS = {
    ChangeKind.SELL_VEHICLE: "vendere",
    ChangeKind.BUY_VEHICLE: "acquistare",
    ChangeKind.CANCEL_SUBSCRIPTION: "disdire",
    ChangeKind.START_SUBSCRIPTION: "sottoscrivere",
}


def _count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def portfolio_label(items: list[PortfolioItem], catalog: Catalog) -> str:
    """Name of a setup, e.g. "Auto media a benzina + 2 abbonamenti TP + e-bike".

    Only what a household decides is named: cars, powered two-wheelers, e-bikes and transit
    passes. Bicycles, bike-sharing and pay-per-use services are not part of the name."""
    cars: Counter[str] = Counter()
    two_wheelers: list[str] = []
    passes = rail_passes = 0
    for item in items:
        option = catalog.option(item.option_id)
        if option.ownership is Ownership.OWNED:
            if option.mode is Mode.CAR:
                cars[option.name] += item.quantity
            elif option.type is OptionType.E_BIKE:
                two_wheelers.append("e-bike")
            elif option.mode is Mode.MOTORCYCLE:
                two_wheelers.append(option.name.lower())
        elif option.ownership is Ownership.SUBSCRIPTION:
            if option.type in _TRANSIT_PASSES:
                passes += item.quantity
            elif option.type is OptionType.RAIL_SUBSCRIPTION:
                rail_passes += item.quantity

    car_names = [name if n == 1 else f"{n} × {name}" for name, n in cars.items()]
    parts = [" + ".join(car_names) if car_names else "Senza auto"]
    if passes:
        parts.append(_count(passes, "abbonamento TP", "abbonamenti TP"))
    if rail_passes:
        parts.append(_count(rail_passes, "abbonamento treno", "abbonamenti treno"))
    parts.extend(two_wheelers)
    return " + ".join(parts)


def describe_changes(changes: list[PortfolioChange], catalog: Catalog) -> str:
    """What the household would do, e.g. "Vendere «Utilitaria a benzina»; acquistare «E-bike»."
    Empty string when nothing changes."""
    grouped: Counter[tuple[ChangeKind, str]] = Counter(
        (change.kind, change.option_id) for change in changes
    )
    steps = []
    for (kind, option_id), n in grouped.items():
        name = f"«{catalog.option(option_id).name}»"
        steps.append(f"{_VERBS[kind]} {name if n == 1 else f'{n} × {name}'}")
    if not steps:
        return ""
    text = "; ".join(steps)
    return f"{text[0].upper()}{text[1:]}."
