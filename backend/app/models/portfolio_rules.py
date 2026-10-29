"""Rules of the candidate-portfolio generator (data/portfolio_rules.yaml).

The list of candidates is data, not code: which add-on sets are tried, which vehicle is bought
when the household has none, which pay-per-use services every candidate can use.
"""

from enum import StrEnum

from pydantic import Field, model_validator

from .base import DomainModel


class Addon(StrEnum):
    """A change to the household's holdings on top of its cars.

    A set with no add-on keeps everything else the household holds today (bicycles,
    subscriptions...), so each candidate changes as little as it needs to."""

    PT = "PT"  # a transit pass for each person who commutes (held passes are kept)
    DROP_TRANSIT = "DROP_TRANSIT"  # cancel the transit passes held today
    E_BIKE = "E_BIKE"
    SCOOTER = "SCOOTER"


class FleetScope(StrEnum):
    WITH_CARS = "WITH_CARS"  # the candidate has at least one car
    CAR_FREE = "CAR_FREE"


class AddonSet(DomainModel):
    id: str
    addons: list[Addon] = Field(default_factory=list)
    applies_to: list[FleetScope] = Field(min_length=1)


class NewVehicles(DomainModel):
    """Catalogue options bought when the household does not own one."""

    car_compact: str
    car_family: str
    e_bike: str
    scooter: str


class PortfolioRules(DomainModel):
    new_vehicles: NewVehicles
    service_layer: list[str]
    addon_sets: list[AddonSet] = Field(min_length=1)
    placeholder: bool = Field(
        default=False,
        description="True if the rules are a stand-in the developer has not reviewed.",
    )

    @model_validator(mode="after")
    def _unique_set_ids(self) -> "PortfolioRules":
        ids = [addon_set.id for addon_set in self.addon_sets]
        if len(ids) != len(set(ids)):
            raise ValueError("addon_sets: duplicate ids")
        return self
