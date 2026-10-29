"""Recommendations and the top-level analysis result (brief sections 20-24).

Thresholds and wording of categories/strengths are design decisions to be settled with the
product owner; this module only fixes the *shape* of the output. Explanations are
structured facts produced by the model, never free text written independently of the
calculation (CLAUDE.md section 24).
"""

from enum import StrEnum

from pydantic import Field

from .base import DomainModel
from .demand import MobilityDemand
from .evaluation import AccuracyHint, FeasibilityIssue, PortfolioDelta, PortfolioEvaluation
from .portfolio import Portfolio
from .provenance import Confidence, Range
from .scenario import Scenario


class RecommendationRole(StrEnum):
    """Which point of the result set a recommendation represents. A single portfolio may
    hold several roles; identical portfolios are deduplicated."""

    CURRENT = "CURRENT"
    CHEAPEST = "CHEAPEST"
    BALANCED = "BALANCED"
    FASTEST = "FASTEST"
    MOST_COMFORTABLE = "MOST_COMFORTABLE"


class RecommendationCategory(StrEnum):
    """What kind of change the recommendation involves."""

    KEEP_CURRENT = "KEEP_CURRENT"
    OPTIMIZE_USAGE = "OPTIMIZE_USAGE"
    CHANGE_SUBSCRIPTION = "CHANGE_SUBSCRIPTION"
    ADD_ASSET = "ADD_ASSET"
    REPLACE_VEHICLE = "REPLACE_VEHICLE"
    REDUCE_VEHICLES = "REDUCE_VEHICLES"
    CHANGE_PORTFOLIO = "CHANGE_PORTFOLIO"


class RecommendationStrength(StrEnum):
    """How strongly a change is recommended once the change penalty is accounted for."""

    KEEP_CURRENT = "KEEP_CURRENT"
    SMALL_IMPROVEMENT = "SMALL_IMPROVEMENT"
    CONSIDER_CHANGE = "CONSIDER_CHANGE"
    STRONG_OPPORTUNITY = "STRONG_OPPORTUNITY"


class ExplanationFact(DomainModel):
    """A structured, machine-checkable reason, e.g. code='second_car_needed_days',
    values={'days_low': 28, 'days_high': 40}. Text is rendered from facts."""

    code: str
    values: dict[str, float | int | str] = Field(default_factory=dict)


class Recommendation(DomainModel):
    portfolio_id: str
    roles: list[RecommendationRole]
    category: RecommendationCategory
    strength: RecommendationStrength
    delta: PortfolioDelta | None = Field(
        default=None, description="None for the current portfolio."
    )
    change_penalty: float | None = Field(
        default=None, description="Switching cost in EUR-equivalent per year."
    )
    net_benefit: Range | None = Field(
        default=None, description="Economic benefit minus time, comfort and change penalties."
    )
    facts: list[ExplanationFact] = Field(default_factory=list)
    explanation: list[str] = Field(
        default_factory=list,
        description="The facts in plain Italian, one sentence each; rendered from `facts` alone.",
    )
    confidence: Confidence


class RecommendationSet(DomainModel):
    recommendations: list[Recommendation]
    headline_portfolio_id: str = Field(
        description="The answer to 'should I change?': the alternative with the highest net "
        "benefit if it is worth the change, else the current portfolio."
    )
    pareto_portfolio_ids: list[str] = Field(default_factory=list)
    accuracy_hints: list[AccuracyHint] = Field(default_factory=list)


class RejectedPortfolio(DomainModel):
    portfolio_id: str
    name: str
    description: str | None = None
    issues: list[FeasibilityIssue]


class AnalysisResult(DomainModel):
    """Output of `POST /api/analyze`: everything the UI needs, structured and aggregatable
    (MobiMix City will call the same analysis on synthetic households)."""

    profile_id: str
    scenario: Scenario | None = Field(
        default=None,
        description="The what-if assumptions the analysis was run with; None for the analysis of "
        "the household as it is.",
    )
    parameters_version: str | None = Field(
        default=None, description="Identifier of the data/ snapshot used."
    )
    demand: MobilityDemand
    portfolios: list[Portfolio] = Field(description="Current plus all feasible candidates.")
    current: PortfolioEvaluation
    evaluations: list[PortfolioEvaluation]
    rejected: list[RejectedPortfolio] = Field(default_factory=list)
    recommendations: RecommendationSet
