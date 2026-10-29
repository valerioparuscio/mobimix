"""Mobility portfolios (brief section 14).

A portfolio is the set of resources available to a household: owned vehicles,
subscriptions and pay-per-use services. It says nothing about how missions are served -
that is a `ModeAssignment`.
"""

from enum import StrEnum

from pydantic import Field

from .base import DomainModel


class PortfolioOrigin(StrEnum):
    CURRENT = "CURRENT"
    GENERATED = "GENERATED"


class PortfolioItem(DomainModel):
    """One resource. Presence of a pay-per-use option means "available", at no fixed cost."""

    option_id: str
    holder_id: str | None = Field(
        default=None, description="Person the item belongs to; None means the household."
    )
    quantity: int = Field(default=1, ge=1)
    profile_ref: str | None = Field(
        default=None,
        description="Id of the OwnedVehicle / HeldSubscription this item was built from, so "
        "declared annual km and costs can be carried over for the current portfolio.",
    )


class ChangeKind(StrEnum):
    SELL_VEHICLE = "SELL_VEHICLE"
    BUY_VEHICLE = "BUY_VEHICLE"
    CANCEL_SUBSCRIPTION = "CANCEL_SUBSCRIPTION"
    START_SUBSCRIPTION = "START_SUBSCRIPTION"


class PortfolioChange(DomainModel):
    """One step the household would take to get from today's setup to a candidate.

    Only commitments are changes: vehicles and subscriptions. Pay-per-use services are
    available or not; using them more or less is a change of habit, which the assignment
    step measures. The recommendation engine prices the effort of a change from this list.
    """

    kind: ChangeKind
    option_id: str
    holder_id: str | None = None
    profile_ref: str | None = Field(
        default=None,
        description="For a sale or a cancellation: the OwnedVehicle / HeldSubscription that goes.",
    )


class Portfolio(DomainModel):
    id: str
    name: str
    origin: PortfolioOrigin = PortfolioOrigin.GENERATED
    items: list[PortfolioItem]
    generation_rule: str | None = Field(
        default=None, description="Which generator rule produced this candidate."
    )
    description: str | None = None
    changes: list[PortfolioChange] = Field(
        default_factory=list,
        description="What the household would have to do to move from the current portfolio to "
        "this one. Empty for the current portfolio.",
    )

    @property
    def signature(self) -> tuple[tuple[str, str | None, int], ...]:
        """Canonical content, ignoring id and name. Used to deduplicate identical portfolios."""
        return tuple(sorted((item.option_id, item.holder_id, item.quantity) for item in self.items))
