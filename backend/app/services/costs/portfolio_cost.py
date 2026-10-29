"""Cost of a whole portfolio: sum of its items, by category, with a confidence and hints.

total      = sum of the items' annual costs
category   = OWNERSHIP (owned assets, incl. their energy), SUBSCRIPTIONS, USAGE (pay-per-use)
confidence = weakest confidence among the items that carry a material share of the total
             (costing.material_share): a tiny uncertain item must not drag the result down
hints      = for each uncertain input, how much narrower the cost range would become if the
             user gave that input exactly (brief section 23: "which extra input would most
             improve accuracy"); the three largest are returned
"""

from collections.abc import Sequence

from app.data.loader import Catalog
from app.models import (
    AccuracyHint,
    Confidence,
    CostCategory,
    EstimationNote,
    ItemCost,
    ItemUsage,
    OptionUsage,
    Ownership,
    Portfolio,
    PortfolioCost,
    Range,
)
from app.services.costs.model import TcoCostModel
from app.services.statistics.estimation import weakest_confidence

CATEGORY_BY_OWNERSHIP = {
    Ownership.OWNED: CostCategory.OWNERSHIP,
    Ownership.SUBSCRIPTION: CostCategory.SUBSCRIPTIONS,
    Ownership.PAY_PER_USE: CostCategory.USAGE,
    Ownership.FREE: CostCategory.USAGE,
}

_HINT_TEXT = {
    "annual_km": "Se indichi i km percorsi in un anno con «{name}», la stima del costo si "
    "restringe di circa {amount} € l'anno.",
    "current_value": "Se indichi quanto vale oggi «{name}», la stima del costo si restringe di "
    "circa {amount} € l'anno.",
    "parking_cost_year": "Se indichi quanto spendi in un anno per il parcheggio di «{name}», la "
    "stima del costo si restringe di circa {amount} € l'anno.",
    "annual_trips": "Se indichi quante volte usi «{name}» in un anno, la stima del costo si "
    "restringe di circa {amount} € l'anno.",
    "annual_days": "Se indichi quanti giorni usi «{name}» in un anno, la stima del costo si "
    "restringe di circa {amount} € l'anno.",
}
_MAX_HINTS = 3


class PortfolioCostCalculator:
    def __init__(self, catalog: Catalog, cost_model: TcoCostModel | None = None) -> None:
        self._catalog = catalog
        self._model = cost_model or TcoCostModel(catalog)

    def price(
        self,
        portfolio: Portfolio,
        usages: Sequence[ItemUsage],
        notes: Sequence[EstimationNote] = (),
    ) -> PortfolioCost:
        """`usages[i]` is the usage of `portfolio.items[i]`."""
        if len(usages) != len(portfolio.items):
            raise ValueError("one ItemUsage is needed for every portfolio item")

        items = []
        for item, item_usage in zip(portfolio.items, usages, strict=True):
            option = self._catalog.option(item.option_id)
            items.append(
                ItemCost(
                    item=item,
                    category=CATEGORY_BY_OWNERSHIP[option.ownership],
                    result=self._model.calculate(option, item_usage.usage),
                    confidence=item_usage.confidence,
                )
            )

        total = _sum(cost.result.total for cost in items)
        by_category = {
            category: _sum(cost.result.total for cost in items if cost.category is category)
            for category in CostCategory
        }
        return PortfolioCost(
            portfolio_id=portfolio.id,
            total=total,
            by_category=by_category,
            items=items,
            confidence=self._confidence(items, total),
            notes=list(notes),
            accuracy_hints=self._hints(portfolio, usages, items),
        )

    # --- confidence ------------------------------------------------------------------------

    def _confidence(self, items: list[ItemCost], total: Range) -> Confidence:
        if total.expected <= 0:
            return Confidence.HIGH  # nothing costs anything: nothing is uncertain
        share = self._catalog.value("costing.material_share")
        material = [c for c in items if c.result.total.expected >= share * total.expected]
        return weakest_confidence(cost.confidence for cost in material)

    # --- accuracy hints --------------------------------------------------------------------

    def _hints(
        self, portfolio: Portfolio, usages: Sequence[ItemUsage], items: list[ItemCost]
    ) -> list[AccuracyHint]:
        hints = []
        for item, item_usage, cost in zip(portfolio.items, usages, items, strict=True):
            option = self._catalog.option(item.option_id)
            usage = item_usage.usage
            before = cost.result.total.width
            for field, pinned in self._pinned_usages(option, usage):
                after = self._model.calculate(option, pinned).total.width
                reduction = before - after
                if reduction < 1.0:
                    continue
                subject = item.profile_ref or item.option_id
                hints.append(
                    AccuracyHint(
                        field=f"{subject}.{field}",
                        message=_HINT_TEXT[field].format(
                            name=option.name, amount=int(round(reduction, -1)) or 10
                        ),
                        reduction_eur=reduction,
                    )
                )
        hints.sort(key=lambda hint: hint.reduction_eur, reverse=True)
        return hints[:_MAX_HINTS]

    def _pinned_usages(self, option, usage: OptionUsage):
        """Variants of `usage` in which one uncertain input is known exactly."""
        for field in ("annual_km", "annual_trips", "annual_days"):
            value: Range = getattr(usage, field)
            if value.width > 0:
                yield field, usage.model_copy(update={field: Range.point(value.expected)})
        if usage.parking_cost_year is not None and usage.parking_cost_year.width > 0:
            yield (
                "parking_cost_year",
                usage.model_copy(
                    update={"parking_cost_year": Range.point(usage.parking_cost_year.expected)}
                ),
            )
        if usage.existing_asset and usage.current_value is None:
            value = self._model.expected_current_value(option)
            if value is not None:
                yield (
                    "current_value",
                    usage.model_copy(update={"current_value": Range.point(value)}),
                )


def _sum(ranges) -> Range:
    """Items err independently of each other (a simplification: the fuel price is shared)."""
    return Range.sum_independent(ranges)
