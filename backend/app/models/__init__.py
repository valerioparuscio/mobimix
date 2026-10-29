"""Domain models. Kept separate from frontend form models (brief section 41)."""
# ruff: noqa: F401  (this module only re-exports)

from .assignment_rules import AssignmentRules
from .base import DomainModel
from .defaults import AreaDefaults
from .demand import EstimationNote, MobilityDemand, MobilityMission, ServiceUsage
from .enums import (
    AccessibilityConstraint,
    AgeRange,
    AreaType,
    EnergyCarrier,
    FamilyLogistic,
    Frequency,
    IncomeBand,
    Level,
    LuggageLevel,
    Mode,
    Occupation,
    OptionType,
    Ownership,
    PassengerRule,
    ProfileMode,
    Purpose,
    ServiceKind,
    TimeBand,
    TripBand,
)
from .evaluation import (
    AccuracyHint,
    AllocationReason,
    AssignedPortfolio,
    CarKmCheck,
    CheckedPortfolio,
    CostCategory,
    CostLine,
    CostResult,
    CurrentCostResult,
    EvaluatedPortfolio,
    FeasibilityIssue,
    FeasibilityIssueCode,
    FeasibilityResult,
    ItemCost,
    ItemUsage,
    MissionAllocation,
    ModeAssignment,
    OptionUsage,
    PortfolioCost,
    PortfolioDelta,
    PortfolioEvaluation,
    Severity,
)
from .feasibility_rules import FeasibilityRules
from .options import Emissions, EnergyUse, MobilityOption, OptionScores
from .portfolio import ChangeKind, Portfolio, PortfolioChange, PortfolioItem, PortfolioOrigin
from .portfolio_rules import Addon, AddonSet, FleetScope, NewVehicles, PortfolioRules
from .profile import (
    HeldSubscription,
    Household,
    Location,
    OtherMobility,
    OwnedVehicle,
    Person,
    Preferences,
    UserProfile,
    WorkPattern,
)
from .provenance import (
    Confidence,
    DataSourceMetadata,
    Estimated,
    ModelParameter,
    NumericAnswer,
    Param,
    ParameterValue,
    Range,
    ValueSource,
)
from .questionnaire import Band, BandGroup, QuestionnaireConfig
from .recommendation import (
    AnalysisResult,
    ExplanationFact,
    Recommendation,
    RecommendationCategory,
    RecommendationRole,
    RecommendationSet,
    RecommendationStrength,
    RejectedPortfolio,
)
from .scenario import Scenario
from .templates import MissionTemplate
