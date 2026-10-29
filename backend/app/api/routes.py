from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.data.loader import Catalog, get_catalog, load_demo_households
from app.models import (
    AnalysisResult,
    AreaDefaults,
    AssignedPortfolio,
    CheckedPortfolio,
    CurrentCostResult,
    DataSourceMetadata,
    EvaluatedPortfolio,
    MobilityDemand,
    MobilityOption,
    ModelParameter,
    Portfolio,
    QuestionnaireConfig,
    Scenario,
    UserProfile,
)
from app.services.costs import CurrentCostEstimator
from app.services.demand import RuleBasedDemandEstimator, UnknownOptionError
from app.services.pipeline import (
    analyze,
    assigned_portfolios,
    checked_portfolios,
    evaluated_portfolios,
)
from app.services.portfolios import RuleBasedPortfolioGenerator

router = APIRouter(prefix="/api")


def catalog_dependency() -> Catalog:
    return get_catalog()


class ScenarioRequest(BaseModel):
    """A household and the what-if assumptions to analyse it under."""

    profile: UserProfile
    scenario: Scenario


class HealthStatus(BaseModel):
    status: str
    parameters_version: str
    n_options: int


class Assumptions(BaseModel):
    """Everything the methodology page needs to show: parameters, defaults and sources."""

    parameters_version: str
    parameters: list[ModelParameter]
    area_defaults: list[AreaDefaults]
    sources: list[DataSourceMetadata]


@router.get("/health", response_model=HealthStatus)
def health(catalog: Catalog = Depends(catalog_dependency)) -> HealthStatus:
    return HealthStatus(
        status="ok", parameters_version=catalog.version, n_options=len(catalog.options)
    )


@router.get("/reference/mobility-options", response_model=list[MobilityOption])
def mobility_options(catalog: Catalog = Depends(catalog_dependency)) -> list[MobilityOption]:
    return list(catalog.options.values())


@router.get("/reference/assumptions", response_model=Assumptions)
def assumptions(catalog: Catalog = Depends(catalog_dependency)) -> Assumptions:
    return Assumptions(
        parameters_version=catalog.version,
        parameters=list(catalog.parameters.values()),
        area_defaults=list(catalog.area_defaults.values()),
        sources=list(catalog.sources.values()),
    )


@router.get("/reference/questionnaire", response_model=QuestionnaireConfig)
def questionnaire(catalog: Catalog = Depends(catalog_dependency)) -> QuestionnaireConfig:
    """Answer bands of the numeric questions (exact value / band / "I don't know")."""
    return catalog.questionnaire


@router.get("/reference/demo-households", response_model=dict[str, UserProfile])
def demo_households(catalog: Catalog = Depends(catalog_dependency)) -> dict[str, UserProfile]:
    """Fixed demo profiles, to prefill the questionnaire during development."""
    return load_demo_households(catalog)


@router.post("/profile/estimate-demand", response_model=MobilityDemand)
def estimate_demand(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> MobilityDemand:
    """Annual mobility needs of the household, with the source and confidence of every number."""
    try:
        return RuleBasedDemandEstimator(catalog).estimate(profile)
    except UnknownOptionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/profile/current-cost", response_model=CurrentCostResult)
def current_cost(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> CurrentCostResult:
    """What the household's current mobility setup costs per year, with a range and a
    confidence, plus the inputs whose precision would narrow the range most."""
    try:
        demand = RuleBasedDemandEstimator(catalog).estimate(profile)
    except UnknownOptionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return CurrentCostEstimator(catalog).estimate(profile, demand)


@router.post("/portfolios/generate", response_model=list[Portfolio])
def generate_portfolios(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> list[Portfolio]:
    """Candidate portfolios to compare with the current setup (neither checked for feasibility
    nor priced: see /portfolios/feasibility). Each lists what the household would have to
    change."""
    try:
        demand = RuleBasedDemandEstimator(catalog).estimate(profile)
    except UnknownOptionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RuleBasedPortfolioGenerator(catalog).generate(profile, demand)


@router.post("/portfolios/feasibility", response_model=list[CheckedPortfolio])
def check_portfolios(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> list[CheckedPortfolio]:
    """The current setup first, then every candidate, each with the outcome of the feasibility
    check: which means serve each need, and what blocks the portfolio if anything does.
    Infeasible candidates are returned too, with the reason; steps 9-11 skip them."""
    return _run(checked_portfolios, catalog, profile)[2]


@router.post("/portfolios/assignment", response_model=list[AssignedPortfolio])
def assign_portfolios(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> list[AssignedPortfolio]:
    """The portfolios of /portfolios/feasibility, each feasible one with the means that serve
    each need and how often. The current setup is always assigned; a candidate rejected by the
    feasibility check is returned without an assignment."""
    return _run(assigned_portfolios, catalog, profile)[2]


@router.post("/portfolios/evaluate", response_model=list[EvaluatedPortfolio])
def evaluate_portfolios(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> list[EvaluatedPortfolio]:
    """The portfolios of /portfolios/assignment, each assigned one with its annual cost, travel
    time, comfort, car kilometres and CO2. The cost of the current setup is the declared one of
    /profile/current-cost; the others are that plus the differences the model finds."""
    return _run(evaluated_portfolios, catalog, profile)[2]


def _run(stage, catalog: Catalog, profile: UserProfile):
    try:
        return stage(catalog, profile)
    except UnknownOptionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analyze", response_model=AnalysisResult)
def analyze_profile(
    profile: UserProfile, catalog: Catalog = Depends(catalog_dependency)
) -> AnalysisResult:
    """The whole analysis: demand, current cost, feasible alternatives with cost, time and
    comfort, the rejected ones with the reason, and the recommendations with their explanation."""
    return _run(analyze, catalog, profile)


@router.post("/scenario", response_model=AnalysisResult)
def analyze_scenario(
    request: ScenarioRequest, catalog: Catalog = Depends(catalog_dependency)
) -> AnalysisResult:
    """The whole analysis of the household under what-if assumptions (fuel price, parking, days
    of remote work, kilometres, an e-bike incentive). Nothing is stored: the same profile and
    scenario always give the same answer."""
    return _run(lambda c, p: analyze(c, p, request.scenario), catalog, request.profile)
