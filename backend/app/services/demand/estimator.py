"""Rule-based demand estimator (step 5): UserProfile -> MobilityDemand.

Turns what the user said into annual mobility *needs* (missions), filling the gaps with
statistical defaults and tagging every number with its source and confidence.

Formulas (all constants come from data/, see docs/methodology.md):

    commute occurrences = physical days per week x weeks per year
        physical days   = days per week - remote days per week            (never below 0)
        weeks per year  = working days per year / 5      (school days / 5 for students)
    school escort       = school days per year            (x a default share if not declared)
    local trips         = trips per week x local weeks per year, split shopping / leisure
    weekend, long weekend, holiday = declared or default occurrences per year

Declared use of taxi, car sharing, rental, rail, flights is NOT added as demand (a taxi trip
serves a need already counted above); it is returned as `current_service_usage`.

Known limitations: business trips and family visits are not modelled separately; the age of
children is unknown, so school escort is approximate; declared car mileage is not yet used
to calibrate the missions (that happens when the current portfolio is costed, steps 6 and 9).
"""

from app.data.loader import Catalog
from app.models import (
    Confidence,
    Estimated,
    EstimationNote,
    FamilyLogistic,
    Frequency,
    Level,
    MobilityDemand,
    MobilityMission,
    Mode,
    NumericAnswer,
    Occupation,
    Ownership,
    ParameterValue,
    PassengerRule,
    Purpose,
    ServiceKind,
    ServiceUsage,
    UserProfile,
    ValueSource,
    WorkPattern,
)
from app.services.statistics.estimation import (
    AREA_NAMES,
    CONFIDENCE_WORDS,
    complement,
    divided,
    from_answer,
    from_parameter,
    minus_clipped,
    multiplied,
    scaled,
)

# The calendar parameters (working days, school days) are expressed for a five-day week.
DAYS_PER_WEEK = 5

# Assumed when the user does not say how many days they work remotely.
_NO_REMOTE_WORK = ParameterValue(
    value=0, confidence=Confidence.LOW, notes="Se non indicato, si assume nessun giorno da remoto."
)

_SERVICE_NAMES = {
    ServiceKind.TAXI: "taxi",
    ServiceKind.CAR_SHARING: "car sharing",
    ServiceKind.CAR_RENTAL: "noleggio auto",
    ServiceKind.RAIL: "treno",
    ServiceKind.AIR: "voli",
    ServiceKind.MICRO_SHARING: "bici e monopattini in sharing",
}
# service, OtherMobility attribute, default key in default_profiles.yaml, unit
_SERVICES: tuple[tuple[ServiceKind, str, str, str], ...] = (
    (ServiceKind.TAXI, "taxi_trips_per_year", "taxi_trips_per_year", "trips"),
    (ServiceKind.CAR_SHARING, "car_sharing_trips_per_year", "car_sharing_trips_per_year", "trips"),
    (ServiceKind.CAR_RENTAL, "car_rental_days_per_year", "car_rental_days_per_year", "days"),
    (ServiceKind.RAIL, "rail_trips_per_year", "rail_trips_per_year", "trips"),
    (ServiceKind.AIR, "flights_per_year", "flights_per_year", "trips"),
    (
        ServiceKind.MICRO_SHARING,
        "bike_scooter_sharing_trips_per_year",
        "bike_scooter_sharing_trips_per_year",
        "trips",
    ),
)


class UnknownOptionError(ValueError):
    """The profile refers to a vehicle or subscription that is not in the catalogue."""


class RuleBasedDemandEstimator:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    def estimate(self, profile: UserProfile) -> MobilityDemand:
        for item in [*profile.vehicles, *profile.subscriptions]:
            if item.option_id not in self._catalog.options:
                raise UnknownOptionError(f"opzione di mobilità sconosciuta: {item.option_id!r}")
        return _Estimation(self._catalog, profile).build()


class _Estimation:
    """One run of the estimator: holds the profile, the defaults and the notes collected."""

    def __init__(self, catalog: Catalog, profile: UserProfile) -> None:
        self.catalog = catalog
        self.profile = profile
        self.household = profile.household
        self.other = profile.other_mobility
        self.area = self.household.location.area_type
        self.defaults = catalog.defaults_for(self.area).values
        self.notes: list[EstimationNote] = []
        self.n_children = self.household.n_children
        self.household_size = self.household.n_adults + self.n_children

    # --- assembly ------------------------------------------------------------------------

    def build(self) -> MobilityDemand:
        missions = [
            *self._commutes(),
            *self._school_escort(),
            *self._local_trips(),
            *self._weekend_trips(),
            *self._long_weekends(),
            *self._holidays(),
        ]
        missions = self._apply_declared_missions(missions)
        return MobilityDemand(
            profile_id=self.profile.id,
            missions=missions,
            simultaneous_car_need_days=self._simultaneous_car_need(),
            current_service_usage=self._service_usage(),
            assumptions=self.notes,
        )

    # --- helpers -------------------------------------------------------------------------

    def _parameter(self, parameter_id: str) -> ParameterValue:
        return self.catalog.parameter(parameter_id)

    def _estimate(
        self,
        answer: NumericAnswer,
        fallback: ParameterValue,
        subject: str,
        field: str,
        message: str,
        fallback_source: ValueSource = ValueSource.STATISTICAL_ESTIMATE,
    ) -> Estimated:
        """The user's answer or the fallback; notes the fallback so it is never silent."""
        estimate = from_answer(answer, fallback, fallback_source)
        self._note(estimate, subject, field, message)
        return estimate

    def _note(self, estimate: Estimated, subject: str, field: str, message: str) -> None:
        if estimate.source not in (ValueSource.STATISTICAL_ESTIMATE, ValueSource.DEFAULT):
            return
        confidence = CONFIDENCE_WORDS[estimate.confidence]
        self.notes.append(
            EstimationNote(
                subject=subject,
                field=field,
                source=estimate.source,
                confidence=estimate.confidence,
                message=message.format(value=f"{estimate.value:g}", area=AREA_NAMES[self.area])
                + f" (affidabilità {confidence}).",
            )
        )

    def _passengers(self, rule: PassengerRule) -> tuple[int, int]:
        """(passengers, children among them)."""
        if rule is PassengerRule.HOUSEHOLD:
            return self.household_size, self.n_children
        if rule is PassengerRule.ADULT_PLUS_CHILDREN:
            return 1 + self.n_children, self.n_children
        return 1, 0

    def _mission(
        self,
        mission_id: str,
        purpose: Purpose,
        occurrences: Estimated,
        distance: Estimated,
        person_id: str | None = None,
        **overrides: object,
    ) -> MobilityMission:
        template = self.catalog.mission_templates[purpose]
        passengers, children = self._passengers(template.passengers)
        fields: dict[str, object] = {
            "legs_per_occurrence": template.legs_per_occurrence,
            "days_away": template.days_away.value if template.days_away else 0.0,
            "passengers": passengers,
            "children": children,
            "luggage": template.luggage,
            "time_critical": template.time_critical,
            "start_time_window": template.start_time_window,
            "duration_tolerance": template.duration_tolerance,
            "weather_sensitivity": template.weather_sensitivity,
        }
        fields.update(overrides)
        return MobilityMission(
            id=mission_id,
            person_id=person_id,
            purpose=purpose,
            occurrences_per_year=occurrences,
            distance_km_one_way=distance,
            **fields,
        )

    # --- missions ------------------------------------------------------------------------

    def _commutes(self) -> list[MobilityMission]:
        missions = []
        for index, person in enumerate(self.household.adults):
            if person.occupation not in (Occupation.WORKER, Occupation.STUDENT):
                continue
            who = f"Adulto {index + 1}"
            study = person.occupation is Occupation.STUDENT
            purpose = Purpose.STUDY if study else Purpose.COMMUTE
            place = "scuola o università" if study else "lavoro"
            work = person.work_or_study or WorkPattern()

            distance = self._estimate(
                work.one_way_distance_km,
                self.defaults["commute_distance_km_one_way"],
                person.id,
                "commute_distance_km",
                f"{who}: la distanza da casa a {place} non è stata indicata, usiamo "
                "{value} km, un valore tipico per {area}",
            )
            days = self._estimate(
                work.days_per_week,
                self.defaults["work_days_per_week"],
                person.id,
                "days_per_week",
                f"{who}: i giorni a settimana non sono stati indicati, usiamo {{value}}",
            )
            remote = self._estimate(
                work.remote_days_per_week,
                _NO_REMOTE_WORK,
                person.id,
                "remote_days_per_week",
                f"{who}: i giorni da remoto non sono stati indicati, assumiamo {{value}}",
                fallback_source=ValueSource.DEFAULT,
            )

            physical_days = minus_clipped(days, remote)
            if physical_days.value <= 0:
                continue  # works or studies entirely from home: no trips
            days_per_year = self._parameter(
                "calendar.school_days_per_year" if study else "calendar.working_days_per_year"
            )
            weeks = divided(days_per_year, DAYS_PER_WEEK)
            occurrences = scaled(physical_days, weeks)

            time_critical = work.time_critical
            missions.append(
                self._mission(
                    f"{purpose.value.lower()}_{person.id}",
                    purpose,
                    occurrences,
                    distance,
                    person_id=person.id,
                    time_critical=time_critical,
                    start_time_window=work.typical_start,
                    duration_tolerance=Level.LOW
                    if time_critical
                    else self.catalog.mission_templates[purpose].duration_tolerance,
                    accessibility_requirements=list(person.accessibility_constraints),
                )
            )
        return missions

    def _school_escort(self) -> list[MobilityMission]:
        if self.n_children == 0:
            return []
        school_days = self._parameter("calendar.school_days_per_year")
        if FamilyLogistic.SCHOOL_ESCORT in self.household.family_logistics:
            occurrences = from_parameter(school_days, ValueSource.INFERRED)
        else:
            share = self._parameter("demand.school_escort_default_share")
            occurrences = Estimated(
                value=school_days.value * share.value,
                low=school_days.lo * share.lo,
                high=school_days.hi * share.hi,
                source=ValueSource.DEFAULT,
                confidence=Confidence.LOW,
            )
            self.notes.append(
                EstimationNote(
                    subject="household",
                    field="school_escort",
                    source=ValueSource.DEFAULT,
                    confidence=Confidence.LOW,
                    message="Non sappiamo se accompagnate i figli a scuola: stimiamo "
                    f"{occurrences.value:g} giorni l'anno di accompagnamento, su circa "
                    f"{school_days.value:g} giorni di scuola (affidabilità bassa).",
                )
            )
        distance = self._estimate(
            NumericAnswer(),
            self.defaults["school_escort_distance_km_one_way"],
            "household",
            "school_escort_distance_km",
            "La distanza casa-scuola non è nota, usiamo {value} km, un valore tipico per {area}",
        )
        return [self._mission("school_escort", Purpose.SCHOOL_ESCORT, occurrences, distance)]

    def _local_trips(self) -> list[MobilityMission]:
        per_adult = self.defaults["local_trips_per_week_per_adult"]
        weekly = self._estimate(
            self.other.local_non_work_trips_per_week,
            multiplied(per_adult, self.household.n_adults),
            "household",
            "local_trips_per_week",
            "Gli spostamenti locali settimanali (spesa, commissioni, svago) non sono stati "
            "indicati: usiamo {value} a settimana, un valore tipico per {area}",
        )
        if weekly.value <= 0:
            return []
        total = scaled(weekly, self._parameter("calendar.local_trip_weeks_per_year"))
        shopping_share = self._parameter("demand.local_trips_shopping_share")
        distance = self._estimate(
            NumericAnswer(),
            self.defaults["local_trip_distance_km_one_way"],
            "household",
            "local_trip_distance_km",
            "La distanza tipica degli spostamenti locali non è nota, usiamo {value} km, "
            "un valore tipico per {area}",
        )
        return [
            self._mission("shopping", Purpose.SHOPPING, scaled(total, shopping_share), distance),
            self._mission(
                "local_leisure",
                Purpose.LOCAL_LEISURE,
                scaled(total, complement(shopping_share)),
                distance,
            ),
        ]

    def _weekend_trips(self) -> list[MobilityMission]:
        occurrences = self._estimate(
            self.other.weekend_trips_per_year,
            self.defaults["weekend_trips_per_year"],
            "household",
            "weekend_trips_per_year",
            "Le gite nel weekend non sono state indicate: stimiamo {value} l'anno, "
            "un valore tipico per {area}",
        )
        if occurrences.value <= 0:
            return []
        distance = self._estimate(
            self.other.weekend_trip_distance_km_one_way,
            self.defaults["weekend_trip_distance_km_one_way"],
            "household",
            "weekend_trip_distance_km",
            "La distanza delle gite nel weekend non è stata indicata: usiamo {value} km, "
            "un valore tipico per {area}",
        )
        return [self._mission("weekend", Purpose.WEEKEND, occurrences, distance)]

    def _long_weekends(self) -> list[MobilityMission]:
        occurrences = self._estimate(
            self.other.long_distance_weekends_per_year,
            self.defaults["long_weekends_per_year"],
            "household",
            "long_weekends_per_year",
            "I weekend lunghi non sono stati indicati: stimiamo {value} l'anno, "
            "un valore tipico per {area}",
        )
        if occurrences.value <= 0:
            return []
        distance = self._estimate(
            NumericAnswer(),
            self.defaults["long_weekend_distance_km_one_way"],
            "household",
            "long_weekend_distance_km",
            "La distanza dei weekend lunghi non è nota: usiamo {value} km, "
            "un valore tipico per {area}",
        )
        return [self._mission("long_weekend", Purpose.LONG_DISTANCE, occurrences, distance)]

    def _holidays(self) -> list[MobilityMission]:
        occurrences = self._estimate(
            self.other.holiday_trips_per_year,
            self.defaults["holiday_trips_per_year"],
            "household",
            "holiday_trips_per_year",
            "I viaggi di vacanza non sono stati indicati: stimiamo {value} l'anno, "
            "un valore tipico per {area}",
        )
        if occurrences.value <= 0:
            return []
        distance = self._estimate(
            self.other.holiday_distance_km_one_way,
            self.defaults["holiday_distance_km_one_way"],
            "household",
            "holiday_distance_km",
            "La distanza delle vacanze non è stata indicata: usiamo {value} km, "
            "un valore tipico per {area}",
        )
        return [self._mission("holiday", Purpose.HOLIDAY, occurrences, distance)]

    def _apply_declared_missions(self, estimated: list[MobilityMission]) -> list[MobilityMission]:
        """Detailed mode: declared missions replace the estimates for the same purpose."""
        declared = self.profile.declared_missions
        if not declared:
            return estimated
        replaced = {mission.purpose for mission in declared}
        for purpose in sorted(replaced):
            self.notes.append(
                EstimationNote(
                    subject="household",
                    field=f"declared_missions.{purpose.value}",
                    source=ValueSource.DECLARED_EXACT,
                    confidence=Confidence.HIGH,
                    message=f"Per «{purpose.value}» usiamo gli spostamenti che avete indicato "
                    "al posto delle nostre stime.",
                )
            )
        kept = [mission for mission in estimated if mission.purpose not in replaced]
        return [*kept, *declared]

    # --- household-level quantities ------------------------------------------------------

    def _simultaneity_days(self, frequency: Frequency) -> ParameterValue:
        """Days per year a qualitative answer stands for (model_parameters.yaml)."""
        return self._parameter(f"simultaneity.days_per_year.{frequency.value.lower()}")

    def _car_count(self) -> int:
        count = 0
        for vehicle in self.profile.vehicles:
            option = self.catalog.options[vehicle.option_id]
            if option.mode is Mode.CAR and option.ownership is Ownership.OWNED:
                count += 1
        return count

    def _simultaneous_car_need(self) -> Estimated | None:
        """Days per year on which two household members need a car at the same time."""
        need = self.household.simultaneous_car_need
        if need is not None:
            parameter = self._simultaneity_days(need)
            return from_parameter(parameter, ValueSource.DECLARED_APPROXIMATE)
        if self._car_count() < 2:
            return None  # not asked, not needed to judge a second car
        sometimes = self._simultaneity_days(Frequency.SOMETIMES)
        rarely = self._simultaneity_days(Frequency.RARELY)
        often = self._simultaneity_days(Frequency.OFTEN)
        estimate = Estimated(
            value=sometimes.value,
            low=rarely.value,
            high=often.value,
            source=ValueSource.DEFAULT,
            confidence=Confidence.LOW,
        )
        self.notes.append(
            EstimationNote(
                subject="household",
                field="simultaneous_car_need",
                source=ValueSource.DEFAULT,
                confidence=Confidence.LOW,
                message="Non sappiamo quanto spesso due auto servono insieme: assumiamo "
                f"«a volte», circa {estimate.value:g} giorni l'anno, tra {estimate.low:g} e "
                f"{estimate.high:g} (affidabilità bassa).",
            )
        )
        return estimate

    def _service_usage(self) -> list[ServiceUsage]:
        usage = []
        for service, attribute, default_key, unit in _SERVICES:
            name = _SERVICE_NAMES[service]
            amount = self._estimate(
                getattr(self.other, attribute),
                self.defaults[default_key],
                "household",
                attribute,
                f"L'uso di {name} non è stato indicato: stimiamo {{value}} "
                f"{'giorni' if unit == 'days' else 'volte'} l'anno, un valore tipico per {{area}}",
            )
            usage.append(ServiceUsage(service=service, annual_amount=amount, unit=unit))
        return usage
