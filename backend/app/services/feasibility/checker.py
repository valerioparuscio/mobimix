"""Rule-based feasibility check (step 8, CLAUDE.md section 6): can this portfolio serve the
household's needs at all? It runs before any ranking, and rejects with a reason.

For each mission, an option of the portfolio can serve it if ALL of these hold:

    distance     the one-way leg is within the option's practical range (min and max);
    traveller    whoever travels may use it: licence for a car, scooter, rental or car sharing
                 (the traveller of a personal mission, any adult for a household one); a pass
                 held by someone else is not usable; no accessibility exclusion; no children on
                 a scooter; the mode is in service at the hour the mission starts;
    capacity     owned vehicles of the mode have seats for everybody (pay-per-use services are
                 taken as available in as many units as needed: two taxis, two rental cars);
    luggage      the luggage space is within `feasibility.luggage_tolerance_levels` of the need;
    regularity   a mission done `feasibility.regular_min_occurrences_per_year` times or more is
                 not served by means meant for the occasional trip (taxi, rental, flights).

A mission nothing serves blocks the portfolio, unless it is rare (a warning only). Then the
household-level rule: if two members need a car at the same time on some days and the
portfolio has fewer than two cars, a car-like service (car sharing, rental, taxi) must be able
to cover those days - a regular one, if they are many.

Not modelled: who drives whom (a person without a licence being driven by another), the fact
that a single car cannot be in two places at once beyond the simultaneity answer, the quality
of public transport (frequency, waiting) and whether the traveller can really park. Thresholds
are in data/model_parameters.yaml (feasibility.*), tables in data/feasibility_rules.yaml.
"""

from collections import Counter
from enum import StrEnum

from app.data.loader import Catalog
from app.models import (
    Estimated,
    FeasibilityIssue,
    FeasibilityIssueCode,
    FeasibilityResult,
    LuggageLevel,
    MobilityDemand,
    MobilityMission,
    MobilityOption,
    Mode,
    Ownership,
    Person,
    Portfolio,
    PortfolioItem,
    Severity,
    UserProfile,
)
from app.services.wording import PURPOSE_NAMES

_LUGGAGE_TEXT = {
    LuggageLevel.NONE: None,
    LuggageLevel.SMALL: "bagaglio piccolo",
    LuggageLevel.MEDIUM: "bagaglio medio",
    LuggageLevel.LARGE: "molti bagagli",
}


class _Rejection(StrEnum):
    """Why an option cannot serve a mission; the first rule that fails is the one recorded."""

    DISTANCE = "DISTANCE"
    NOT_HOLDER = "NOT_HOLDER"
    LICENCE = "LICENCE"
    CAPACITY = "CAPACITY"
    LUGGAGE = "LUGGAGE"
    CHILDREN = "CHILDREN"
    ACCESSIBILITY = "ACCESSIBILITY"
    SCHEDULE = "SCHEDULE"


_REJECTION_TEXT = {
    _Rejection.DISTANCE: "la distanza non è adatta ai mezzi disponibili",
    _Rejection.NOT_HOLDER: "l'abbonamento è intestato a un'altra persona",
    _Rejection.LICENCE: "serve la patente e chi viaggia non ce l'ha",
    _Rejection.CAPACITY: "i veicoli di proprietà non hanno abbastanza posti",
    _Rejection.LUGGAGE: "il bagaglio non ci sta",
    _Rejection.CHILDREN: "i mezzi disponibili non sono adatti ai bambini",
    _Rejection.ACCESSIBILITY: "i mezzi disponibili non sono compatibili con l'accessibilità",
    _Rejection.SCHEDULE: "il servizio non è attivo all'orario di partenza",
}


class RuleBasedFeasibilityChecker:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def check(
        self, portfolio: Portfolio, demand: MobilityDemand, profile: UserProfile
    ) -> FeasibilityResult:
        """The profile is needed, beside the demand, for licences and accessibility."""
        return _Check(self._catalog, portfolio, demand, profile).run()


class _Check:
    def __init__(
        self, catalog: Catalog, portfolio: Portfolio, demand: MobilityDemand, profile: UserProfile
    ) -> None:
        self.catalog = catalog
        self.portfolio = portfolio
        self.demand = demand
        self.rules = catalog.feasibility_rules
        self.regular_min = catalog.value("feasibility.regular_min_occurrences_per_year")
        self.rare_max = catalog.value("feasibility.rare_max_occurrences_per_year")
        self.luggage_tolerance = int(catalog.value("feasibility.luggage_tolerance_levels"))

        self.adults = {person.id: person for person in profile.household.adults}
        self.adult_numbers = {person.id: n for n, person in enumerate(profile.household.adults, 1)}
        self.entries = [(item, catalog.option(item.option_id)) for item in portfolio.items]
        self.seats = self._owned_seats()
        self.issues: list[FeasibilityIssue] = []

    def run(self) -> FeasibilityResult:
        options_by_mission = {}
        for mission in self.demand.missions:
            if mission.occurrences_per_year.value > 0:
                options_by_mission[mission.id] = self._serve(mission)
        self._check_simultaneous_car_need()
        return FeasibilityResult(
            portfolio_id=self.portfolio.id,
            is_feasible=not any(issue.severity is Severity.BLOCKING for issue in self.issues),
            options_by_mission=options_by_mission,
            issues=self.issues,
        )

    # --- one mission -----------------------------------------------------------------------

    def _serve(self, mission: MobilityMission) -> list[str]:
        """The options of the portfolio that can reasonably serve the mission."""
        usable: dict[str, MobilityOption] = {}
        rejections: Counter[_Rejection] = Counter()
        for item, option in self.entries:
            reason = self._rejection(mission, item, option)
            if reason is None:
                usable[option.id] = option
            else:
                rejections[reason] += 1

        times = mission.occurrences_per_year.value
        occasional_only = dict(usable)
        if times >= self.regular_min:
            usable = {
                option_id: option
                for option_id, option in usable.items()
                if option.type not in self.rules.occasional_only_types
            }
        if usable:
            return list(usable)

        if occasional_only:  # only means meant for the occasional trip, for a regular mission
            names = _list_names(list(occasional_only.values()))
            self._issue(
                mission,
                Severity.BLOCKING,
                FeasibilityIssueCode.NO_REGULAR_OPTION,
                f"Per {self._label(mission)} ({self._facts(mission)}), che fate circa "
                f"{times:g} volte l'anno, con questa configurazione ci sono solo {names}: "
                "mezzi pensati per l'uso occasionale, non una soluzione ragionevole per "
                "un'abitudine regolare.",
            )
        else:
            rare = times <= self.rare_max
            self._issue(
                mission,
                Severity.WARNING if rare else Severity.BLOCKING,
                FeasibilityIssueCode.NO_OPTION,
                "Con questa configurazione non c'è un modo ragionevole per "
                f"{self._label(mission)} ({self._facts(mission)}): {self._reasons(rejections)}."
                + (" Capita raramente: si potrebbe organizzare di volta in volta." if rare else ""),
            )
        return []

    def _rejection(
        self, mission: MobilityMission, item: PortfolioItem, option: MobilityOption
    ) -> _Rejection | None:
        distance = mission.distance_km_one_way.value
        longest, shortest = option.max_practical_distance_km, option.min_practical_distance_km
        if (longest and distance > longest.value) or (shortest and distance < shortest.value):
            return _Rejection.DISTANCE
        if (
            option.ownership is Ownership.SUBSCRIPTION
            and item.holder_id is not None
            and mission.person_id is not None
            and item.holder_id != mission.person_id
        ):
            return _Rejection.NOT_HOLDER
        if option.requires_license and not self._may_drive(mission):
            return _Rejection.LICENCE
        if option.ownership is Ownership.OWNED and self.seats[option.mode] < mission.passengers:
            return _Rejection.CAPACITY
        if option.luggage_capacity.rank + self.luggage_tolerance < mission.luggage.rank:
            return _Rejection.LUGGAGE
        if mission.children > 0 and option.mode in self.rules.modes_not_with_children:
            return _Rejection.CHILDREN
        if option.mode in self._excluded_modes(mission):
            return _Rejection.ACCESSIBILITY
        if mission.start_time_window in self.rules.unavailable_time_bands.get(option.mode, []):
            return _Rejection.SCHEDULE
        return None

    def _owned_seats(self) -> Counter[Mode]:
        seats: Counter[Mode] = Counter()
        for item, option in self.entries:
            if option.ownership is Ownership.OWNED and option.capacity:
                seats[option.mode] += option.capacity * item.quantity
        return seats

    def _travellers(self, mission: MobilityMission) -> list[Person]:
        """Who travels: the person of a personal mission, every adult for a household one."""
        person = self.adults.get(mission.person_id) if mission.person_id else None
        return [person] if person is not None else list(self.adults.values())

    def _may_drive(self, mission: MobilityMission) -> bool:
        travellers = self._travellers(mission)
        if mission.person_id in self.adults:
            return all(person.has_license for person in travellers)
        return any(person.has_license for person in travellers)  # someone drives for the rest

    def _excluded_modes(self, mission: MobilityMission) -> set[Mode]:
        constraints = set(mission.accessibility_requirements)
        for person in self._travellers(mission):
            constraints.update(person.accessibility_constraints)
        return {
            mode
            for constraint in constraints
            for mode in self.rules.accessibility_exclusions.get(constraint, [])
        }

    # --- household level -------------------------------------------------------------------

    def _check_simultaneous_car_need(self) -> None:
        need = self.demand.simultaneous_car_need_days
        if need is None or need.value <= 0:
            return
        cars = sum(
            item.quantity
            for item, option in self.entries
            if option.mode is Mode.CAR and option.ownership is Ownership.OWNED
        )
        if cars >= 2:
            return

        licensed = any(person.has_license for person in self.adults.values())
        substitutes = [
            option
            for _, option in self.entries
            if option.ownership is not Ownership.OWNED
            and option.mode in (Mode.CAR, Mode.TAXI)
            and (licensed or not option.requires_license)
        ]
        regular = [o for o in substitutes if o.type not in self.rules.occasional_only_types]
        days = need.value
        fleet = "non ha auto" if cars == 0 else "ha una sola auto"
        head = f"Servono due auto insieme per {self._days(need)}, e questa configurazione {fleet}"
        no_service = ": non c'è alcun servizio (car sharing, taxi, noleggio) che copra quei giorni."
        names = _list_names(substitutes)

        if days >= self.regular_min and not regular:
            blocking = True
            tail = (
                f": in quei giorni ci sarebbero solo {names}, mezzi pensati per l'uso "
                "occasionale che non bastano per un'esigenza così frequente."
                if substitutes
                else no_service
            )
        elif not substitutes:
            blocking = days > self.rare_max
            tail = no_service
        else:
            blocking = False
            tail = f": in quei giorni si dovrebbe ricorrere a {names}."
        self.issues.append(
            FeasibilityIssue(
                severity=Severity.BLOCKING if blocking else Severity.WARNING,
                code=FeasibilityIssueCode.SIMULTANEOUS_CAR_NEED,
                message=f"{head}{tail}",
            )
        )

    # --- wording ---------------------------------------------------------------------------

    def _issue(
        self,
        mission: MobilityMission,
        severity: Severity,
        code: FeasibilityIssueCode,
        message: str,
    ) -> None:
        self.issues.append(
            FeasibilityIssue(mission_id=mission.id, severity=severity, code=code, message=message)
        )

    def _label(self, mission: MobilityMission) -> str:
        label = PURPOSE_NAMES[mission.purpose]
        number = self.adult_numbers.get(mission.person_id) if mission.person_id else None
        return f"{label} (adulto {number})" if number else label

    @staticmethod
    def _facts(mission: MobilityMission) -> str:
        facts = [f"{mission.distance_km_one_way.value:g} km a tratta"]
        if mission.passengers > 1:
            facts.append(f"{mission.passengers} persone")
        if mission.children > 0:
            facts.append("bambini" if mission.children > 1 else "un bambino")
        luggage = _LUGGAGE_TEXT[mission.luggage]
        if luggage:
            facts.append(luggage)
        return ", ".join(facts)

    @staticmethod
    def _reasons(reasons: Counter[_Rejection]) -> str:
        if not reasons:
            return "nessun mezzo adatto nella configurazione"
        return "; ".join(_REJECTION_TEXT[reason] for reason, _ in reasons.most_common())

    @staticmethod
    def _days(need: Estimated) -> str:
        if need.high - need.low < 1:
            return f"circa {need.value:g} giorni l'anno"
        return f"circa {need.value:g} giorni l'anno (tra {need.low:g} e {need.high:g})"


def _list_names(options: list[MobilityOption]) -> str:
    """Option names for the middle of a sentence: 'taxi, noleggio auto (giornaliero)'."""
    names = sorted({option.name[:1].lower() + option.name[1:] for option in options})
    return ", ".join(names)
