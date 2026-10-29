"""Mode assignment (step 9, CLAUDE.md sections 21 and 30): given a portfolio that can serve the
household's needs, which of its options serves each mission, and how often.

The rule is the one a household follows, not a search for the best portfolio: it uses what it
has, choosing for every trip the means that is cheapest once time and comfort are priced in
(`GeneralizedCost`). It runs the same way on the current portfolio and on every candidate, so a
difference between two portfolios comes from the portfolios and not from how they were treated.

For each mission, over the options the feasibility check admitted:

1.  Within one mode the household uses the best way into it: the pass it holds, not the
    ticket; the car it owns, not car sharing; the car with room for the luggage, then the
    cheapest. Only the best option of each mode competes.
2.  Across modes the occurrences are shared out by a multinomial logit on the generalized cost:
        share(mode) ~ exp(-scale x (cost - lowest cost)),  scale = assignment.logit_scale_per_eur
    A hard minimum would put every trip on one means and flip it on a cost difference of a
    cent, which a recommendation cannot rest on; the logit spreads trips over near ties and
    still sends them all to a means that wins clearly.
3.  Two situations take a share of a mission's occurrences away from some options:
        bad weather  `assignment.bad_weather_share` x the mission's weather weight: means
                     exposed to the weather are not used (if another can serve the mission);
        car busy     with a single car and `simultaneous_car_need_days` = D, the car cannot
                     serve the personal missions of the household's other members on D of their
                     occurrences: the car goes to its main user, the others use something else.
    The mission is split into these slices, each assigned by steps 1-2; shares are summed.
4.  A vehicle for one rider (bicycle, e-bike, scooter, motorcycle) serves one person at a time:
    one that belongs to someone is used by them alone; a household's, by as many people as
    there are units - those who would ride it most. A person who holds a car uses their own.
5.  Shares below `assignment.min_share` are dropped and the rest renormalised.

Not modelled: who needs the household's vehicles at which hour (beyond the "car busy" days),
whether the traveller really parks or finds a car-sharing vehicle nearby, habits that make a
household use its car more than cost and time would suggest (the declared mileage is not used
to calibrate the choice), and tolls, which are not in the cost model.
"""

import math
from collections import defaultdict

from app.data.loader import Catalog
from app.models import (
    AllocationReason,
    CheckedPortfolio,
    MissionAllocation,
    MobilityDemand,
    MobilityMission,
    MobilityOption,
    Mode,
    ModeAssignment,
    Ownership,
    PortfolioItem,
    UserProfile,
)
from app.models.enums import Level
from app.services.costs.model import TcoCostModel
from app.services.optimizer.trips import GeneralizedCost, TripCalculator
from app.services.wording import PURPOSE_NAMES

# Owned vehicles with room for one rider (two for a motorcycle): used by one person at a time.
_PERSONAL_MODES = {Mode.BICYCLE, Mode.E_BIKE, Mode.MOTORCYCLE, Mode.KICK_SCOOTER}
_MAX_ROUNDS = 6  # each round only adds exclusions, so the loop ends; this is a safety net
_EPSILON = 1e-12

# When one option's share comes from several situations, the reason is the largest of them;
# on a tie the first in this list.
_REASON_ORDER = (
    AllocationReason.ONLY_OPTION,
    AllocationReason.BEST,
    AllocationReason.CAR_BUSY,
    AllocationReason.WEATHER,
    AllocationReason.ALTERNATIVE,
)


class GeneralizedCostAssigner:
    def __init__(self, catalog: Catalog, cost_model: TcoCostModel | None = None) -> None:
        self._catalog = catalog
        self._calculator = TripCalculator(catalog, cost_model)

    def assign(
        self, checked: CheckedPortfolio, demand: MobilityDemand, profile: UserProfile
    ) -> ModeAssignment:
        """`checked.feasibility.options_by_mission` says which options may serve each mission;
        the profile says who the household's adults are (licences, to find the car's driver)."""
        return _Assignment(self._catalog, self._calculator, checked, demand, profile).run()


class _Assignment:
    def __init__(
        self,
        catalog: Catalog,
        calculator: TripCalculator,
        checked: CheckedPortfolio,
        demand: MobilityDemand,
        profile: UserProfile,
    ) -> None:
        self.catalog = catalog
        self.calculator = calculator
        self.valuation = GeneralizedCost(catalog)
        self.portfolio = checked.portfolio
        self.feasible = checked.feasibility.options_by_mission
        self.profile = profile
        self.adults = profile.household.adults

        self.scale = catalog.value("assignment.logit_scale_per_eur")
        self.min_share = catalog.value("assignment.min_share")
        self.bad_weather = catalog.value("assignment.bad_weather_share")
        self.weather_factor = catalog.assignment_rules.weather_factor

        self.options: dict[str, MobilityOption] = {
            item.option_id: catalog.option(item.option_id) for item in self.portfolio.items
        }
        self.owned: dict[str, list[PortfolioItem]] = defaultdict(list)
        for item in self.portfolio.items:
            if self.options[item.option_id].ownership is Ownership.OWNED:
                self.owned[item.option_id].append(item)
        self.owned_cars = {
            option_id for option_id in self.owned if self.options[option_id].mode is Mode.CAR
        }
        self.exposed = {
            option_id
            for option_id, option in self.options.items()
            if option.weather_sensitivity is Level.HIGH
        }

        self.missions = [
            mission
            for mission in demand.missions
            if mission.occurrences_per_year.value > 0 and self.feasible.get(mission.id)
        ]
        self.unserved = [
            mission.id
            for mission in demand.missions
            if mission.occurrences_per_year.value > 0 and not self.feasible.get(mission.id)
        ]
        self.simultaneous_days = demand.simultaneous_car_need_days
        self.notes: dict[str, None] = {}  # an ordered set
        self.costs: dict[tuple[str, str], float] = {}

        self.excluded: set[tuple[str, str]] = set()  # (person, option) the person cannot use
        self.pools: dict[str, int] = {}  # one-rider vehicle -> units not reserved for anyone
        self._reserve_vehicles()
        self.busy = self._busy_shares()

    # --- the assignment --------------------------------------------------------------------

    def run(self) -> ModeAssignment:
        shares = self._allocate_all()
        for _ in range(_MAX_ROUNDS):
            if not self._share_pooled_vehicles(shares):
                break
            shares = self._allocate_all()

        allocations = [
            MissionAllocation(
                mission_id=mission.id, option_id=option_id, share=share, reason=reason
            )
            for mission in self.missions
            for option_id, share, reason in shares[mission.id]
        ]
        return ModeAssignment(
            portfolio_id=self.portfolio.id,
            allocations=allocations,
            unserved_mission_ids=self.unserved,
            notes=list(self.notes),
        )

    def _allocate_all(self) -> dict[str, list[tuple[str, float, AllocationReason]]]:
        return {mission.id: self._allocate(mission) for mission in self.missions}

    def _allocate(self, mission: MobilityMission) -> list[tuple[str, float, AllocationReason]]:
        feasible = list(self.feasible[mission.id])
        usable = [o for o in feasible if (mission.person_id, o) not in self.excluded]
        if not usable:
            self._note(
                f"Per {self._label(mission)} tutti i mezzi ammessi sono riservati ad altre "
                "persone della famiglia: li abbiamo considerati comunque."
            )
            usable = feasible
        only_option = len(usable) == 1

        weather_share = self.bad_weather * self.weather_factor[mission.weather_sensitivity]
        busy_share = self.busy.get(mission.id, 0.0)
        contributions: dict[tuple[str, AllocationReason], float] = defaultdict(float)
        for bad_weather, weather_weight in ((False, 1 - weather_share), (True, weather_share)):
            for car_busy, car_weight in ((False, 1 - busy_share), (True, busy_share)):
                weight = weather_weight * car_weight
                if weight <= _EPSILON:
                    continue
                allowed, weather_applied, busy_applied = self._allowed(
                    mission, usable, bad_weather, car_busy
                )
                shares = self._choose(mission, allowed)
                best = max(shares, key=lambda option_id: (shares[option_id], option_id))
                for option_id, share in shares.items():
                    if only_option:
                        reason = AllocationReason.ONLY_OPTION
                    elif busy_applied:
                        reason = AllocationReason.CAR_BUSY
                    elif weather_applied:
                        reason = AllocationReason.WEATHER
                    else:
                        reason = (
                            AllocationReason.BEST
                            if option_id == best
                            else AllocationReason.ALTERNATIVE
                        )
                    contributions[(option_id, reason)] += weight * share
        return self._merge(contributions)

    def _allowed(
        self, mission: MobilityMission, usable: list[str], bad_weather: bool, car_busy: bool
    ) -> tuple[list[str], bool, bool]:
        """The options open in one slice, and whether the slice really differs from an ordinary
        day (nothing to take away, or nothing to replace it with, makes it an ordinary day)."""
        allowed = usable
        busy_applied = False
        if car_busy:
            without_cars = [o for o in allowed if o not in self.owned_cars]
            if without_cars and len(without_cars) < len(allowed):
                allowed, busy_applied = without_cars, True
            elif not without_cars:
                self._note(
                    f"Per {self._label(mission)} l'unica auto è anche l'unico mezzo possibile: "
                    "non siamo riusciti a toglierla nei giorni in cui serve a un'altra persona."
                )
        weather_applied = False
        if bad_weather:
            sheltered = [o for o in allowed if o not in self.exposed]
            if sheltered and len(sheltered) < len(allowed):
                allowed, weather_applied = sheltered, True
        return allowed, weather_applied, busy_applied

    def _choose(self, mission: MobilityMission, allowed: list[str]) -> dict[str, float]:
        """Shares among the options of one slice: the best option of each mode, then logit.

        Within a mode, an option with room for the luggage beats one that only passes the
        feasibility check thanks to its tolerance, whatever it costs: a household with a small
        and a large car takes the large one on holiday. Then the cheapest."""
        best: dict[Mode, tuple[tuple[int, float, str], float]] = {}
        for option_id in sorted(allowed):
            option = self.options[option_id]
            cost = self._cost(mission, option_id)
            shortfall = max(0, mission.luggage.rank - option.luggage_capacity.rank)
            rank = (shortfall, cost, option_id)
            if option.mode not in best or rank < best[option.mode][0]:
                best[option.mode] = (rank, cost)
        lowest = min(cost for _, cost in best.values())
        weights = {rank[2]: math.exp(-self.scale * (cost - lowest)) for rank, cost in best.values()}
        total = sum(weights.values())
        return {option_id: weight / total for option_id, weight in weights.items()}

    def _cost(self, mission: MobilityMission, option_id: str) -> float:
        key = (mission.id, option_id)
        if key not in self.costs:
            trip = self.calculator.trip(mission, self.options[option_id])
            self.costs[key] = self.valuation.of(trip)
        return self.costs[key]

    def _merge(
        self, contributions: dict[tuple[str, AllocationReason], float]
    ) -> list[tuple[str, float, AllocationReason]]:
        """One entry per option; the reason is the one that brings most of its share. Small
        shares are dropped and the rest renormalised."""
        by_option: dict[str, dict[AllocationReason, float]] = defaultdict(dict)
        for (option_id, reason), share in contributions.items():
            by_option[option_id][reason] = share
        totals = {option_id: sum(reasons.values()) for option_id, reasons in by_option.items()}
        kept = {o: t for o, t in totals.items() if t >= self.min_share} or totals
        scale = sum(kept.values())
        merged = []
        for option_id in sorted(kept, key=lambda o: (-kept[o], o)):
            reasons = by_option[option_id]
            reason = max(reasons, key=lambda r: (round(reasons[r], 9), -_REASON_ORDER.index(r)))
            merged.append((option_id, min(1.0, kept[option_id] / scale), reason))
        return merged

    # --- vehicles shared by several people -------------------------------------------------

    def _reserve_vehicles(self) -> None:
        """Who may use the household's vehicles for their personal missions."""
        people = {m.person_id for m in self.missions if m.person_id is not None}
        car_holders = {
            item.holder_id
            for option_id in self.owned_cars
            for item in self.owned[option_id]
            if item.holder_id is not None
        }
        for option_id, items in self.owned.items():
            holders = {item.holder_id for item in items if item.holder_id is not None}
            shared = sum(item.quantity for item in items if item.holder_id is None)
            mode = self.options[option_id].mode
            if mode is Mode.CAR:
                # whoever holds a car uses their own; whoever holds none, any
                for person in people & car_holders:
                    if person not in holders and not shared:
                        self.excluded.add((person, option_id))
            elif mode in _PERSONAL_MODES:
                if shared:
                    self.pools[option_id] = shared  # shared out later, by use
                else:
                    self.excluded.update((person, option_id) for person in people - holders)

    def _share_pooled_vehicles(
        self, shares: dict[str, list[tuple[str, float, AllocationReason]]]
    ) -> bool:
        """A household's bicycle serves as many people as there are bicycles. When more would
        use it, it goes to those who would ride it most. Returns whether anything changed."""
        changed = False
        for option_id, units in self.pools.items():
            reserved = {i.holder_id for i in self.owned[option_id] if i.holder_id is not None}
            km_by_person: dict[str, float] = defaultdict(float)
            for mission in self.missions:
                person = mission.person_id
                if person is None or person in reserved:
                    continue
                share = next((s for o, s, _ in shares[mission.id] if o == option_id), 0.0)
                km_by_person[person] += share * mission.annual_km
            users = sorted(km_by_person, key=lambda p: (-km_by_person[p], p))
            users = [person for person in users if km_by_person[person] > _EPSILON]
            if len(users) <= units:
                continue
            for loser in users[units:]:
                self.excluded.add((loser, option_id))
            changed = True
            winners = ", ".join(self._person(p) for p in users[:units])
            self._note(
                f"«{self.options[option_id].name}» è uno solo e non può servire più persone "
                f"insieme: lo usa chi lo userebbe di più ({winners})."
            )
        return changed

    # --- the car that two people need --------------------------------------------------------

    def _busy_shares(self) -> dict[str, float]:
        """With a single car, the share of each other member's personal occurrences on which the
        car is not theirs: the days two members need a car at once, spread over those missions."""
        cars = [item for option_id in self.owned_cars for item in self.owned[option_id]]
        need = self.simultaneous_days
        if sum(item.quantity for item in cars) != 1 or need is None or need.value <= 0:
            return {}
        driver = cars[0].holder_id or next(
            (person.id for person in self.adults if person.has_license), None
        )
        contested = [
            mission
            for mission in self.missions
            if mission.person_id not in (None, driver)
            and any(o in self.owned_cars for o in self.feasible[mission.id])
        ]
        occurrences = sum(m.occurrences_per_year.value for m in contested)
        if occurrences <= _EPSILON:
            self._note(
                f"Servono due auto insieme per circa {need.value:g} giorni l'anno, ma nessuno "
                "spostamento personale degli altri componenti usa l'auto: non abbiamo da dove "
                "toglierla."
            )
            return {}
        return {m.id: min(1.0, need.value / occurrences) for m in contested}

    # --- wording ---------------------------------------------------------------------------

    def _note(self, message: str) -> None:
        self.notes[message] = None

    def _person(self, person_id: str) -> str:
        numbers = {person.id: n for n, person in enumerate(self.adults, 1)}
        return f"adulto {numbers[person_id]}" if person_id in numbers else person_id

    def _label(self, mission: MobilityMission) -> str:
        who = f" ({self._person(mission.person_id)})" if mission.person_id else ""
        return f"{PURPOSE_NAMES[mission.purpose]}{who}"
