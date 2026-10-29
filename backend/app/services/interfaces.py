"""Replaceable modelling components (brief section 27, CLAUDE.md section 30).

Each stage of the analysis pipeline is a small interface so its first, simple
implementation can later be swapped for a richer one (real routing, city tariffs, MILP,
household schedules...) without touching the others:

    profile -> DemandEstimator -> demand
    profile, demand -> PortfolioGenerator -> portfolios
    portfolio, demand, profile -> FeasibilityChecker -> feasibility   (before any ranking)
    checked portfolio, demand, profile -> PortfolioOptimizer -> assignment
    assigned portfolio, baseline, demand, profile -> PortfolioEvaluator -> evaluation
    evaluated portfolios, demand, current cost, profile -> RecommendationEngine -> recommendations

They are `Protocol`s: implementations need no base class. Implementations receive their
reference data (the `Catalog`) through their constructor, never through globals.
"""

from typing import Protocol

from app.models import (
    AssignedPortfolio,
    CheckedPortfolio,
    CostResult,
    CurrentCostResult,
    EvaluatedPortfolio,
    FeasibilityResult,
    MobilityDemand,
    MobilityOption,
    ModeAssignment,
    OptionUsage,
    Portfolio,
    PortfolioEvaluation,
    RecommendationSet,
    UserProfile,
)
from app.services.scoring import Baseline


class DemandEstimator(Protocol):
    def estimate(self, profile: UserProfile) -> MobilityDemand: ...


class CostModel(Protocol):
    def calculate(self, option: MobilityOption, usage: OptionUsage) -> CostResult: ...


class PortfolioGenerator(Protocol):
    def generate(self, profile: UserProfile, demand: MobilityDemand) -> list[Portfolio]: ...


class FeasibilityChecker(Protocol):
    """The profile is passed beside the demand: licences and accessibility constraints belong
    to the people of the household, not to the missions."""

    def check(
        self, portfolio: Portfolio, demand: MobilityDemand, profile: UserProfile
    ) -> FeasibilityResult: ...


class PortfolioOptimizer(Protocol):
    """Works on a checked portfolio: the feasibility result says which options may serve each
    mission. The profile is passed for the same reason as in the checker (people, licences)."""

    def assign(
        self, checked: CheckedPortfolio, demand: MobilityDemand, profile: UserProfile
    ) -> ModeAssignment: ...


class PortfolioEvaluator(Protocol):
    """Evaluates an assigned portfolio. The cost of every portfolio is anchored to the declared
    cost of the current one, so the evaluator needs the baseline (see `scoring.Baseline`)."""

    def evaluate(
        self,
        assigned: AssignedPortfolio,
        baseline: Baseline,
        demand: MobilityDemand,
        profile: UserProfile,
    ) -> PortfolioEvaluation: ...


class RecommendationEngine(Protocol):
    """Chooses what to show and whether the household should change. `evaluated[0]` is the
    current portfolio; the demand and the cost of the current portfolio feed the explanations."""

    def recommend(
        self,
        evaluated: list[EvaluatedPortfolio],
        demand: MobilityDemand,
        current_cost: CurrentCostResult,
        profile: UserProfile,
    ) -> RecommendationSet: ...
