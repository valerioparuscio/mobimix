"""Intermediate and final results of evaluating a portfolio.

Pipeline (CLAUDE.md section 6): generate -> `FeasibilityResult` -> `ModeAssignment`
-> `PortfolioEvaluation` -> rank. Quantities that carry uncertainty are `Range`s.
"""

from enum import StrEnum

from pydantic import Field

from .base import DomainModel
from .demand import EstimationNote
from .portfolio import Portfolio, PortfolioItem
from .provenance import Confidence, Range


def _zero() -> Range:
    return Range.point(0.0)


class OptionUsage(DomainModel):
    """How one portfolio item is used in a year, and what is known about its situation.
    Input of `CostModel.calculate`. Uncertain quantities are `Range`s.

    All amounts are totals for the whole item: with `quantity` > 1 the usage is shared among
    the units, while fixed costs (insurance, tax...) are multiplied by `quantity`.
    """

    annual_km: Range = Field(default_factory=_zero)
    annual_trips: Range = Field(default_factory=_zero)
    annual_minutes: Range = Field(default_factory=_zero)
    annual_days: Range = Field(default_factory=_zero, description="Rental / day-pass days.")
    annual_toll_km: Range = Field(
        default_factory=_zero, description="Km driven on toll motorways (road vehicles)."
    )
    annual_destination_days: Range = Field(
        default_factory=_zero,
        description="Days of stay at a destination reached without a vehicle (rail, flights).",
    )
    annual_destination_charges: Range = Field(
        default_factory=_zero,
        description="Parking and access charges (EUR) paid at the destination by a car left "
        "there: already priced, as they depend on the destination, not on the car.",
    )
    months_held: float = Field(default=12.0, ge=0, le=12)
    quantity: int = Field(default=1, ge=1)
    existing_asset: bool = Field(
        default=False,
        description="True for an asset the household already owns (depreciation is then "
        "based on its present value); False for a new purchase.",
    )
    current_value: Range | None = Field(
        default=None, description="Present market value (EUR) of an existing asset, if known."
    )
    parking_cost_year: Range | None = Field(
        default=None, description="Parking / garage cost (EUR/year) per unit; overrides the option."
    )
    fixed_cost_override: Range | None = Field(
        default=None,
        description="What the household really pays per year for a subscription, if declared.",
    )


class CostLine(DomainModel):
    """One labelled amount of an annual cost, for explainability."""

    label: str = Field(description="Component code, e.g. depreciation, insurance, energy.")
    option_id: str | None = None
    amount: Range


class CostResult(DomainModel):
    """Annual cost of one option for a given usage."""

    option_id: str
    total: Range
    lines: list[CostLine]


class CostCategory(StrEnum):
    """Brief section 17.1: ownership + subscription + usage cost."""

    OWNERSHIP = "OWNERSHIP"
    SUBSCRIPTIONS = "SUBSCRIPTIONS"
    USAGE = "USAGE"


class ItemUsage(DomainModel):
    """The usage of one portfolio item and how far its inputs can be trusted."""

    usage: OptionUsage
    confidence: Confidence


class ItemCost(DomainModel):
    item: PortfolioItem
    category: CostCategory
    result: CostResult
    confidence: Confidence


class AccuracyHint(DomainModel):
    """The extra input that would most improve the estimate (brief section 23)."""

    field: str = Field(description='Stable id, e.g. "car1.annual_km".')
    message: str = Field(description="Plain-language suggestion, in Italian.")
    reduction_eur: float = Field(
        ge=0, description="Width of the cost range (EUR/year) that knowing it would remove."
    )


class PortfolioCost(DomainModel):
    """Annual cost of a portfolio for a given usage, by category and by item."""

    portfolio_id: str
    total: Range = Field(description="EUR / year")
    by_category: dict[CostCategory, Range]
    items: list[ItemCost]
    confidence: Confidence = Field(
        description="Trust in the inputs of the items that carry a material share of the cost."
    )
    notes: list[EstimationNote] = Field(default_factory=list)
    accuracy_hints: list[AccuracyHint] = Field(default_factory=list)


class CarKmCheck(DomainModel):
    """Declared car mileage against the estimated mobility needs: a plausibility check."""

    cars_km: Range
    needs_km: float
    ratio: float | None = Field(description="cars_km.expected / needs_km")
    all_declared: bool = Field(description="False if some car mileage was filled with defaults.")


class CurrentCostResult(DomainModel):
    """The current portfolio and what it costs (step 6)."""

    portfolio: Portfolio
    cost: PortfolioCost
    car_km_check: CarKmCheck | None = None


class Severity(StrEnum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


class FeasibilityIssueCode(StrEnum):
    NO_OPTION = "NO_OPTION"  # nothing in the portfolio can serve the mission
    NO_REGULAR_OPTION = "NO_REGULAR_OPTION"  # only means meant for the occasional trip can
    SIMULTANEOUS_CAR_NEED = "SIMULTANEOUS_CAR_NEED"  # two cars needed at once, fewer owned


class FeasibilityIssue(DomainModel):
    mission_id: str | None = None
    severity: Severity
    code: FeasibilityIssueCode
    message: str = Field(description="Plain-language reason, shown to the user if relevant.")


class FeasibilityResult(DomainModel):
    portfolio_id: str
    is_feasible: bool = Field(description="False if any issue is BLOCKING.")
    options_by_mission: dict[str, list[str]] = Field(
        default_factory=dict,
        description="For each mission, the portfolio options that can reasonably serve it.",
    )
    issues: list[FeasibilityIssue] = Field(default_factory=list)


class CheckedPortfolio(DomainModel):
    """A portfolio with the outcome of the feasibility check: what steps 9-11 work on."""

    portfolio: Portfolio
    feasibility: FeasibilityResult


class AllocationReason(StrEnum):
    """Why an option serves a share of a mission, for the explanation shown to the user."""

    ONLY_OPTION = "ONLY_OPTION"  # nothing else in the portfolio can serve the mission
    BEST = "BEST"  # the cheapest way, all things weighed, on an ordinary day
    ALTERNATIVE = "ALTERNATIVE"  # not the cheapest, but close enough to be used part of the time
    WEATHER = "WEATHER"  # replaces a means exposed to the weather on bad-weather days
    CAR_BUSY = "CAR_BUSY"  # replaces the car on the days someone else needs it


class MissionAllocation(DomainModel):
    mission_id: str
    option_id: str
    share: float = Field(gt=0, le=1, description="Fraction of the mission's occurrences.")
    reason: AllocationReason


class ModeAssignment(DomainModel):
    """Which option serves each mission. A mission may be split across options
    (e.g. commute by e-bike in good weather, by PT otherwise): the shares of a mission add
    up to 1."""

    portfolio_id: str
    allocations: list[MissionAllocation]
    unserved_mission_ids: list[str] = Field(
        default_factory=list,
        description="Missions nothing in the portfolio can serve (rare ones, which the "
        "feasibility check lets through with a warning).",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Plain-language remarks on how the assignment had to depart from the "
        "simple rule (a vehicle shared by two people, a constraint that could not be met).",
    )


class AssignedPortfolio(DomainModel):
    """A portfolio with its feasibility and, if feasible, how its missions are served: what
    the evaluator (step 10) works on. The current portfolio is always assigned, because it is
    the baseline even if the check finds fault with it."""

    portfolio: Portfolio
    feasibility: FeasibilityResult
    assignment: ModeAssignment | None = Field(
        default=None, description="None for a candidate rejected by the feasibility check."
    )


class PortfolioDelta(DomainModel):
    """Candidate minus current, computed mission by mission so that what both portfolios share -
    the same uncertain needs - cancels. Negative cost = saving."""

    cost: Range = Field(description="EUR / year; negative is a saving")
    travel_hours: Range
    perceived_hours: Range = Field(
        description="Travel hours weighted by discomfort (see `GeneralizedCost.time_weight`): "
        "the difference between this and `travel_hours` is what comfort costs in time."
    )
    comfort: Range
    flexibility: Range
    car_km: Range
    co2_kg: Range | None = None
    saving_per_extra_hour: float | None = Field(
        default=None,
        description="EUR saved per additional travel hour, when the candidate saves money "
        "and takes more time.",
    )


class PortfolioEvaluation(DomainModel):
    """What a portfolio costs, how long it takes, how comfortable it is (step 10).

    The cost is anchored to what the household declared (see `PortfolioEvaluator`); the other
    quantities come from the model alone, so only their differences between portfolios mean
    something."""

    portfolio_id: str
    annual_cost: Range = Field(description="EUR / year")
    cost_by_category: dict[CostCategory, Range] = Field(default_factory=dict)
    cost_lines: list[CostLine] = Field(
        default_factory=list,
        description="The cost item by item. For an item the household already has: its declared "
        "cost, plus a `usage_change` line if the portfolio makes it use the item more or less.",
    )
    annual_travel_hours: Range = Field(description="Person-hours of travel, all travellers")
    perceived_hours: Range = Field(description="The same hours, each weighted by its discomfort")
    comfort: Range = Field(description="0-10, averaged over the hours of travel")
    flexibility: Range = Field(description="0-10, averaged over the hours of travel")
    reliability: Range | None = Field(default=None, description="0-10, same average")
    car_km_per_year: Range = Field(description="Km driven in cars: owned, shared or rented")
    co2_kg_per_year: Range | None = None
    private_vehicles_owned: int = Field(ge=0, description="Owned cars and motorcycles")
    uses_by_option: dict[str, float] = Field(
        default_factory=dict,
        description="How many times a year each option of the portfolio is used (occurrences "
        "of the missions it serves, share applied).",
    )
    delta: PortfolioDelta | None = Field(
        default=None, description="Against the current portfolio; None for the current one."
    )
    confidence: Confidence
    data_quality_notes: list[str] = Field(default_factory=list)


class EvaluatedPortfolio(DomainModel):
    """A portfolio with its feasibility and, if it is feasible, its evaluation: what the
    recommendation engine (step 11) ranks. The current portfolio is always evaluated."""

    portfolio: Portfolio
    feasibility: FeasibilityResult
    evaluation: PortfolioEvaluation | None = Field(
        default=None, description="None for a candidate rejected by the feasibility check."
    )
