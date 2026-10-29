"""The layer of pay-per-use services every portfolio can use (step 7, reused by step 8).

A pay-per-use option costs nothing until it is used, so having it is not a decision: every
candidate gets the same layer, and so must the current portfolio, or the comparison between
them would be unbalanced. The layer is:

    the services of `portfolio_rules.service_layer` that exist in the household's area;
    plus the services the household says it uses today (declared use proves the service is
    available to it, a statistical default proves nothing);
    plus the options that are always available at no cost (walking).
"""

from app.data.loader import Catalog
from app.models import (
    AreaType,
    MobilityDemand,
    Ownership,
    Portfolio,
    PortfolioItem,
    UserProfile,
    ValueSource,
)

_DECLARED = (ValueSource.DECLARED_EXACT, ValueSource.DECLARED_APPROXIMATE, ValueSource.OBSERVED)


def service_items(catalog: Catalog, area: AreaType, demand: MobilityDemand) -> list[PortfolioItem]:
    """Pay-per-use services available to a household in `area`, then the free options."""
    option_ids = [
        option_id
        for option_id in catalog.portfolio_rules.service_layer
        if area in catalog.option(option_id).available_in_area_types
    ]
    for usage in demand.current_service_usage:
        option = catalog.service_option(usage.service)
        declared = usage.annual_amount.source in _DECLARED
        if option is not None and declared and usage.annual_amount.value > 0:
            if option.id not in option_ids:
                option_ids.append(option.id)
    free = [o.id for o in catalog.options.values() if o.ownership is Ownership.FREE]
    return [PortfolioItem(option_id=option_id) for option_id in [*option_ids, *free]]


def with_service_layer(
    portfolio: Portfolio, catalog: Catalog, profile: UserProfile, demand: MobilityDemand
) -> Portfolio:
    """A copy of the portfolio with the common service layer added to what it already has."""
    area = profile.household.location.area_type
    present = {item.option_id for item in portfolio.items}
    added = [item for item in service_items(catalog, area, demand) if item.option_id not in present]
    return portfolio.model_copy(update={"items": [*portfolio.items, *added]})
