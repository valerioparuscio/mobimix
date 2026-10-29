# Methodology

Work in progress: this note documents what exists. Each modelling module adds its formulas,
assumptions, units, sources and known limitations here as it is implemented
(CLAUDE.md section 40).

## 1. Pipeline

```text
UserProfile
  -> DemandEstimator        -> MobilityDemand (missions)
  -> PortfolioGenerator     -> candidate Portfolios (+ the current one, the baseline)
  -> FeasibilityChecker     -> reject portfolios that cannot serve the needs
  -> PortfolioOptimizer     -> ModeAssignment (which option serves which mission)
  -> PortfolioEvaluator     -> PortfolioEvaluation (cost, time, comfort, flexibility, CO2)
  -> RecommendationEngine   -> current / cheapest / balanced / fastest + explanations
```

Interfaces: [backend/app/services/interfaces.py](../backend/app/services/interfaces.py).
Feasibility always runs before any ranking.

## 2. Need, mode, portfolio

Three different things, never merged into one object:

- **Need** - a `MobilityMission`: purpose, frequency, distance, passengers, luggage, children,
  time criticality. Independent of how it is served.
- **Mode** - how a need is physically served (`Mode`: car, PT, bicycle, e-bike, taxi...).
- **Portfolio** - the resources a household has available (`Portfolio` of `PortfolioItem`s, each
  pointing to a `MobilityOption`).

An option belongs to exactly one mode. The same mode can be reached through several options
(CAR: owned car, car sharing, rental), with very different cost structures.

## 3. Missions

Distance convention: `distance_km_one_way` is the length of **one leg**; one occurrence of a
mission is `legs_per_occurrence` legs (2 for a round trip).

```text
annual_legs = occurrences_per_year x legs_per_occurrence
annual_km   = annual_legs x distance_km_one_way
```

Trip bands for speed lookup (`URBAN`, `REGIONAL`, `LONG`) are classified on the one-way leg
distance; the thresholds are parameters (`bands.*`, currently placeholders).

## 4. Provenance and uncertainty

Three layers (see [provenance.py](../backend/app/models/provenance.py)):

| Layer | Type | Meaning |
|---|---|---|
| Declared | `NumericAnswer` | what the user said: exact, range, or unknown |
| Model input | `Estimated` / `ParameterValue` | value + low/high + source + confidence |
| Result | `Range` | low / expected / high |

Value sources: `DECLARED_EXACT`, `DECLARED_APPROXIMATE`, `INFERRED`, `STATISTICAL_ESTIMATE`,
`DEFAULT`, `OBSERVED` (future).

Uncertainty is propagated **to first order, treating inputs as independent**. Each uncertain
input is moved in turn to the low and to the high end of its range, the others staying at their
expected value; the effects of different inputs are combined as a root sum of squares on each
side (`Range.sum_independent`, `Range.times_independent`, and the cost model's own probe). The
result is a *plausible* range - what happens when inputs err independently - not the worst case.

The worst case (every input at its unfavourable end at once, i.e. plain interval arithmetic)
is practically impossible and gives useless ranges: for a small car whose expected cost is about
4,800 EUR/year it gave 3,100-11,000 EUR; the plausible range is 4,150-5,900. `Range.__add__` and
`Range.__sub__` remain the conservative interval operations, available where a hard bound is wanted.

Limitation: inputs shared by different items (the fuel price shared by two cars) are treated as
independent between items, and quantities derived from the same count (taxi trips and the km of
those trips) are treated as independent: both slightly overstate or understate the range.

## 5. Option data

Cost fields of a `MobilityOption` (EUR, see [options.py](../backend/app/models/options.py)):

```text
annual depreciation = (purchase_price - residual_value) / expected_lifetime_years
annual fixed cost   = fixed_cost_year + maintenance + insurance + tax + parking + financing
annual variable     = annual_km x (cost_per_km + consumption/100 x energy_price)
                      + minutes x cost_per_minute + trips x cost_per_trip + days x cost_per_day
```

The cost model itself is step 6; the data are already sanity-checked against published
total-cost figures in `backend/tests/test_catalog.py` (ISFORT average and the sum.money
simulator).

Time per leg = `distance / average_speed_kmh[band] + fixed_time_min_per_trip`.

## 6. Questionnaire

Design: [frontend/src/form/](../frontend/src/form/). The form state is deliberately separate
from the domain profile (`UserProfile`): the form has "unanswered" states and band choices; the
profile has `NumericAnswer`s. `formToProfile` / `profileToForm` convert between them.

- **Numeric answers.** Each numeric question is a band, an exact value or "I don't know". A band
  is sent as a range (`DECLARED_APPROXIMATE` once the demand estimator tags it); a band with
  low == high is sent as an exact value; "I don't know" is sent as all-null and triggers
  statistical estimation. Bands live in [data/questionnaire.yaml](../data/questionnaire.yaml).
- **Words to numbers.** "Rarely / sometimes / often" for trips and services are translated into
  ranges by bands flagged `placeholder: true` - modelling assumptions, not measurements.
- **Adaptivity.** Rules in `rules.ts`: car questions only with cars, simultaneity only with two
  or more cars, distance of weekend/holiday trips only if there are such trips, work questions
  only for people who work or study.
- **Nothing is lost.** Fields the questionnaire does not ask (age band, accessibility, PT
  quality...) are kept from the loaded profile, so editing a demo household and re-saving it
  returns the same profile apart from the edits. Covered by round-trip tests on the five demo
  households.
- **Persistence.** The draft is kept in the browser's `localStorage`; nothing is stored on the
  server.

Added to the profile for the questionnaire: `OtherMobility.car_rental_days_per_year`, and a
per-adult "has a driving licence" answer (needed to know who can drive).

## 7. Demand estimation

Code: [backend/app/services/demand/estimator.py](../backend/app/services/demand/estimator.py)
(`RuleBasedDemandEstimator`); provenance helpers in
[statistics/estimation.py](../backend/app/services/statistics/estimation.py). Endpoint:
`POST /api/profile/estimate-demand`.

**Missions produced** (purpose; occurrences per year):

| Mission | Occurrences per year |
|---|---|
| COMMUTE / STUDY, one per working or studying adult | physical days per week x weeks per year, where physical days = days per week - remote days (never below 0) and weeks per year = working days per year / 5 (school days / 5 for students) |
| SCHOOL_ESCORT | school days per year, if the household said it escorts its children; otherwise school days x a default share (0.5, range 0-1) because the children's age is unknown |
| SHOPPING, LOCAL_LEISURE | local trips per week x local weeks per year (48), split by a default share (50/50). Default trips per week = per-adult default x number of adults |
| WEEKEND, LONG_DISTANCE (long weekends), HOLIDAY | declared value, or the default for the residential context |

Every mission is filled from three layers: the user's answers, the statistical defaults of the
area type ([default_profiles.yaml](../data/default_profiles.yaml)) and the mission templates
([mission_templates.yaml](../data/mission_templates.yaml): legs, passengers, luggage, time
window, weather sensitivity, days away).

**Provenance and uncertainty.** An answer is DECLARED_EXACT (HIGH) or DECLARED_APPROXIMATE
(MEDIUM, midpoint of the band, band ends as range). A missing answer falls back to the default:
STATISTICAL_ESTIMATE, with LOW confidence while the default is a placeholder. A computed value is
INFERRED if all its ingredients are declared or inferred, otherwise it inherits the weakest
source; its confidence is the lowest of its ingredients and of the model constants it uses.
Ranges propagate by interval arithmetic. Every fallback adds an `EstimationNote` (subject, field,
source, confidence, plain-language message), so no estimate is silent and later steps can say
which missing answer would improve the result most.

**Declared use of taxi, car sharing, rental, rail and flights is not added as demand.** A taxi
trip serves a need that is already among the missions; counting it again would inflate demand.
It is returned as `current_service_usage` and will feed the cost of the current portfolio and
the baseline assignment.

**Simultaneous car need.** The qualitative answer maps to days per year
(never 0, rarely 10, sometimes 40, often 100, almost daily 200; ranges in
[model_parameters.yaml](../data/model_parameters.yaml)). With two or more cars and no answer the
estimator assumes "sometimes" with the wide range 10-100 and LOW confidence. With fewer cars and
no answer the value is left unknown.

**Detailed mode.** Missions declared by the user replace the estimated ones of the same purpose.

**Limitations.** Business trips and family visits are not modelled separately. The school-escort
mission covers the morning trip only. Declared car mileage is not yet used to calibrate the
missions: on the demo households the estimated needs (7,600-31,000 km) are in the same order of
magnitude as the declared car kilometres, and the comparison will be made when the current
portfolio is costed (steps 6 and 9). Estimation is deterministic (no random sampling).

## 8. Cost of the current portfolio

Code: [backend/app/services/costs/](../backend/app/services/costs/). Endpoint:
`POST /api/profile/current-cost`.

**Option cost** (`TcoCostModel`, EUR/year; components are `CostLine`s):

```text
depreciation + financing + insurance + tax + maintenance + parking      (fixed, x quantity)
+ subscription fee                                                      (x months/12 for monthly passes)
+ energy       = consumption/100 x km x energy price
+ distance     = cost_per_km x km
+ time         = trips x min(minutes x per-minute, ceil(hours) x per-hour, per-day)
+ per trip     = cost_per_trip x trips
+ per day      = cost_per_day x days                       (options without a per-minute tariff)
```

Electric-car energy uses a blend of home and public charging (home share, AC/DC split from
[model_parameters.yaml](../data/model_parameters.yaml)); an e-bike is charged at home.

**Depreciation.**

| Case | Formula |
|---|---|
| new purchase | (purchase - residual) / lifetime (linear, as in the brief) |
| already owned, value known | value x r, with r = 1 - (residual / purchase)^(1/lifetime) |
| already owned, value unknown | expected: value at the average age of the Italian fleet (13 years) x r; low: 0; high: linear |

The last case is deliberate. Most cars on the road are old; charging them the depreciation of a
new car (about 1,250 EUR/year for a small car instead of about 420) would overstate the cost of
the baseline and bias the analysis against owning a car. The household's real value is the single
most useful extra answer, and the cost result says so (`accuracy_hints`).

**Current portfolio** (`CurrentCostEstimator`): owned vehicles, held subscriptions, services the
household declares or is estimated to use (taxi, car sharing, rental, rail, flights, micro-sharing)
and walking. Kilometres are the declared ones, else the area default for the first or second car;
parking is declared or the area default. A bike-sharing pass covers micro-sharing trips. Services
are priced from the number of uses times a typical size of one use (km per taxi ride, minutes per
car-sharing rental... all placeholders in model_parameters.yaml).

**Not included:** public-transport tickets bought without a pass (not asked), tolls (the evaluator of
step 10 charges them on the trips it models), financing.
How needs are served mode by mode - and so what extra tickets or taxi rides a candidate portfolio
needs - is the assignment step.

**Confidence.** The confidence of a portfolio cost is the weakest confidence among the items that
carry at least 10% of the total, so a small uncertain item does not drag it down. Today it is LOW
for every demo household because no car value is declared; once a household states it, the
confidence rises.

**Accuracy hints.** For each uncertain input the cost is recomputed with that input known exactly;
the three inputs that would narrow the range most are returned with the reduction in EUR/year.

**Plausibility check.** The declared car kilometres are compared with the estimated needs
(`CarKmCheck`); outside 0.5-1.25 of the needs a note is added. Nothing is corrected silently.
On the demo households the ratios are 0.58-0.97, so no note is raised.

**Expected costs today** (placeholders included, EUR/year, plausible range in brackets): see the
tests in `backend/tests/test_current_cost.py`; they are regression values to update on purpose.

## 9. Candidate portfolios

Module: [backend/app/services/portfolios/](../backend/app/services/portfolios/). Rules:
[data/portfolio_rules.yaml](../data/portfolio_rules.yaml). Endpoint: `POST /api/portfolios/generate`.

The generator proposes a short list of setups the household could really adopt (CLAUDE.md section
20). It does not enumerate every combination, and it does not judge: a candidate that cannot serve
the needs is still produced, and the feasibility check (step 8) removes it. Each candidate is built
from three independent choices.

1. **Fleet** - how many of the cars the household owns it keeps: all, then one fewer, down to none.
   For each size, one candidate per distinct set of models kept (two identical cars are one
   candidate: it does not matter which is sold). A household with no cars may buy one: a compact
   car if it has up to two adults and no children, a family car otherwise
   (`new_vehicles.car_compact` / `car_family`).
2. **Add-on set** - one entry of `addon_sets` in the rules file. Today: cars only; transit passes
   cancelled; transit passes for the people who commute; an e-bike; a scooter; passes plus e-bike.
   Car-free candidates always include passes. Adding or removing a set is a data change.
3. **Services** - the pay-per-use layer (`service_layer`), identical for all candidates of a
   household.

**Passes.** A pass is added for each adult who commutes (has a commute or study mission) and
holds none; if nobody commutes, for every adult. Passes already held are kept. The pass is the
cheapest annual one sold in the area that the person may buy. A discounted pass (under 27, over 65)
is offered only if the whole age band qualifies, and never when the age is unknown. Monthly passes
are not proposed.

**Services.** The layer is the list in the rules file, restricted to what each option's
`available_in_area_types` allows. A service the household *declares* it uses is added even outside
its area (declared use shows it is available); a statistical default is not evidence and adds
nothing. Pay-per-use items carry no fixed cost, so having them is not a decision: how much they
are used is decided when needs are assigned to modes (step 9). The consequence is that
"0 cars + PT + car sharing" and "0 cars + PT + taxi + rental" (examples in CLAUDE.md section 20)
are the same candidate here, "0 cars + PT", with the services available to both.

**Kept and new.** A kept vehicle or subscription carries its `profile_ref`, so the evaluator can
price it as the asset already owned (declared km, parking, present value). A new item has none and
is priced as a purchase. New vehicles belong to the household (`holder_id` empty).

**Changes.** `Portfolio.changes` lists what the household would do to reach the candidate: sell
or buy a vehicle, cancel or start a subscription. The change penalty (step 11) is computed from it,
and `description` is written from it, so the text on screen cannot diverge from the model.

**Deduplication.** A candidate is dropped if its vehicles and subscriptions equal today's setup
or an earlier candidate's. The current portfolio itself is built by the cost module, not here.

**Steady-state view.** The comparison is of annual costs once the new setup is in place. The
one-off effects of changing (selling a car below its book value, a purchase paid up front,
financing) are not included.

## 10. Feasibility

Module: [backend/app/services/feasibility/](../backend/app/services/feasibility/). Rules:
[data/feasibility_rules.yaml](../data/feasibility_rules.yaml), thresholds `feasibility.*` in
[data/model_parameters.yaml](../data/model_parameters.yaml). Endpoint:
`POST /api/portfolios/feasibility`.

The check runs after generation and before any ranking (CLAUDE.md section 6): a cheap portfolio
that cannot serve the household's needs must never win. It answers two questions.

**1. Which options serve each mission?** An option of the portfolio serves a mission if all of this
holds (the first rule that fails is the reason recorded):

| Rule | Condition |
|---|---|
| distance | `min_practical_distance_km` <= one-way leg <= `max_practical_distance_km` of the option |
| pass | a pass held by someone else does not serve a personal mission (the ticket does) |
| licence | an option with `requires_license` needs the traveller's licence (personal mission) or any licensed adult (household mission) |
| seats | owned vehicles of the mode have, together, `capacity` x `quantity` >= passengers; pay-per-use services are taken as available in as many units as needed |
| luggage | luggage space + `feasibility.luggage_tolerance_levels` >= luggage of the mission |
| children | modes in `modes_not_with_children` (scooter, motorcycle) are out |
| accessibility | modes excluded by a constraint of the traveller (all adults for a household mission) |
| hours | modes in `unavailable_time_bands` are out at that hour (public transport and rail at night) |
| regularity | from `feasibility.regular_min_occurrences_per_year` (50) a mission is regular: types in `occasional_only_types` (taxi, ride hailing, rental, flights) do not count |

If nothing serves a mission, the portfolio is **infeasible** (`NO_OPTION`), unless the mission is
rare (up to `feasibility.rare_max_occurrences_per_year`, 2 a year): then it is a warning. If only
occasional-only means serve a regular mission the issue is `NO_REGULAR_OPTION` (blocking): a daily
commute by taxi is technically possible but not reasonable. Missions that never happen are not
checked. The result lists, for each mission, the options that serve it: step 9 chooses among them.

**2. Simultaneous car need.** If the demand says two members need a car at the same time on `D` days
a year and the portfolio has fewer than two cars, a car-like service (car sharing, rental, taxi) has
to cover those days:

- no such service, and `D` above the rare threshold: infeasible;
- only occasional-only services (taxi, rental) and `D` >= the regular threshold: infeasible;
- otherwise a warning that names the services the household would use on those days.

So, in the demo households, `family_two_cars` (need declared "often", about 100 days) cannot sell a
car in a suburb, where there is no car sharing, but could in a city centre, where there is.

**Luggage tolerance.** With tolerance 0 a small car could never take a family on holiday (LARGE
luggage), which would unfairly send the household's own car to rental in the baseline. With 1, a
car one level short is accepted. It is a placeholder, and it applies equally to the current
portfolio and to the candidates, so it cannot tilt the comparison.

**The current portfolio.** The check works on any portfolio, the current one included, once the
common service layer is added to it (`with_service_layer`): without it, a household that declares
no taxi would look unable to do a rare trip that a taxi would serve. The setup a household lives
with today must always come out feasible; a test enforces it on the five demo households, as a rule
that rejects it would be a wrong rule. The pipeline never discards the current portfolio: it is the
baseline.

**Output.** `FeasibilityResult`: `is_feasible`, `options_by_mission`, and `issues` with severity
(`BLOCKING` / `WARNING`), code and a plain-language message in Italian, built from the same
structured facts (distance, passengers, luggage, reason of rejection), never written separately.

**Known simplifications.** No schedule: simultaneity is the one declared number, not an overlap of
times. A person without a licence being driven by another is not modelled. Public-transport
quality (frequency, waiting, coverage) is not modelled: if the option exists in the area and the
distance is within range it serves the mission. Children are not individuals: a bicycle is not
excluded for them (they ride their own), a scooter is.

## 11. Mode assignment

Module: [backend/app/services/optimizer/](../backend/app/services/optimizer/). Tables:
[data/assignment_rules.yaml](../data/assignment_rules.yaml), tunables `assignment.*` and
`valuation.*` in [data/model_parameters.yaml](../data/model_parameters.yaml). Endpoint:
`POST /api/portfolios/assignment`.

The assignment answers, for a portfolio the feasibility check has admitted: *which of its options
serves each mission, and how often?* It is not a search for the best portfolio. It describes what a
household does with the means it has, and it does so **identically for the current portfolio and
for every candidate**: a difference between two portfolios must come from the portfolios, not from
how they were treated. (CLAUDE.md section 21: a transparent rule, no solver.)

**One occurrence of a mission with one option** (`TripCalculator`, shared with the evaluator of
step 10 so the two cannot disagree):

```text
leg_hours      = distance / speed(trip band) + fixed time per trip / 60
person_hours   = legs x leg_hours x passengers            (children's time counts as well)
units          = ceil(passengers / capacity)  for a vehicle with seats (one car for four,
                 two taxis for six, one bicycle each);  = passengers  for a service without seats
km             = distance x legs x units
trips          = legs x units;   for car sharing: one rental per unit, kept for the journey
                 plus the stay at the destination (hours per purpose, or days_away x 24)
days           = units x max(1, ceil(days_away))   for rental and day passes
toll km        = km x share of the distance on toll motorways (0 in town, 40% regional, 80% long)
                 for road vehicles
stay days      = ceil(days_away) for rail and flights: no vehicle at the destination
```

A band the option does not define takes the speed of the nearest band it defines (the slower one
if two are equally near).

**Cost on the margin** (`TcoCostModel.usage_cost`): the components of the cost that grow with use
(energy, distance charge, time charge, trip charge, day charge, tolls, local transport at a
destination reached without a vehicle), not the fixed ones. Tolls are charged at 0.08 EUR/km
(`usage.motorway_toll_eur_per_km`, class A average, sourced); a stay by train or plane costs
15 EUR/day to get around (`usage.destination_mobility_eur_per_day`, a placeholder). A household
that owns a car does not weigh its insurance when it decides how to go to work; it weighs the
fuel. Whether to own the car is the question the candidate portfolios answer, one level above.

**Generalized cost** (EUR per occurrence of the mission):

```text
cost  = cost on the margin + value of time x person_hours x weight(comfort)
weight(comfort) = 1 + (m - 1) x (10 - comfort) / 10        m = perceived-time multiplier at comfort 0
```

The value of time is the fixed 10 EUR/h (`valuation.value_of_time_eur_per_hour`); `m` = 2
(`assignment.perceived_time_multiplier_at_zero_comfort`), so an hour in a car (comfort 8.5) feels
like 1.15 hours and an hour on public transport (5.5) like 1.45. The household's own preferences
(`Preferences`) do **not** enter: the assignment is a neutral description of behaviour, and the
preferences weigh the *outcomes* later (CLAUDE.md section 7).

**Choosing among the options of a mission** (`GeneralizedCostAssigner`):

1. *Within a mode, the best way in.* Of the options of one mode only the best competes: the pass the
   household holds, not the ticket; the car it owns, not car sharing; the car with room for the
   luggage (the feasibility tolerance is for the household that has only a small car), then the
   cheapest.
2. *Across modes, a multinomial logit:* `share(mode) ~ exp(-s x (cost - lowest cost))`, with
   `s = assignment.logit_scale_per_eur` = 0.25 per EUR. With 10 EUR/h that is about 0.04 per minute
   of travel, the order of magnitude of urban mode-choice models. A hard minimum would put every
   trip on one means and move it all on a difference of one cent, a result no recommendation can
   rest on; the logit spreads trips over near ties and still sends them all to a clear winner.
3. *Two situations take part of a mission's occurrences away from some options.* The mission is split
   into slices, each assigned by steps 1-2, and the shares are summed.
   - **Bad weather**: on a share `assignment.bad_weather_share` (15%) x the mission's weather weight
     (`weather_factor`: low 0, medium 1, high 1.5) of occurrences, options exposed to the weather
     (bicycle, e-bike, scooter, motorcycle, micro-sharing) are not used, if the portfolio has
     another way to serve the mission.
   - **Car busy**: with a single car and `simultaneous_car_need_days` = D, the car cannot serve the
     personal missions of the household's other members on D of their occurrences (spread over their
     missions in proportion). The car goes to its driver: the holder of the car, or else the first
     adult with a licence.
4. *A vehicle for one rider serves one person at a time.* A bicycle, e-bike, scooter or motorcycle
   held by a person is used by that person alone for their personal missions; one that belongs to the
   household serves as many people as there are units - those who would ride it most (by kilometres),
   decided by repeating the assignment until no vehicle has more users than units. Whoever holds a car
   uses their own for personal missions. Missions of the whole household (shopping, a weekend away)
   are not limited by who holds what.
5. Shares under `assignment.min_share` (2%) are dropped and the rest renormalised.

**Output.** `ModeAssignment`: for each mission the options with their `share` (they add up to 1) and
a `reason` (`ONLY_OPTION`, `BEST`, `ALTERNATIVE`, `WEATHER`, `CAR_BUSY`) that the explanation of
step 11 is written from; missions nothing serves (`unserved_mission_ids`, only rare ones); `notes`
(a vehicle that two people would use, a conflict that could not be resolved). The current portfolio
is always assigned, with the same service layer as the candidates (`with_service_layer`); a candidate
rejected by the feasibility check is not.

**Check on the demo households.** Modelled mileage of the owned cars against the declared one (km per
year): urban single 3,500 / 6,000; urban couple 10,400 / 8,500; family with two cars 18,600 / 21,000;
peripheral family 27,600 / 18,000 (there the estimated needs, 29,000 km, already exceed the declared
mileage by 60%). The order of magnitude is right; the model is **not calibrated** on the declared
mileage, and a test only guards against the car being dropped or overused.

**Known simplifications** (all to be revisited with the evaluator and with real data):

- *Habit and destination mobility.* Tolls and the cost of getting around after a train or a flight make
  a couple keep the car for a 400 km holiday, but not for a 250 km long weekend (90% by train), and a
  single traveller with a car still goes by train on a 450 km holiday, where the generalized cost says so. What the model does not know is that
  people avoid changing means with luggage, or that the car is already paid for in their eyes. Families
  with children and large luggage keep the car, because tickets for four are dear.
- *Rail availability.* Whether a station is near home and destination is not modelled. Regional rail
  needs 10 km (it was 5, which gave it a quarter of the short urban commutes); the right answer depends
  on the area data (Car Independence Index).
- *Pay-per-use friction.* Registering, booking, finding a vehicle: a day pass for bike sharing can take
  7-13% of short shopping trips by a car owner, the tail of the logit. No hassle penalty yet.
- *No schedule.* Who needs which vehicle at which hour exists only as the "car busy" days and the
  one-rider rule. Two members who both drive to work every day with one car are not detected unless the
  household declared the need for two cars.
- *Declared use of services* (taxi, car sharing, rental...) is not used here: the shares come from the
  rule, not from habit. The cost of the current setup declared by the user (step 6) is the baseline.
- *Rental* is charged for the days of the stay and the fuel of the journey, not of the local driving at
  the destination.

## 12. Evaluation

Module: [backend/app/services/scoring/](../backend/app/services/scoring/) (`PortfolioEvaluator`), the
stages as one callable pipeline in [backend/app/services/pipeline.py](../backend/app/services/pipeline.py).
Endpoint: `POST /api/portfolios/evaluate`.

For every portfolio the assignment admitted, and always for the current one, the evaluator computes
annual cost, travel time, comfort, flexibility, reliability, car kilometres, CO2 and the number of
private vehicles. It works allocation by allocation: how many times a year a mission is done with an
option (occurrences x share) times what one occurrence uses and costs (`TripCalculator`, the same
numbers the assignment weighed). The uncertainty of the missions - occurrences and distances, each
with its low/high - is propagated; speeds and the shares of the assignment are taken as exact.

**Physical quantities: modelled, for every portfolio alike.**

```text
travel hours   sum over allocations of person-hours (every traveller's time)
comfort etc.   average of the option's score weighted by the hours spent with it
car km         vehicle-km of options of mode CAR (owned, shared, rented); taxis excluded
CO2            fuel or electricity burnt x emission factor (petrol 2.31, diesel 2.65 kg/l,
               grid mix in g/kWh); else the option's g/km x km (per vehicle- or passenger-km, as
               the units of the trip already are)
vehicles       owned cars and motorcycles/scooters (not bicycles)
```

**Cost: the declared one, plus the differences the model finds.** The assignment does not reproduce the
real use of the household's vehicles (modelled and declared car mileage differ by up to 50%), so the
model's absolute cost would not be the one the household recognises. The current portfolio therefore
costs exactly what step 6 found from the declared data, and every other portfolio is that plus a change
computed *item by item*:

| Item | Cost in the candidate |
|---|---|
| kept (same option, holder and id in the profile) | cost today + (modelled use cost in the candidate - modelled use cost today) |
| dropped (a car sold, a pass cancelled) | gone, with its whole cost today |
| added (a new car, e-bike, pass) | full modelled cost: purchase depreciation (linear, not discounted by age), the area's parking for a car, fee of the pass, plus its use cost |

"Use cost" is the marginal one (`TcoCostModel.usage_cost`, section 11): the components that grow with
use - energy, wear, tickets, rental days, tolls, local transport at a destination reached without a
vehicle. The fixed costs of a kept item are identical in the two portfolios and cancel exactly, so the
uncertainty about the value of a car already owned (the largest in the current cost) does not blur the
saving of a candidate that keeps it, while selling that car removes all of it. The same-portfolio
check: a copy of the current portfolio costs exactly the current cost.

*Floor.* What a candidate can save on an item is limited to the use cost the household declared for it:
a car never costs less than its fixed part, and tickets nobody told us about (the questionnaire does not
ask) cannot be saved, only added. It is deliberately conservative: it never invents a saving.

**Differences from the current portfolio, mission by mission.** Every quantity above is linear in the
occurrences and the distances of the missions, which carry a low/high. A portfolio's total is the sum over
missions of (the mission's expected value) x (its relative range), the missions adding up independently;
a *difference* between two portfolios is computed the same way on the per-mission differences, so that
what the two share - the same uncertain need - cancels. A portfolio compared with itself differs by exactly
nothing; subtracting two totals instead would have given "+-386 hours" for no change at all. The cost
difference is built from the item changes: use-cost changes of kept items, the full cost of added items,
minus the declared cost of dropped ones. So a candidate that sells the car carries the uncertainty about the
car's value (the saving depends on it), while one that keeps the car does not. Prices and speeds are taken
at their expected value in the differences, and emission factors in the totals.

**Output.** `PortfolioEvaluation`: `annual_cost` (a `Range`), `cost_by_category` (ownership,
subscriptions, use), `delta` (against the current portfolio: cost, hours, perceived hours, comfort,
flexibility, car km, CO2, saving per extra hour), `uses_by_option`, `cost_lines` (item by item: for a kept item its declared lines plus one
`usage_change`; for a new one its fixed lines plus `usage`), hours, scores, car km, CO2, vehicles,
`confidence` (the weakest of the cost's and of the missions that make up at least 10% of the
kilometres) and `data_quality_notes`. The notes say when a mission is unserved, repeat those of the
assignment, and - for the current portfolio - when the modelled car mileage is less than two thirds
or more than one and a half times the declared one.

**On the demo households** (EUR per year, hours per year; placeholders included, so read them as
regression values, not as findings):

| Household | Current cost | Sell the car + passes | Hours | Keep car + e-bike |
|---|---:|---:|---:|---:|
| urban single | 4,764 | 1,227 (-3,537) | 283 -> 344 | 5,177 (+413) |
| urban couple | 5,476 | 2,902 (-2,574) | 868 -> 1,013 | 5,721 (+245) |
| peripheral family | 5,593 | 4,460 (-1,133) | 1,860 -> 2,461 | 5,869 (+275) |

(The peripheral family saves 1,133 EUR by giving up the car and spends 600 hours more: about 1.9 EUR per
extra hour, far under the 10 EUR/h the household's time is worth - the number that will keep that option
from winning in step 11.)

**Known simplifications.**

- *Items not declared.* Tickets and occasional services are not in the declared cost; a candidate is
  charged for using more of them but never credited for using fewer (the floor).
- *The residual of a removed item.* A car sold takes away its whole declared cost, including the fuel of
  kilometres the model cannot attribute to any mission, while the replacement means are modelled for the
  missions only. The gap is largest where the model explains little of the declared mileage (urban
  single: 3,500 of 6,000 km) and is reported in the notes.
- *Comfort and flexibility are averages over the hours of use*, not properties of the portfolio: owning
  a car one hardly uses does not raise them.
- *Speeds, prices and the shares of the assignment are exact in the differences*; their uncertainty is
  not propagated.
- *Confidence is LOW on every demo* because the value of the household's car is not declared and the
  scores of the options are placeholders.

## 13. Recommendations

Module: [backend/app/services/recommendations/](../backend/app/services/recommendations/)
(`RuleBasedRecommendationEngine`, wording in `wording.py`); the whole analysis as one call:
`analyze()` in [pipeline.py](../backend/app/services/pipeline.py). Endpoint: `POST /api/analyze`.
Parameters: `recommendation.*` in [data/model_parameters.yaml](../data/model_parameters.yaml).

**Net benefit** of a candidate against the current portfolio, in EUR a year (brief section 22):

```text
net = saving - value of time x extra perceived hours - change penalty
```

The extra *perceived* hours are the extra hours of travel, each weighted by its discomfort (the weight
of the assignment, section 11), so time and comfort are priced together at 10 EUR/h: an extra hour in a
crowded bus costs more than one in a car. Time saved counts in favour. The saving and the hours are
the mission-by-mission differences of section 12, so their ranges are as narrow as the data allow;
the net benefit combines them as independent errors.

**Change penalty** (EUR-equivalent per year; starting values agreed with the product owner on
2026-10-29, all placeholders):

| Change | Penalty |
|---|---:|
| each vehicle sold | 400 |
| each vehicle bought (an e-bike too) | 250 |
| each subscription cancelled | 50 |
| each subscription started (Claude's choice, not discussed) | 50 |
| relying on car sharing: at least 12 uses a year (Claude's choice) and more than today | 150, once |

The penalty comes from `Portfolio.changes`, so it is computed from the same list the description of
the candidate is written from. It stops the engine from recommending a big change for a small gain:
350 EUR a year for selling a car and buying an e-bike is a net -300 and KEEP_CURRENT (CLAUDE.md
section 22).

**Strength**, from the net benefit (thresholds agreed on 2026-10-29, except the middle one):

| Net benefit (EUR/year) | Strength |
|---|---|
| below 150 | KEEP_CURRENT |
| 150 to 500 (500 is Claude's choice) | SMALL_IMPROVEMENT |
| 500 to 1,000 | CONSIDER_CHANGE |
| 1,000 and over | STRONG_OPPORTUNITY, only if even the pessimistic end of the range is at least 150; otherwise CONSIDER_CHANGE |

The last rule is how uncertainty enters (brief section 23): a recommendation is never "strong" if, with
the inputs at their pessimistic ends, it could be worth less than the threshold of doing nothing.

**Category** (what kind of change it is), from the changes and the number of cars before and after:
the last car sold or the first one bought is CHANGE_PORTFOLIO; a sale together with a purchase is
REPLACE_VEHICLE; only sales, REDUCE_VEHICLES; only purchases, ADD_ASSET; only subscriptions,
CHANGE_SUBSCRIPTION. OPTIMIZE_USAGE (same assets, used differently) is reserved: every candidate
today changes at least one asset.

**What is shown** (CLAUDE.md section 9). The portfolios compared are the current one and every feasible
candidate. Each role goes to one portfolio, and a portfolio holding several roles is shown once:

| Role | Rule |
|---|---|
| CURRENT | the baseline, always |
| CHEAPEST | lowest annual cost, the current portfolio included |
| FASTEST | fewest hours of travel |
| MOST_COMFORTABLE | highest comfort |
| BALANCED | see below |

The extremes are one-sided by definition and the strength says whether they are worth it: the cheapest
setup of the peripheral family saves 1,150 EUR a year and costs 600 hours more, a net -12,500, so it is
shown as the cheapest and KEEP_CURRENT. If the current portfolio is already the cheapest, the fastest
or the most comfortable, it says so.

**BALANCED, by the household's own priorities.** Of the Pareto-efficient portfolios (none is better on
cost, time, comfort and flexibility together - and on car km and CO2, if the household gave them a
weight), the one that improves most on today. Every criterion is the relative change against the
current portfolio (cost -30% scores +0.3, comfort -10% scores -0.1, clipped to +-1), weighted by the
sliders of the questionnaire (`Preferences`, 0 to 5) and averaged; the current portfolio scores 0 and
wins ties, so something has to improve on it to be chosen. The cost includes the change penalty. Car
dependence and sustainability weigh 0 unless the household raised them (neutrality, CLAUDE.md section 7).
The sliders choose the compromise; they do not change the value of time or the strength thresholds.

**Headline** (`headline_portfolio_id`): the answer to "should I change?". The candidate with the highest
net benefit if it reaches 150 EUR a year, else the current portfolio. It may hold no role: the best deal
is not always the cheapest, the fastest or the household's compromise.

**Explanation** (CLAUDE.md section 24). Each recommendation carries `facts`: a code and numbers produced
by the model (`saving`, `dropped_item_cost`, `second_car_needed`, `services_cost`, `extra_time`, `comfort`,
`saving_per_extra_hour`, `net_benefit`, `not_worth_the_time`, `tiny_gain`, `environment`, `confidence`...).
The Italian sentences (`explanation`) are rendered from the facts alone (`wording.render`), so the text
cannot say what the calculation did not find; a fact without a wording is an error. Amounts are rounded
to what the estimate supports (to 50 EUR above 1,000, to 10 above 100) and given as ranges. The second-car
fact comes from the declared simultaneous need ("a second car is needed at the same time as the first
on about 40 days a year"); the services fact from the use cost the candidate adds on pay-per-use means.

**On the demo households** (placeholders included: regression values, not findings):

| Household | Headline | Net benefit, EUR/year |
|---|---|---|
| urban single | sell the car, buy an e-bike, take a pass: STRONG_OPPORTUNITY | +2,100 (1,400 to 3,100) |
| urban couple | cancel one of the two passes: SMALL_IMPROVEMENT | +440 (180 to 840) |
| family with two cars | keep (all one-car and car-free setups are infeasible) | - |
| peripheral family | keep (the cheapest, car-free, nets -12,500) | - |
| car-free household | keep (buying a car nets -3,100 to -4,200) | - |

**Known simplifications.**

- The penalty is charged every year of the comparison, which is how it was agreed ("EUR per year"); the
  one-off effects of changing (selling a car below its book value, a purchase paid at once) are not
  modelled.
- Only the four changes above and car sharing are penalised. Taxi and rental reliance, transfers, weather
  exposure and loss of flexibility are not, apart from what comfort and time already price.
- Comfort weighs heavily: with a perceived-time multiplier of 2, the couple's car-free setup (comfort 7.8
  to 5.8) is charged 2,400 EUR a year for comfort alone. The multiplier and the comfort scores are
  placeholders, and this is the single largest term in several verdicts.
- Strength uses the expected net benefit; the range only caps STRONG_OPPORTUNITY.
- Explanations are in Italian only.

## 14. What-if scenarios

Module: [backend/app/services/scenarios.py](../backend/app/services/scenarios.py), model
[backend/app/models/scenario.py](../backend/app/models/scenario.py). Endpoint: `POST /api/scenario`
(`{profile, scenario}` -> the same `AnalysisResult` as `/api/analyze`, with the scenario echoed back).
On the screen: the "E se...?" panel beside the results (CLAUDE.md section 27).

A scenario is a few assumptions the household can change to see what would happen, without changing its
answers. Each is a *change from today*, zero meaning "as it is"; the neutral scenario is the analysis
itself (the same object, byte for byte). The profile and the reference data are copied, never changed in
place. The bounds are what the model is meant to be asked; outside them the server answers 422.

| Control | Range | What it does to the model |
|---|---|---|
| remote work | +0 to +4 days a week | every adult who commutes works that many more days from home, never more than the days they work (an unknown number of remote days counts as 0, as in the demand estimator): fewer commuting occurrences, so fewer trips, hours and km |
| fuel price | -50% to +100% | the petrol and diesel prices (value and range), which also move the fuel of rental cars; electricity does not move |
| parking cost | -100% (free) to +200% | the declared parking cost of every car owned, and the statistical default (an undeclared cost, and the cost of a car the candidates buy) |
| car km | -50% to +100% | the declared kilometres of every car and the statistical defaults. It changes what the cars cost today and so what selling one saves; **the trips the household needs do not change** |
| e-bike incentive | 0 to 2,000 EUR | the purchase price of the e-bike the generator proposes, never below its resale value: a new e-bike's yearly depreciation falls by subsidy / lifetime (600 EUR over 6 years: 100 EUR a year); an e-bike already owned is unaffected |

An answer the household did not give stays unknown: a what-if does not raise the confidence of a number.
What changes is the default that stands in for it.

The screen offers narrower ranges than the server accepts (fuel -30% to +50%, parking -100% to +100%,
car km -50% to +50%, incentive up to 1,000 EUR); a test keeps the two within each other.

**Recomputation.** The whole pipeline reruns (a few hundredths of a second per demo household). The screen waits
0.3 s after the last move of a slider, cancels the request still in flight, and keeps the previous answer
on screen, faded, until the new one arrives. It shows the assumptions in force, what the answer was
without them, and says so when the answer changes ("with these assumptions the best choice is now...").

**Known simplifications.** Fuel moves for everybody at once: no region or fuel type apart from petrol and
diesel. "Car km" changes the cost of the car but not the missions, so a household that says it drives 20%
more does not get a longer commute; remote work is the control that changes the needs. The incentive is a
reduction of the price, not a separate refund: no eligibility, no income limits. Public-transport prices
and car-sharing availability, also listed in CLAUDE.md section 27, are not offered yet.

## 15. Known limitations (current state)

- Tariffs are Milan-centred (ATM, Trenord, Free2move, BikeMi); other cities are not modelled.
- Comfort / flexibility / reliability scores, statistical defaults by area type, simultaneity
  mapping, the value of time and the candidate-portfolio rules are **placeholders** - see
  [assumptions.md](assumptions.md).
- Emission factors per passenger-km for public transport, rail and air are unsourced estimates.
- The Car Independence Index is not used yet (data to be provided). Until then the services
  available to a household depend on the coarse area type only: free-floating car sharing, bike
  and scooter sharing exist in city centres and urban areas only, while taxi, PT and rail tickets
  and rental are available everywhere (confirmed by the developer). How good the service is
  outside the city - waiting time, frequency - is not modelled yet: the same fixed access time
  per trip applies in every area.
- The candidate generator does not propose a second car to a one-car household, replacing a car
  with another model (an electric one, say), monthly passes, or selling a motorcycle, scooter or
  bicycle already owned.
- The analysis is complete end to end on the backend (`POST /api/analyze`); the web app does not show
  the result yet (step 12).
- The recommendation parameters (change penalties, strength thresholds) are **placeholders**; see
  section 13.
- What-if: public-transport prices and car-sharing availability are not controls yet (section 14).
- The feasibility rules (thresholds, regular-use exclusions, accessibility, luggage tolerance,
  minimum distances of rail, flights and rental) are **placeholders** to confirm; see section 10.
- The assignment parameters (scale of the choice, perceived-time multiplier, share of bad-weather
  days, stay hours, weather weights) are **placeholders**; section 11 says what they do and what
  is not modelled.
- Server-side validation messages are in English (Pydantic); the form prevents most invalid
  input, but a translated error layer is still to do.
- The municipality is free text: no ISTAT list, so the Car Independence Index cannot be looked up yet.
