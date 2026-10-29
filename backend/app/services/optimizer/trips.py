"""One occurrence of a mission done with one option: how long it takes, what it consumes of the
option, what it costs on the margin, and what it is worth to the traveller (step 9).

The assignment weighs these numbers to choose a means; the evaluator (step 10) will add them up
over the year. Both read them here, so the two cannot disagree.

Time
    leg_hours = distance / speed(trip band) + fixed time per trip / 60
    The speed of a band the option does not define is taken from the nearest band it defines
    (the slowest, when two are equally near).
    person_hours = legs x leg_hours x passengers: every traveller's time counts, children's too.

Units
    A vehicle with seats (`capacity`) is taken in as many units as needed for the passengers:
    one car for four people, two taxis for six, one bicycle each. A service without seats
    (public transport, rail, flights) is taken one unit per passenger.

Usage (the input of the cost model, for ONE occurrence)
    km        distance x legs x units
    trips     legs x units; for means billed by the time the vehicle is kept (car sharing) one
              rental per unit, lasting the journey plus the stay at the destination
    days      per unit, `days_away` rounded up, at least one - for rental and day passes
    toll km   km x the share of the distance on toll motorways (by trip band), for road vehicles
    stay days `days_away` rounded up, for rail and flights: the traveller arrives without a
              vehicle and has to get around at the destination

Cost on the margin
    What using the option costs on top of owning it (`TcoCostModel.usage_cost`): the fuel and
    wear of a car already in the garage, nothing for a pass already paid, the full fare for a
    ticket. A household that owns something does not weigh its fixed costs when it chooses how
    to travel today; whether to own it is what the candidate portfolios are for.

Generalized cost (EUR per occurrence)
    cost on the margin + value of time x person_hours x perceived-time weight
    weight(comfort) = 1 + (m - 1) x (10 - comfort) / 10, m = the multiplier at comfort 0.
    An hour in a comfortable car counts less than an hour spent waiting for a crowded bus.
"""

import math
from dataclasses import dataclass

from app.data.loader import Catalog
from app.models import MobilityMission, MobilityOption, OptionUsage, Range, TripBand
from app.services.costs.model import TcoCostModel

_BAND_ORDER = (TripBand.URBAN, TripBand.REGIONAL, TripBand.LONG)


@dataclass(frozen=True)
class Trip:
    """One occurrence of a mission (all its legs, all its travellers) done with one option."""

    option_id: str
    units: int
    leg_hours: float
    person_hours: float
    usage: OptionUsage
    usage_cost: float
    comfort: float


class TripCalculator:
    def __init__(self, catalog: Catalog, cost_model: TcoCostModel | None = None) -> None:
        self._catalog = catalog
        self._cost_model = cost_model or TcoCostModel(catalog)

    def trip(self, mission: MobilityMission, option: MobilityOption) -> Trip:
        legs = mission.legs_per_occurrence
        distance = mission.distance_km_one_way.value
        units = (
            math.ceil(mission.passengers / option.capacity)
            if option.capacity
            else mission.passengers
        )
        leg_hours = self.leg_hours(option, distance)
        trip_minutes = legs * leg_hours * 60.0

        if option.cost_per_minute is not None:
            # billed by the time the vehicle is kept: one rental per vehicle
            trips = units
            minutes = units * (trip_minutes + self.stay_hours(mission) * 60.0)
        else:
            trips = legs * units
            minutes = 0.0
        billed_by_day = option.cost_per_day is not None and option.cost_per_minute is None
        days = units * max(1, math.ceil(mission.days_away)) if billed_by_day else 0

        km = distance * legs * units
        toll_km = km * self._motorway_share(distance) if option.uses_motorways else 0.0
        destination_days = math.ceil(mission.days_away) if option.no_vehicle_at_destination else 0
        usage = OptionUsage(
            annual_km=Range.point(km),
            annual_trips=Range.point(trips),
            annual_minutes=Range.point(minutes),
            annual_days=Range.point(days),
            annual_toll_km=Range.point(toll_km),
            annual_destination_days=Range.point(destination_days),
        )
        if option.comfort_score is None:
            raise ValueError(f"{option.id}: no comfort score")
        return Trip(
            option_id=option.id,
            units=units,
            leg_hours=leg_hours,
            person_hours=legs * leg_hours * mission.passengers,
            usage=usage,
            usage_cost=self._cost_model.usage_cost(option, usage),
            comfort=option.comfort_score.value,
        )

    def leg_hours(self, option: MobilityOption, distance_km: float) -> float:
        speeds = option.average_speed_kmh
        if not speeds:
            raise ValueError(f"{option.id}: no average speed")
        band = self._catalog.trip_band(distance_km)
        nearest = min(
            speeds,
            key=lambda known: (
                abs(_BAND_ORDER.index(known) - _BAND_ORDER.index(band)),
                speeds[known].value,
            ),
        )
        overhead = option.fixed_time_min_per_trip.value if option.fixed_time_min_per_trip else 0.0
        return distance_km / speeds[nearest].value + overhead / 60.0

    def _motorway_share(self, distance_km: float) -> float:
        """Share of a leg driven on toll motorways: none in town, more as the trip gets longer."""
        band = self._catalog.trip_band(distance_km)
        if band is TripBand.URBAN:
            return 0.0
        key = "regional" if band is TripBand.REGIONAL else "long"
        return self._catalog.value(f"usage.motorway_share.{key}")

    def stay_hours(self, mission: MobilityMission) -> float:
        """Time the traveller spends at the destination during one occurrence."""
        if mission.days_away > 0:
            return mission.days_away * 24.0
        return self._catalog.assignment_rules.stay_hours_by_purpose[mission.purpose]


class GeneralizedCost:
    """Turns a trip into one number in EUR: money plus time, time being weighed by comfort."""

    def __init__(self, catalog: Catalog) -> None:
        self.value_of_time = catalog.value("valuation.value_of_time_eur_per_hour")
        self._multiplier = catalog.value("assignment.perceived_time_multiplier_at_zero_comfort")

    def time_weight(self, comfort: float) -> float:
        """How many hours of travel an hour feels like, from 1 (comfort 10) to the multiplier
        (comfort 0)."""
        return 1.0 + (self._multiplier - 1.0) * (10.0 - comfort) / 10.0

    def of(self, trip: Trip) -> float:
        perceived_hours = trip.person_hours * self.time_weight(trip.comfort)
        return trip.usage_cost + self.value_of_time * perceived_hours
