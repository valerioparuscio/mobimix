"""The analysis pipeline, stage by stage, callable without HTTP (CLAUDE.md section 35: MobiMix
City will run it on synthetic households).

    profile -> demand -> current portfolio + candidates -> feasibility -> assignment -> evaluation

Each function runs the pipeline up to its stage and returns the demand, the cost of the current
portfolio (step 6, declared) and the portfolios with what that stage found. The current portfolio
is always first, with the same common service layer as the candidates, and is never dropped:
it is the baseline.
"""

from app.data.loader import Catalog
from app.models import (
    AnalysisResult,
    AssignedPortfolio,
    CheckedPortfolio,
    CurrentCostResult,
    EvaluatedPortfolio,
    MobilityDemand,
    PortfolioOrigin,
    RejectedPortfolio,
    Scenario,
    Severity,
    UserProfile,
)
from app.services.costs import CurrentCostEstimator
from app.services.demand import RuleBasedDemandEstimator
from app.services.feasibility import RuleBasedFeasibilityChecker
from app.services.optimizer import GeneralizedCostAssigner
from app.services.portfolios import RuleBasedPortfolioGenerator, with_service_layer
from app.services.recommendations import RuleBasedRecommendationEngine
from app.services.scenarios import apply_scenario
from app.services.scoring import PortfolioEvaluator


def checked_portfolios(
    catalog: Catalog, profile: UserProfile
) -> tuple[MobilityDemand, CurrentCostResult, list[CheckedPortfolio]]:
    demand = RuleBasedDemandEstimator(catalog).estimate(profile)
    current_cost = CurrentCostEstimator(catalog).estimate(profile, demand)
    portfolios = [
        with_service_layer(current_cost.portfolio, catalog, profile, demand),
        *RuleBasedPortfolioGenerator(catalog).generate(profile, demand),
    ]
    checker = RuleBasedFeasibilityChecker(catalog)
    return (
        demand,
        current_cost,
        [
            CheckedPortfolio(
                portfolio=portfolio, feasibility=checker.check(portfolio, demand, profile)
            )
            for portfolio in portfolios
        ],
    )


def assigned_portfolios(
    catalog: Catalog, profile: UserProfile
) -> tuple[MobilityDemand, CurrentCostResult, list[AssignedPortfolio]]:
    """A candidate rejected by the feasibility check is not assigned; the current one always is."""
    demand, current_cost, checked = checked_portfolios(catalog, profile)
    assigner = GeneralizedCostAssigner(catalog)
    assigned = []
    for entry in checked:
        is_baseline = entry.portfolio.origin is PortfolioOrigin.CURRENT
        assignment = (
            assigner.assign(entry, demand, profile)
            if entry.feasibility.is_feasible or is_baseline
            else None
        )
        assigned.append(
            AssignedPortfolio(
                portfolio=entry.portfolio, feasibility=entry.feasibility, assignment=assignment
            )
        )
    return demand, current_cost, assigned


def evaluated_portfolios(
    catalog: Catalog, profile: UserProfile
) -> tuple[MobilityDemand, CurrentCostResult, list[EvaluatedPortfolio]]:
    demand, current_cost, assigned = assigned_portfolios(catalog, profile)
    evaluator = PortfolioEvaluator(catalog)
    baseline = evaluator.baseline(assigned[0], current_cost, demand)
    return (
        demand,
        current_cost,
        [
            EvaluatedPortfolio(
                portfolio=entry.portfolio,
                feasibility=entry.feasibility,
                evaluation=(
                    evaluator.evaluate(entry, baseline, demand, profile)
                    if entry.assignment is not None
                    else None
                ),
            )
            for entry in assigned
        ],
    )


def analyze(
    catalog: Catalog, profile: UserProfile, scenario: Scenario | None = None
) -> AnalysisResult:
    """The whole analysis of a household: what `POST /api/analyze` returns. Deterministic, and
    free of any HTTP or UI logic, so MobiMix City can call it on synthetic households.

    With a scenario, the analysis of the household under those assumptions (`POST /api/scenario`);
    a neutral scenario is the analysis itself."""
    if scenario is not None and scenario.is_neutral:
        scenario = None
    if scenario is not None:
        catalog, profile = apply_scenario(catalog, profile, scenario)
    demand, current_cost, evaluated = evaluated_portfolios(catalog, profile)
    recommendations = RuleBasedRecommendationEngine(catalog).recommend(
        evaluated, demand, current_cost, profile
    )
    feasible = [entry for entry in evaluated if entry.evaluation is not None]
    return AnalysisResult(
        profile_id=profile.id,
        scenario=scenario,
        parameters_version=catalog.version,
        demand=demand,
        portfolios=[entry.portfolio for entry in feasible],
        current=feasible[0].evaluation,  # type: ignore[arg-type]
        evaluations=[entry.evaluation for entry in feasible[1:]],  # type: ignore[misc]
        rejected=[
            RejectedPortfolio(
                portfolio_id=entry.portfolio.id,
                name=entry.portfolio.name,
                description=entry.portfolio.description,
                issues=[
                    issue
                    for issue in entry.feasibility.issues
                    if issue.severity is Severity.BLOCKING
                ],
            )
            for entry in evaluated
            if entry.evaluation is None
        ],
        recommendations=recommendations,
    )
