"""The household's current portfolio and what it costs (step 6).

The current portfolio is the baseline every alternative is compared with (CLAUDE.md section
10). It is built from what the household owns and holds, plus the pay-per-use services it
declares to use:

    owned vehicles      -> items, priced with the declared (or estimated) km, parking and value
    subscriptions       -> items, priced at the catalogue fee unless the user declared the price
    services in use     -> taxi, car sharing, rental, rail, flights, micro-sharing, priced from
                           the declared number of uses and a typical size of each use
    walking             -> always available, free

How the needs are served mode by mode (and so what PT tickets or extra taxi rides would cost) is
the job of the assignment step; here only declared facts are priced. Public-transport tickets
bought without a pass are therefore not included: the questionnaire does not ask about them.

Plausibility check: the declared kilometres of the cars are compared with the estimated needs
(`CarKmCheck`). A large gap is reported, never silently corrected.
"""

from app.data.loader import Catalog
from app.models import (
    CarKmCheck,
    Confidence,
    CurrentCostResult,
    Estimated,
    EstimationNote,
    ItemUsage,
    MobilityDemand,
    Mode,
    OptionType,
    OptionUsage,
    ParameterValue,
    Portfolio,
    PortfolioItem,
    PortfolioOrigin,
    Range,
    ServiceKind,
    UserProfile,
    ValueSource,
)
from app.services.costs.model import TcoCostModel
from app.services.costs.portfolio_cost import PortfolioCostCalculator
from app.services.statistics.estimation import (
    AREA_NAMES,
    CONFIDENCE_WORDS,
    constant_confidence,
    from_answer,
    weakest_confidence,
)

_NONE = ParameterValue(value=0)
_DECLARED = (ValueSource.DECLARED_EXACT, ValueSource.DECLARED_APPROXIMATE, ValueSource.OBSERVED)


def _range(estimate: Estimated) -> Range:
    return Range(low=estimate.low, expected=estimate.value, high=estimate.high)


class CurrentCostEstimator:
    def __init__(self, catalog: Catalog, cost_model: TcoCostModel | None = None) -> None:
        self._catalog = catalog
        self._calculator = PortfolioCostCalculator(catalog, cost_model)

    def estimate(self, profile: UserProfile, demand: MobilityDemand) -> CurrentCostResult:
        run = _Run(self._catalog, profile, demand)
        portfolio, usages = run.build()
        car_km_check = run.car_km_check()  # may add a note: it must run before pricing
        cost = self._calculator.price(portfolio, usages, run.notes)
        return CurrentCostResult(portfolio=portfolio, cost=cost, car_km_check=car_km_check)


class _Run:
    def __init__(self, catalog: Catalog, profile: UserProfile, demand: MobilityDemand) -> None:
        self.catalog = catalog
        self.profile = profile
        self.demand = demand
        self.area = profile.household.location.area_type
        self.defaults = catalog.defaults_for(self.area).values
        self.items: list[PortfolioItem] = []
        self.usages: list[ItemUsage] = []
        self.notes: list[EstimationNote] = []
        self.car_km: list[Estimated] = []

    def build(self) -> tuple[Portfolio, list[ItemUsage]]:
        self._vehicles()
        self._subscriptions()
        self._services()
        self._add(PortfolioItem(option_id="walking"), OptionUsage(), Confidence.HIGH)
        portfolio = Portfolio(
            id="current",
            name="Situazione attuale",
            origin=PortfolioOrigin.CURRENT,
            items=self.items,
            description="Mezzi, abbonamenti e servizi che il nucleo ha oggi.",
        )
        return portfolio, self.usages

    def _add(self, item: PortfolioItem, usage: OptionUsage, confidence: Confidence) -> None:
        self.items.append(item)
        self.usages.append(ItemUsage(usage=usage, confidence=confidence))

    def _note(self, estimate: Estimated, subject: str, field: str, message: str) -> None:
        if estimate.source in _DECLARED or estimate.source is ValueSource.INFERRED:
            return
        self.notes.append(
            EstimationNote(
                subject=subject,
                field=field,
                source=estimate.source,
                confidence=estimate.confidence,
                message=message.format(value=f"{estimate.value:g}", area=AREA_NAMES[self.area])
                + f" (affidabilità {CONFIDENCE_WORDS[estimate.confidence]}).",
            )
        )

    # --- owned vehicles --------------------------------------------------------------------

    def _vehicles(self) -> None:
        cars_so_far = 0
        for vehicle in self.profile.vehicles:
            option = self.catalog.option(vehicle.option_id)
            name = option.name.lower()
            is_car = option.mode is Mode.CAR

            if is_car:
                fallback_key = "car_annual_km_first" if cars_so_far == 0 else "car_annual_km_second"
                cars_so_far += 1
                km_fallback = self.defaults[fallback_key]
            else:
                km_fallback = self.catalog.parameters.get(f"usage.annual_km.{option.id}", _NONE)
            km = from_answer(vehicle.annual_km, km_fallback)
            self._note(
                km,
                vehicle.id,
                "annual_km",
                f"I km annui di «{name}» non sono stati indicati: usiamo {{value}} km, "
                "un valore tipico per {area}",
            )
            if is_car:
                self.car_km.append(km)

            confidences = [km.confidence]
            parking: Range | None = None
            if is_car:
                parking_estimate = from_answer(
                    vehicle.parking_cost_year, self.defaults["parking_cost_year_per_car"]
                )
                self._note(
                    parking_estimate,
                    vehicle.id,
                    "parking_cost_year",
                    f"Il costo del parcheggio di «{name}» non è stato indicato: usiamo "
                    "{value} € l'anno, un valore tipico per {area}",
                )
                parking = _range(parking_estimate)
                confidences.append(parking_estimate.confidence)

            current_value: Range | None = None
            if vehicle.current_value.kind != "unknown":
                value = from_answer(vehicle.current_value, _NONE)
                current_value = _range(value)
                confidences.append(value.confidence)
            elif option.purchase_price is not None:
                # Value and age unknown: the depreciation is the most uncertain cost item.
                confidences.append(Confidence.LOW)
                self.notes.append(
                    EstimationNote(
                        subject=vehicle.id,
                        field="current_value",
                        source=ValueSource.DEFAULT,
                        confidence=Confidence.LOW,
                        message=f"Non conosciamo il valore attuale di «{name}»: stimiamo la "
                        "svalutazione sull'età media delle auto in Italia, con un intervallo "
                        "ampio (affidabilità bassa).",
                    )
                )

            self._add(
                PortfolioItem(
                    option_id=option.id, holder_id=vehicle.primary_user_id, profile_ref=vehicle.id
                ),
                OptionUsage(
                    annual_km=_range(km),
                    existing_asset=True,
                    current_value=current_value,
                    parking_cost_year=parking,
                ),
                weakest_confidence(confidences),
            )

    # --- subscriptions ---------------------------------------------------------------------

    def _subscriptions(self) -> None:
        for subscription in self.profile.subscriptions:
            declared = subscription.annual_cost.kind != "unknown"
            override = _range(from_answer(subscription.annual_cost, _NONE)) if declared else None
            self._add(
                PortfolioItem(
                    option_id=subscription.option_id,
                    holder_id=subscription.holder_id,
                    profile_ref=subscription.id,
                ),
                OptionUsage(fixed_cost_override=override),
                Confidence.HIGH,  # the user said they hold it
            )

    # --- services in use -------------------------------------------------------------------

    def _holds_bike_sharing_pass(self) -> bool:
        return any(
            self.catalog.option(sub.option_id).type is OptionType.BIKE_SHARING_SUBSCRIPTION
            for sub in self.profile.subscriptions
        )

    def _services(self) -> None:
        for service in self.demand.current_service_usage:
            amount = service.annual_amount
            option = self.catalog.service_option(service.service)
            if option is None or amount.value <= 0:
                continue
            if service.service is ServiceKind.MICRO_SHARING and self._holds_bike_sharing_pass():
                continue  # included in the bike-sharing pass already counted

            def per_use(parameter_id: str) -> tuple[Range, Confidence]:
                parameter = self.catalog.parameter(parameter_id)
                return parameter.as_range(), constant_confidence(parameter)

            uses = _range(amount)
            usage = OptionUsage()
            confidences = [amount.confidence]
            kind = service.service
            if kind is ServiceKind.TAXI:
                size, conf = per_use("usage.taxi_ride_km")
                usage = OptionUsage(annual_trips=uses, annual_km=uses.times_independent(size))
            elif kind is ServiceKind.CAR_SHARING:
                size, conf = per_use("usage.car_sharing_minutes_per_rental")
                usage = OptionUsage(annual_trips=uses, annual_minutes=uses.times_independent(size))
            elif kind is ServiceKind.CAR_RENTAL:
                size, conf = per_use("usage.car_rental_km_per_day")
                usage = OptionUsage(annual_days=uses, annual_km=uses.times_independent(size))
            elif kind is ServiceKind.RAIL:
                size, conf = per_use("usage.rail_trip_km")
                usage = OptionUsage(annual_trips=uses, annual_km=uses.times_independent(size))
            elif kind is ServiceKind.MICRO_SHARING:
                size, conf = per_use("usage.micro_sharing_minutes_per_trip")
                usage = OptionUsage(annual_trips=uses, annual_minutes=uses.times_independent(size))
            else:  # AIR: priced per flight
                usage = OptionUsage(annual_trips=uses)
                conf = Confidence.HIGH
            confidences.append(conf)
            self._add(PortfolioItem(option_id=option.id), usage, weakest_confidence(confidences))

    # --- plausibility check ----------------------------------------------------------------

    def car_km_check(self) -> CarKmCheck | None:
        if not self.car_km:
            return None
        cars = Range.point(0.0)
        for km in self.car_km:
            cars = cars + _range(km)
        needs = self.demand.total_annual_km
        ratio = cars.expected / needs if needs > 0 else None
        all_declared = all(km.source in _DECLARED for km in self.car_km)

        if all_declared and ratio is not None:
            low = self.catalog.value("calibration.car_km_min_ratio")
            high = self.catalog.value("calibration.car_km_max_ratio")
            message = None
            if ratio < low:
                message = (
                    f"I km dichiarati per le auto ({cars.expected:,.0f}) sono molto meno degli "
                    f"spostamenti che stimiamo ({needs:,.0f} km): una parte avviene con altri "
                    "mezzi, oppure abbiamo sovrastimato alcune abitudini."
                )
            elif ratio > high:
                message = (
                    f"I km dichiarati per le auto ({cars.expected:,.0f}) superano gli "
                    f"spostamenti che stimiamo ({needs:,.0f} km): probabilmente mancano "
                    "spostamenti nel profilo (lavoro, visite, viaggi)."
                )
            if message is not None:
                self.notes.append(
                    EstimationNote(
                        subject="household",
                        field="car_km_vs_needs",
                        source=ValueSource.INFERRED,
                        confidence=Confidence.MEDIUM,
                        message=message.replace(",", "."),
                    )
                )
        return CarKmCheck(cars_km=cars, needs_km=needs, ratio=ratio, all_declared=all_declared)
