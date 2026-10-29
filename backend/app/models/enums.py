"""Controlled vocabularies shared across the domain model.

All enums are `StrEnum`: they serialise to their name in JSON/YAML, which keeps the
data files and the API readable.
"""

from enum import StrEnum


class Purpose(StrEnum):
    """Why a mobility need exists (brief section 10)."""

    COMMUTE = "COMMUTE"
    STUDY = "STUDY"
    SCHOOL_ESCORT = "SCHOOL_ESCORT"
    SHOPPING = "SHOPPING"
    LOCAL_LEISURE = "LOCAL_LEISURE"
    WEEKEND = "WEEKEND"
    FAMILY_VISIT = "FAMILY_VISIT"
    HOLIDAY = "HOLIDAY"
    BUSINESS = "BUSINESS"
    LONG_DISTANCE = "LONG_DISTANCE"
    OTHER = "OTHER"


class Mode(StrEnum):
    """How a need is physically served. A mission is served by a mode; a mode is made
    available by one or more mobility options (an owned car, a car-sharing service...)."""

    WALK = "WALK"
    BICYCLE = "BICYCLE"
    E_BIKE = "E_BIKE"
    KICK_SCOOTER = "KICK_SCOOTER"
    MOTORCYCLE = "MOTORCYCLE"  # powered two-wheelers: scooters and motorcycles
    CAR = "CAR"
    PUBLIC_TRANSPORT = "PUBLIC_TRANSPORT"
    RAIL = "RAIL"
    TAXI = "TAXI"  # taxi and ride hailing
    AIR = "AIR"


class OptionType(StrEnum):
    """Catalogue categories (brief section 11)."""

    # owned assets
    CAR_SMALL_PETROL = "CAR_SMALL_PETROL"
    CAR_MEDIUM_PETROL = "CAR_MEDIUM_PETROL"
    CAR_DIESEL = "CAR_DIESEL"
    CAR_ELECTRIC = "CAR_ELECTRIC"
    MOTORCYCLE = "MOTORCYCLE"
    SCOOTER = "SCOOTER"
    BICYCLE = "BICYCLE"
    E_BIKE = "E_BIKE"
    # subscriptions
    PT_ANNUAL = "PT_ANNUAL"
    PT_MONTHLY = "PT_MONTHLY"
    RAIL_SUBSCRIPTION = "RAIL_SUBSCRIPTION"
    BIKE_SHARING_SUBSCRIPTION = "BIKE_SHARING_SUBSCRIPTION"
    CAR_SHARING_SUBSCRIPTION = "CAR_SHARING_SUBSCRIPTION"
    # pay-per-use
    PT_TICKET = "PT_TICKET"
    TAXI = "TAXI"
    RIDE_HAILING = "RIDE_HAILING"
    CAR_SHARING = "CAR_SHARING"
    BIKE_SHARING = "BIKE_SHARING"
    SCOOTER_SHARING = "SCOOTER_SHARING"
    CAR_RENTAL = "CAR_RENTAL"
    RAIL = "RAIL"
    AIR = "AIR"
    # free
    WALKING = "WALKING"


class Ownership(StrEnum):
    OWNED = "OWNED"
    SUBSCRIPTION = "SUBSCRIPTION"
    PAY_PER_USE = "PAY_PER_USE"
    FREE = "FREE"


class EnergyCarrier(StrEnum):
    PETROL = "PETROL"
    DIESEL = "DIESEL"
    ELECTRICITY = "ELECTRICITY"


class TripBand(StrEnum):
    """Coarse trip-length class used to look up speeds (one-way leg distance).

    The distance thresholds between bands are model parameters
    (`bands.urban_max_km`, `bands.regional_max_km` in data/model_parameters.yaml)."""

    URBAN = "URBAN"
    REGIONAL = "REGIONAL"
    LONG = "LONG"


class AreaType(StrEnum):
    """Coarse residential context. Deliberately coarse for privacy (brief section 37)."""

    CITY_CENTER = "CITY_CENTER"
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    PERIPHERAL = "PERIPHERAL"  # outer or rural areas with weak public transport


class Level(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LuggageLevel(StrEnum):
    NONE = "NONE"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"

    @property
    def rank(self) -> int:
        return _LUGGAGE_RANK[self]


_LUGGAGE_RANK = {
    LuggageLevel.NONE: 0,
    LuggageLevel.SMALL: 1,
    LuggageLevel.MEDIUM: 2,
    LuggageLevel.LARGE: 3,
}


class TimeBand(StrEnum):
    """When a mission typically starts. Used for simultaneity and service-hours checks."""

    EARLY_MORNING = "EARLY_MORNING"
    MORNING_PEAK = "MORNING_PEAK"
    MIDDAY = "MIDDAY"
    AFTERNOON = "AFTERNOON"
    EVENING_PEAK = "EVENING_PEAK"
    EVENING = "EVENING"
    NIGHT = "NIGHT"
    ANY = "ANY"


class Frequency(StrEnum):
    """Qualitative frequency, used for questions people can answer without numbers."""

    NEVER = "NEVER"
    RARELY = "RARELY"
    SOMETIMES = "SOMETIMES"
    OFTEN = "OFTEN"
    ALMOST_DAILY = "ALMOST_DAILY"


class ProfileMode(StrEnum):
    """The three usage modes that share one engine (brief section 5)."""

    QUICK = "QUICK"
    DETAILED = "DETAILED"
    RETROSPECTIVE = "RETROSPECTIVE"  # future


class AgeRange(StrEnum):
    A18_24 = "A18_24"
    A25_34 = "A25_34"
    A35_44 = "A35_44"
    A45_54 = "A45_54"
    A55_64 = "A55_64"
    A65_74 = "A65_74"
    A75_PLUS = "A75_PLUS"

    @property
    def bounds(self) -> tuple[int, int]:
        """Youngest and oldest age the band can hold (the last band is capped at 110)."""
        return _AGE_BOUNDS[self]


_AGE_BOUNDS = {
    AgeRange.A18_24: (18, 24),
    AgeRange.A25_34: (25, 34),
    AgeRange.A35_44: (35, 44),
    AgeRange.A45_54: (45, 54),
    AgeRange.A55_64: (55, 64),
    AgeRange.A65_74: (65, 74),
    AgeRange.A75_PLUS: (75, 110),
}


class Occupation(StrEnum):
    WORKER = "WORKER"
    STUDENT = "STUDENT"
    RETIRED = "RETIRED"
    OTHER = "OTHER"


class IncomeBand(StrEnum):
    """Ordinal household income / mobility-budget band. Optional input."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AccessibilityConstraint(StrEnum):
    REDUCED_MOBILITY = "REDUCED_MOBILITY"
    WHEELCHAIR = "WHEELCHAIR"
    CANNOT_CYCLE = "CANNOT_CYCLE"
    OTHER = "OTHER"


class FamilyLogistic(StrEnum):
    """Household constraints that make some modes impractical."""

    SCHOOL_ESCORT = "SCHOOL_ESCORT"
    CHILD_ACTIVITIES = "CHILD_ACTIVITIES"
    ELDERLY_CARE = "ELDERLY_CARE"
    WORK_EQUIPMENT = "WORK_EQUIPMENT"
    PETS = "PETS"
    OTHER = "OTHER"


class ServiceKind(StrEnum):
    """Pay-per-use services whose current usage the user declares. They are evidence of how
    needs are served today, not additional needs (that would double count)."""

    TAXI = "TAXI"
    CAR_SHARING = "CAR_SHARING"
    CAR_RENTAL = "CAR_RENTAL"
    RAIL = "RAIL"
    AIR = "AIR"
    MICRO_SHARING = "MICRO_SHARING"  # bike and kick-scooter sharing


class PassengerRule(StrEnum):
    """How many people travel together on a mission of a given kind."""

    ONE = "ONE"
    HOUSEHOLD = "HOUSEHOLD"  # all adults and children
    ADULT_PLUS_CHILDREN = "ADULT_PLUS_CHILDREN"
