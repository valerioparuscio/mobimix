"""Controlled generation of plausible candidate portfolios (step 7, CLAUDE.md section 20).

Not an enumeration of every combination: a short list of setups a household could really
adopt, built from three independent choices that are all editable in data/portfolio_rules.yaml.

    1. FLEET     how many of its cars the household keeps (every subset size, from all to none),
                 or, if it owns none, buying one;
    2. ADD-ON    one set from the rules: nothing more, no transit passes, transit passes,
                 an e-bike, a scooter, passes + e-bike;
    3. SERVICES  the same layer of pay-per-use services, available to every candidate.

The generator proposes; it does not judge. A candidate that cannot serve the household's needs
is still produced and is rejected by the feasibility check (step 8), as CLAUDE.md section 6
requires: nothing is ranked before feasibility, and nothing is hidden before it either.

What is kept and what is new
----------------------------
Anything the household owns today and the candidate keeps carries its `profile_ref`, so the
evaluator can price it as the asset already owned (declared km, parking, current value). A new
item has no `profile_ref` and is priced as a purchase. `Portfolio.changes` lists the vehicles
and subscriptions that go and come, which is what the change penalty (step 11) prices.

Plausibility only
-----------------
The generator checks only what is structural: the option exists in the area, someone is
old enough for a discounted pass, someone can ride a bicycle, someone holds a licence. Whether
a bicycle can cover a 30 km commute is not its business.

Known limits (documented in docs/methodology.md, section 15)
-----------------------------------------------------------
No second-car purchase for a household that owns one, no replacement of a car by another model
(an electric one, say), no monthly passes, no sale of a motorcycle, bicycle or scooter already
owned. One candidate per distinct set of cars kept: two identical cars are one candidate.
"""

from dataclasses import dataclass
from itertools import combinations

from app.data.loader import Catalog
from app.models import (
    AccessibilityConstraint,
    Addon,
    AddonSet,
    ChangeKind,
    FleetScope,
    HeldSubscription,
    MobilityDemand,
    MobilityOption,
    Mode,
    OptionType,
    OwnedVehicle,
    Ownership,
    Person,
    Portfolio,
    PortfolioChange,
    PortfolioItem,
    PortfolioOrigin,
    Purpose,
    UserProfile,
)
from app.services.portfolios.labels import describe_changes, portfolio_label
from app.services.portfolios.service_layer import service_items

_TRANSIT_TYPES = (OptionType.PT_ANNUAL, OptionType.PT_MONTHLY, OptionType.RAIL_SUBSCRIPTION)
_COMMUTE_PURPOSES = (Purpose.COMMUTE, Purpose.STUDY)

# Hashable summary of a setup: (option, holder, profile_ref) of each vehicle and subscription.
SetupKey = frozenset[tuple[str, str | None, str | None]]


@dataclass(frozen=True)
class _Fleet:
    id: str
    kept: tuple[OwnedVehicle, ...]
    bought: str | None = None  # catalogue option of a car to buy

    @property
    def has_cars(self) -> bool:
        return bool(self.kept) or self.bought is not None


class RuleBasedPortfolioGenerator:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def generate(self, profile: UserProfile, demand: MobilityDemand) -> list[Portfolio]:
        """Candidates other than the current setup, in a stable order: the current number of
        cars first, then fewer. The profile must refer to catalogue options only (the demand
        estimator, which runs first, rejects any other)."""
        return _Generation(self._catalog, profile, demand).run()


class _Generation:
    def __init__(self, catalog: Catalog, profile: UserProfile, demand: MobilityDemand) -> None:
        self.catalog = catalog
        self.profile = profile
        self.demand = demand
        self.rules = catalog.portfolio_rules
        self.area = profile.household.location.area_type
        self.adults = profile.household.adults

        self.cars = [v for v in profile.vehicles if self._is_car(v.option_id)]
        self.other_vehicles = [v for v in profile.vehicles if not self._is_car(v.option_id)]
        self.transit = [s for s in profile.subscriptions if self._is_transit(s.option_id)]
        self.other_subscriptions = [
            s for s in profile.subscriptions if not self._is_transit(s.option_id)
        ]

    # --- classification --------------------------------------------------------------------

    def _is_car(self, option_id: str) -> bool:
        return self.catalog.option(option_id).mode is Mode.CAR

    def _is_transit(self, option_id: str) -> bool:
        return self.catalog.option(option_id).type in _TRANSIT_TYPES

    # --- main loop -------------------------------------------------------------------------

    def run(self) -> list[Portfolio]:
        seen = {self._key(self._current_setup())}  # a candidate equal to today's setup is not one
        candidates: list[Portfolio] = []
        for fleet in self._fleets():
            scope = FleetScope.WITH_CARS if fleet.has_cars else FleetScope.CAR_FREE
            for addon_set in self.rules.addon_sets:
                if scope not in addon_set.applies_to:
                    continue
                setup = self._setup(fleet, addon_set)
                if setup is None:
                    continue
                key = self._key(setup)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(self._portfolio(fleet, addon_set, setup))
        return candidates

    @staticmethod
    def _key(setup: list[PortfolioItem]) -> SetupKey:
        return frozenset((item.option_id, item.holder_id, item.profile_ref) for item in setup)

    # --- fleets ----------------------------------------------------------------------------

    def _fleets(self) -> list[_Fleet]:
        fleets = []
        for size in range(len(self.cars), -1, -1):
            seen_models: set[tuple[str, ...]] = set()
            for kept in combinations(self.cars, size):
                models = tuple(sorted(vehicle.option_id for vehicle in kept))
                if models in seen_models:
                    continue  # same cars kept, whichever of two identical ones is sold
                seen_models.add(models)
                name = "-".join(vehicle.id for vehicle in kept)
                fleets.append(_Fleet(id=f"keep-{name}" if kept else "car-free", kept=kept))

        if not self.cars and any(person.has_license for person in self.adults):
            option_id = self._new_car()
            fleets.append(_Fleet(id=f"buy-{option_id}", kept=(), bought=option_id))
        return fleets

    def _new_car(self) -> str:
        """The car bought by a household that has none: a family car if there are children or
        three or more adults, a compact one otherwise."""
        vehicles = self.rules.new_vehicles
        household = self.profile.household
        family = household.n_children > 0 or household.n_adults >= 3
        return vehicles.car_family if family else vehicles.car_compact

    # --- one candidate ---------------------------------------------------------------------

    def _current_setup(self) -> list[PortfolioItem]:
        return [
            *self._vehicle_items(self.cars),
            *self._vehicle_items(self.other_vehicles),
            *self._subscription_items(self.transit),
            *self._subscription_items(self.other_subscriptions),
        ]

    def _setup(self, fleet: _Fleet, addon_set: AddonSet) -> list[PortfolioItem] | None:
        """Vehicles and subscriptions of a candidate, or None if an add-on cannot be applied."""
        addons = set(addon_set.addons)
        items = self._vehicle_items(fleet.kept)
        if fleet.bought is not None:
            items.append(PortfolioItem(option_id=fleet.bought))
        items += self._vehicle_items(self.other_vehicles)
        items += self._subscription_items(self.other_subscriptions)

        kept_transit = [] if Addon.DROP_TRANSIT in addons else self.transit
        items += self._subscription_items(kept_transit)

        if Addon.PT in addons:
            new_passes = self._missing_passes(kept_transit)
            if not kept_transit and not new_passes:
                return None  # no pass can be held in this area
            items += new_passes

        if Addon.E_BIKE in addons:
            e_bike = self._added_vehicle(
                self.rules.new_vehicles.e_bike,
                owned=self._owns_e_bike(),
                possible=self._can_cycle(),
            )
            if e_bike is None:
                return None
            items += e_bike

        if Addon.SCOOTER in addons:
            scooter = self._added_vehicle(
                self.rules.new_vehicles.scooter,
                owned=self._owns_powered_two_wheeler(),
                possible=any(person.has_license for person in self.adults),
            )
            if scooter is None:
                return None
            items += scooter
        return items

    @staticmethod
    def _vehicle_items(vehicles) -> list[PortfolioItem]:
        return [
            PortfolioItem(
                option_id=vehicle.option_id,
                holder_id=vehicle.primary_user_id,
                profile_ref=vehicle.id,
            )
            for vehicle in vehicles
        ]

    @staticmethod
    def _subscription_items(subscriptions: list[HeldSubscription]) -> list[PortfolioItem]:
        return [
            PortfolioItem(
                option_id=subscription.option_id,
                holder_id=subscription.holder_id,
                profile_ref=subscription.id,
            )
            for subscription in subscriptions
        ]

    def _portfolio(
        self, fleet: _Fleet, addon_set: AddonSet, setup: list[PortfolioItem]
    ) -> Portfolio:
        changes = self._changes(setup)
        return Portfolio(
            id=f"{fleet.id}+{addon_set.id}",
            name=portfolio_label(setup, self.catalog),
            origin=PortfolioOrigin.GENERATED,
            items=[*setup, *self._services()],
            generation_rule=f"fleet={fleet.id}; addons={addon_set.id}",
            description=describe_changes(changes, self.catalog),
            changes=changes,
        )

    # --- add-ons ---------------------------------------------------------------------------

    def _owns_e_bike(self) -> bool:
        return any(
            self.catalog.option(vehicle.option_id).type is OptionType.E_BIKE
            for vehicle in self.other_vehicles
        )

    def _owns_powered_two_wheeler(self) -> bool:
        return any(
            self.catalog.option(vehicle.option_id).mode is Mode.MOTORCYCLE
            for vehicle in self.other_vehicles
        )

    def _can_cycle(self) -> bool:
        return any(
            AccessibilityConstraint.CANNOT_CYCLE not in person.accessibility_constraints
            for person in self.adults
        )

    @staticmethod
    def _added_vehicle(
        option_id: str, *, owned: bool, possible: bool
    ) -> list[PortfolioItem] | None:
        """The vehicle an add-on brings: nothing new if one is owned already, None if nobody
        in the household could use it. Bought for the household, not for a person."""
        if owned:
            return []
        return [PortfolioItem(option_id=option_id)] if possible else None

    def _missing_passes(self, kept: list[HeldSubscription]) -> list[PortfolioItem]:
        """A pass for each person who commutes and holds none (everyone, if nobody commutes)."""
        covered = {subscription.holder_id for subscription in kept}
        passes = []
        for person in self._pass_candidates():
            if person.id in covered:
                continue
            option = self._cheapest_pass(person)
            if option is not None:
                passes.append(PortfolioItem(option_id=option.id, holder_id=person.id))
        return passes

    def _pass_candidates(self) -> list[Person]:
        commuters = {
            mission.person_id
            for mission in self.demand.missions
            if mission.purpose in _COMMUTE_PURPOSES and mission.occurrences_per_year.value > 0
        }
        selected = [person for person in self.adults if person.id in commuters]
        return selected or list(self.adults)

    def _cheapest_pass(self, person: Person) -> MobilityOption | None:
        """The cheapest annual transit pass sold in the area that the person may buy.

        Monthly passes are not proposed (a candidate holds a pass all year); rail passes are
        only kept when already held."""
        options = [
            option
            for option in self.catalog.options.values()
            if option.type is OptionType.PT_ANNUAL
            and option.fixed_cost_year is not None
            and self.area in option.available_in_area_types
            and _may_buy(option, person)
        ]
        return min(options, key=lambda option: option.fixed_cost_year.value, default=None)

    # --- services --------------------------------------------------------------------------

    def _services(self) -> list[PortfolioItem]:
        """Pay-per-use services every candidate can use, then walking (service_layer.py)."""
        return service_items(self.catalog, self.area, self.demand)

    # --- changes ---------------------------------------------------------------------------

    def _changes(self, setup: list[PortfolioItem]) -> list[PortfolioChange]:
        kept = {item.profile_ref for item in setup if item.profile_ref is not None}
        changes = [
            PortfolioChange(
                kind=ChangeKind.SELL_VEHICLE,
                option_id=vehicle.option_id,
                holder_id=vehicle.primary_user_id,
                profile_ref=vehicle.id,
            )
            for vehicle in [*self.cars, *self.other_vehicles]
            if vehicle.id not in kept
        ]
        changes += [
            PortfolioChange(
                kind=ChangeKind.BUY_VEHICLE, option_id=item.option_id, holder_id=item.holder_id
            )
            for item in setup
            if item.profile_ref is None
            and self.catalog.option(item.option_id).ownership is Ownership.OWNED
        ]
        changes += [
            PortfolioChange(
                kind=ChangeKind.CANCEL_SUBSCRIPTION,
                option_id=subscription.option_id,
                holder_id=subscription.holder_id,
                profile_ref=subscription.id,
            )
            for subscription in [*self.transit, *self.other_subscriptions]
            if subscription.id not in kept
        ]
        changes += [
            PortfolioChange(
                kind=ChangeKind.START_SUBSCRIPTION,
                option_id=item.option_id,
                holder_id=item.holder_id,
            )
            for item in setup
            if item.profile_ref is None
            and self.catalog.option(item.option_id).ownership is Ownership.SUBSCRIPTION
        ]
        return changes


def _may_buy(option: MobilityOption, person: Person) -> bool:
    """Whether the whole age band of the person satisfies the age limits of a discounted pass.
    Unknown age only qualifies for passes without limits: no discount is assumed."""
    if option.min_age is None and option.max_age is None:
        return True
    if person.age_range is None:
        return False
    youngest, oldest = person.age_range.bounds
    return (option.min_age is None or youngest >= option.min_age) and (
        option.max_age is None or oldest <= option.max_age
    )
