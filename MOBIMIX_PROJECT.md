# MOBIMIX PERSONAL — PROJECT BRIEF FOR CLAUDE CODE

## 1. Project Purpose

**MobiMix Personal** is a web application that acts as a **personal mobility portfolio advisor**.

Its purpose is not to optimize a single trip, but to evaluate the user's **overall annual mobility setup** and answer questions such as:

- Is my current mobility setup already efficient?
- Could I spend less by changing how I travel?
- Could I reduce the number of private vehicles I own?
- Would it make sense to buy an e-bike, scooter, motorcycle, or car?
- Is a public transport subscription worth it for me?
- Would car sharing, taxi, rental, bike sharing, or pay-per-use public transport replace part of my current mobility?
- How much money would I save, and at what cost in time, comfort, and flexibility?
- If I had used a different mobility configuration last year, how much would I have spent?
- What is the best mobility portfolio for me or my household?

The central product idea is:

> **MobiMix does not answer “How should I make this trip?”**
>
> It answers:
>
> **“Given the way I live and move, what mobility should I own, subscribe to and buy?”**

The user should be able to describe their mobility with a relatively small number of answers.  
Where information is incomplete, MobiMix should estimate missing values using statistical defaults and clearly indicate uncertainty.

The application must be designed for **rapid MVP implementation**, while keeping each model component modular so that it can later be replaced with richer models and databases.

---

# 2. Product Vision

MobiMix should behave like a **neutral mobility consultant**.

It must not assume that public transport, shared mobility, cycling, or private car ownership is intrinsically better.

A recommendation may legitimately be:

- keep the current car;
- sell the second car;
- buy an e-bike;
- buy a scooter;
- replace pay-per-use tickets with an annual public transport subscription;
- stop paying for an unused subscription;
- increase taxi usage while removing a private vehicle;
- use car rental for holidays instead of owning a second car;
- keep two cars because household constraints make alternatives impractical.

The application should compare feasible alternatives using three primary criteria:

1. **Cost**
2. **Travel time**
3. **Comfort / convenience**

Additional dimensions should be supported in the model, even if initially simplified:

- flexibility;
- reliability;
- environmental impact / CO2;
- independence from private car ownership;
- magnitude of lifestyle change required.

The output should not be a single supposedly “perfect” answer.

MobiMix should normally present at least:

- **Current setup**
- **Cheapest feasible portfolio**
- **Best compromise**
- **Fastest / most convenient portfolio**

These results should represent different points on a **Pareto frontier** between cost, time, and comfort.

---

# 3. Core Product Principle: Preserve Mobility Needs

MobiMix should not optimize by simply eliminating trips.

The baseline assumption is:

> The user's underlying mobility needs remain approximately constant.  
> MobiMix changes how those needs are served.

Example:

A household currently performs:

- commuting;
- school trips;
- shopping;
- weekend trips;
- holidays;
- leisure;
- occasional long-distance travel.

An alternative portfolio must satisfy approximately the same set of needs.

The algorithm must therefore separate:

1. **Mobility need**
2. **Transport mode / service used to satisfy it**

This distinction is fundamental.

---

# 4. Main Web Experience

The MVP should be imagined as a responsive web page / web app.

Suggested flow:

```text
Landing Page
    ↓
Quick Mobility Profile
    ↓
Current Mobility Setup
    ↓
Annual Mobility Needs
    ↓
Preferences
    ↓
MobiMix Analysis
    ↓
Results Dashboard
    ↓
What-if Simulator
```

The questionnaire should avoid overwhelming the user.

The target should be approximately:

- 8–12 questions in the default quick flow;
- additional questions shown only when useful;
- optional detailed mode for more precise results.

The questionnaire should be **adaptive**.

Example:

If the user says they do not own a car, do not ask about annual car mileage.

If the user owns two cars, ask whether both are often needed at the same time.

If the user does not know annual kilometres, allow:

- exact value;
- approximate range;
- “I don't know”.

The latter should trigger statistical estimation.

---

# 5. User Modes

Design the data model so that three future usage modes can share the same engine.

## 5.1 Quick Profile

Few questions.

Use user answers + statistical defaults.

Purpose:

- immediate recommendation;
- low friction;
- exploratory use.

## 5.2 Detailed Profile

More precise declared data:

- annual kilometres;
- typical weekly mobility;
- travel purposes;
- weekend habits;
- holiday travel;
- taxi / sharing use;
- detailed household constraints.

## 5.3 Actual / Retrospective Profile

Future mode based on real past behaviour.

Goal:

> “Last year you spent €8,000.  
> Had you used this alternative portfolio, you could have spent €6,200, with +35 hours of travel time and slightly lower comfort.”

Possible future data sources:

- odometer readings;
- mobility diaries;
- transport subscriptions;
- sharing history;
- banking / expense categories;
- calendar;
- voluntarily provided location traces;
- tickets / receipts.

MVP does not need integrations, but architecture should not prevent them.

---

# 6. Individual and Household Model

MobiMix must support both:

- a single user;
- a household.

A household is **not just the sum of independent individuals**.

Simultaneous mobility requirements matter.

Example:

```text
08:00 Person A takes the car to work
09:00 Person B needs to take a child to a medical appointment
```

With only one car, the second need must be served through another mode.

Therefore household-level feasibility must eventually support time overlap and shared vehicle availability.

For the MVP, this may initially be approximated with questions such as:

- How many adults?
- How many children?
- How many licensed drivers?
- How often do two household members need a car at the same time?
- Never / rarely / sometimes / often / almost every day.

Later this can evolve into explicit schedules.

---

# 7. Minimum Input Data

The first MVP should work with a relatively small questionnaire.

Suggested initial fields:

## Person / Household

- age range;
- municipality or residential zone;
- number of adults;
- number of children;
- number of licensed drivers;
- work / study status;
- optional income / mobility budget band;
- accessibility constraints;
- important family logistics.

## Work / Study

- distance from home;
- number of trips / days per week;
- number of days working from home;
- normal travel time window;
- whether punctual arrival is critical.

## Current Vehicle Ownership

- number of cars;
- approximate car category;
- fuel type;
- annual kilometres if known;
- parking / garage cost;
- motorcycle / scooter;
- bicycle;
- e-bike.

## Current Subscriptions

- public transport annual / monthly subscription;
- rail subscription;
- car sharing subscription;
- bike sharing subscription;
- other MaaS products.

## Other Mobility

Approximate:

- weekly local non-work trips;
- weekend trips;
- long-distance weekends;
- holidays;
- rail trips;
- flights;
- taxi use;
- car sharing;
- bike / scooter sharing.

## Preferences

Allow a simple ranking or sliders:

- save money;
- reduce travel time;
- maximize comfort;
- maximize flexibility;
- reduce car dependence;
- sustainability.

The UI should make clear that exact data are optional.

---

# 8. Statistical Reconstruction of Missing Data

Users often do not know their real annual mobility.

MobiMix must be designed around this fact.

Each input should have:

```text
value
source
confidence
```

Possible sources:

```text
DECLARED_EXACT
DECLARED_APPROXIMATE
INFERRED_FROM_OTHER_INPUTS
STATISTICAL_ESTIMATE
DEFAULT
OBSERVED_DATA   # future
```

Example:

| Variable | Value | Source | Confidence |
|---|---:|---|---|
| commuting distance | 3,400 km/year | calculated from declared commute | high |
| weekend travel | 1,800 km/year | statistical estimate | medium |
| taxi use | 10 trips/year | declared approximate | medium |
| bicycle | 600 km/year | statistical estimate | low |

The system must never present statistically estimated values as precise observations.

Results should support uncertainty ranges:

> Estimated annual cost: €7,400–€8,100

instead of:

> €7,683.24

when data quality does not justify precision.

---

# 9. Future Statistical Data Sources

Do not hard-code the MVP to any particular database.

Create replaceable data provider interfaces.

Potential future sources include:

- ISTAT;
- ISFORT / Audimob;
- ACI vehicle fleet data;
- municipal statistics;
- census data;
- household income statistics;
- public transport use statistics;
- local mobility surveys;
- city-specific origin/destination datasets;
- shared mobility datasets;
- parking datasets;
- Car Independence Index;
- accessibility indicators.

For the MVP, use a small local JSON/YAML/CSV dataset with documented assumptions.

Every model parameter should ideally include:

```text
value
geographic_scope
valid_from
valid_to
source_name
source_url
confidence
notes
```

This is important because future work will progressively replace generic assumptions with real databases.

---

# 10. Mobility Needs / Mission Model

Do not model mobility purely as annual kilometres.

Create **mobility missions**.

A mission represents a recurring or occasional need.

Example schema:

```yaml
mission:
  id:
  person_id:
  purpose:
  frequency_per_year:
  distance_km:
  passengers:
  luggage_level:
  children:
  time_critical:
  start_time_window:
  duration_tolerance:
  weather_sensitivity:
  accessibility_requirements:
```

Initial purposes:

```text
COMMUTE
STUDY
SCHOOL_ESCORT
SHOPPING
LOCAL_LEISURE
WEEKEND
FAMILY_VISIT
HOLIDAY
BUSINESS
LONG_DISTANCE
OTHER
```

The MVP may use aggregated missions rather than individual trips.

Example:

```yaml
COMMUTE:
  distance_km_one_way: 8
  days_per_year: 180
  passengers: 1
  time_critical: true

WEEKEND:
  distance_km_round_trip: 120
  trips_per_year: 20
  passengers: 3
  luggage_level: medium
```

---

# 11. Mobility Options Catalogue

Create a modular catalogue of mobility options.

Initial MVP categories:

## Owned assets

- small petrol car;
- medium petrol car;
- diesel car;
- electric car;
- motorcycle;
- scooter;
- bicycle;
- e-bike.

## Subscriptions

- public transport annual;
- public transport monthly;
- rail subscription;
- bike sharing subscription;
- car sharing subscription.

## Pay-per-use

- public transport ticket;
- taxi;
- ride hailing;
- car sharing;
- bike sharing;
- scooter sharing;
- car rental;
- rail;
- air travel.

Each option should use a common data model.

Example:

```yaml
mobility_option:
  id:
  type:
  ownership_type:
  fixed_cost_year:
  purchase_price:
  residual_value:
  expected_lifetime_years:
  cost_per_km:
  cost_per_minute:
  cost_per_trip:
  maintenance_cost_year:
  insurance_cost_year:
  tax_cost_year:
  parking_cost_year:
  average_speed:
  comfort_score:
  flexibility_score:
  reliability_score:
  capacity:
  luggage_capacity:
  max_practical_distance:
  weather_sensitivity:
  geographic_availability:
```

Not every field applies to every mode.

---

# 12. Total Cost of Ownership

Private assets must use **Total Cost of Ownership**, not only fuel cost.

For a car:

```text
annual depreciation
+ financing cost if applicable
+ insurance
+ taxes
+ maintenance
+ tyres
+ fuel / electricity
+ parking / garage
+ tolls where relevant
```

Generic MVP formula:

```text
annual_vehicle_cost =
    depreciation
  + fixed_costs
  + variable_cost_per_km * km
```

Depreciation MVP:

```text
(purchase_price - expected_residual_value) / holding_years
```

Later replace with market-specific depreciation curves.

The cost model must be isolated as a separate module.

---

# 13. Car Independence / Territorial Context

Geographic context should influence recommendations.

For the MVP, the **Car Independence Index (CII)** can be represented as an optional contextual variable.

Use it as a prior / territorial indicator, not as a deterministic rule.

Bad rule:

```text
if CII > 6:
    sell_car()
```

Correct use:

```text
car_free_feasibility =
    f(CII, household, mobility_needs, available_services)
```

Possible uses:

1. estimate missing mobility behaviour;
2. prioritize candidate portfolios;
3. modify expected time / flexibility penalties;
4. estimate how realistic car-free or car-light alternatives are.

Future full implementation should ideally replace a single aggregated CII value with direct multimodal accessibility metrics and routing.

Long-term MobiMix could generate a **Personal Car Independence Index**:

> 82/100 — 91% of ordinary mobility needs can be served without a private car with an average additional travel time below 12 minutes.

---

# 14. Candidate Mobility Portfolios

A portfolio is a combination of:

- owned vehicles;
- subscriptions;
- pay-per-use services.

Examples:

```text
2 cars

1 car + public transport subscription

1 car + 2 public transport subscriptions

1 car + e-bike

1 car + scooter + public transport

0 car + public transport + bike

0 car + public transport + e-bike + car sharing

0 car + public transport + taxi + car rental

EV + e-bike + public transport
```

The MVP does not need to enumerate every mathematically possible combination.

Use configurable generation rules.

Avoid unrealistic combinations.

The portfolio generator must be a separate module.

---

# 15. Feasibility Comes Before Optimization

This is a core architectural rule.

Do **not** rank portfolios before checking whether they can satisfy the household's mobility needs.

For each mission determine which modes can serve it.

Example:

| Mission | Bike | E-bike | PT | Car | Taxi | Train | Rental |
|---|---|---|---|---|---|---|---|
| commute 8 km | yes | yes | yes | yes | yes | no | no |
| family weekend 180 km | no | no | maybe | yes | expensive | yes | yes |
| shopping | maybe | maybe | yes | yes | yes | no | no |

A portfolio is infeasible if one or more important missions cannot be reasonably served.

Later versions must also test simultaneous household demand.

---

# 16. Mode Assignment

For each feasible portfolio, MobiMix must assign mobility missions to available modes.

Example portfolio:

```text
1 car
2 PT subscriptions
1 e-bike
```

Possible assignment:

```text
commute A → e-bike
commute B → public transport
shopping → car
weekend → car
holiday → car
evening → PT / taxi
```

The assignment itself can be optimized.

MVP can initially use rule-based or simple exhaustive assignment.

Later versions can use:

- linear programming;
- MILP;
- constraint programming;
- shortest path / generalized cost;
- stochastic optimization.

Keep the optimizer behind a clean interface.

---

# 17. Evaluation Metrics

For every feasible portfolio calculate:

## 17.1 Annual Cost

```text
ownership cost
+ subscription cost
+ usage cost
```

## 17.2 Annual Travel Time

```text
sum(travel time × annual frequency)
```

For MVP, travel time can use simple mode-specific assumptions or multipliers.

Later replace with routing.

## 17.3 Comfort

MVP can use a normalized 0–10 score.

Comfort may depend on:

- mode;
- transfers;
- weather exposure;
- crowding;
- luggage;
- children;
- seat availability;
- trip length.

The first version may use simple coefficients.

## 17.4 Flexibility

Potential factors:

- immediate availability;
- service hours;
- need for booking;
- availability uncertainty;
- transfers;
- geographic coverage.

## 17.5 Sustainability

Optional MVP metric.

Examples:

- estimated CO2/year;
- car km/year;
- private vehicle ownership count.

---

# 18. Three Main Optimization Criteria

The product should explicitly expose the three criteria discussed during project conception:

## Cheapest

Minimize annual mobility cost while maintaining feasibility.

## Fastest / Most Convenient

Minimize travel time, with comfort / flexibility constraints.

## Best Compromise

Multi-objective balance between:

```text
cost
time
comfort
flexibility
```

Avoid one arbitrary universal weighting.

User preferences should influence the compromise.

---

# 19. Pareto Frontier

Prefer showing multiple efficient alternatives instead of claiming one single mathematically correct answer.

Example:

| Portfolio | Cost | Time | Comfort |
|---|---:|---:|---:|
| Current | €8,050 | 410 h | 8.0 |
| Cheapest | €4,950 | 510 h | 6.8 |
| Balanced | €6,400 | 455 h | 7.4 |
| Fastest | €8,900 | 390 h | 8.3 |

The user should visually understand the trade-off.

---

# 20. Compare Against Current Behaviour

The current setup is not merely another candidate.

It is the **baseline**.

For every alternative calculate:

```text
delta_cost
delta_time
delta_comfort
delta_flexibility
delta_co2
```

Example:

```text
Saving: €2,800/year
Additional travel time: +35 h/year
Comfort change: -0.7
```

Also calculate:

```text
saving_per_additional_hour = saving / extra_time
```

Example:

> You save €2,800/year in exchange for approximately 35 extra travel hours.

> Equivalent saving: €80 per additional travel hour.

This is a key user-facing metric.

---

# 21. Recommendation Types

Recommendations should be classified.

## KEEP

Current portfolio is already efficient.

## OPTIMIZE USAGE

Keep assets and subscriptions but use them differently.

Example:

> Use PT for two additional commuting days per week.

## CHANGE SUBSCRIPTION

Example:

> Annual PT subscription is cheaper than current ticket use.

or:

> Your annual subscription is underused; pay-per-use is cheaper.

## ADD VEHICLE / ASSET

Example:

> Buying an e-bike is expected to save €900/year.

## REPLACE VEHICLE

Example:

> Replacing the second car with an e-bike + car sharing is advantageous.

## REDUCE VEHICLES

Example:

> The second car is only essential on approximately 30 days/year.

## CHANGE PORTFOLIO

Major structural change.

Example:

> 0 cars + PT + e-bike + car sharing + rental.

---

# 22. Do Not Recommend Change for Tiny Gains

The mathematically cheapest solution is not automatically the right recommendation.

Create a **change penalty / switching cost**.

Possible components:

```text
vehicle sale/purchase
behaviour change
extra transfers
service dependence
loss of flexibility
habit disruption
uncertainty
```

Conceptually:

```text
net_benefit =
    economic_benefit
  - time_penalty
  - comfort_penalty
  - change_penalty
```

A solution saving €400/year while requiring selling two cars and dramatically changing behaviour should not be strongly recommended.

Possible recommendation levels:

```text
KEEP CURRENT
SMALL OPTIMIZATION
CONSIDER CHANGE
STRONG CHANGE OPPORTUNITY
```

---

# 23. Uncertainty

Every result should carry confidence / uncertainty.

Reasons:

- statistical input estimation;
- approximate costs;
- uncertain service availability;
- unknown real trip patterns;
- approximate comfort coefficients.

Suggested output:

```text
Estimated annual cost: €6,200–€6,700
Confidence: medium
```

The app should explain which additional input would most improve accuracy.

Example:

> “If you provide your car's annual mileage, we can significantly improve this estimate.”

This enables future **adaptive questioning** based on information gain.

---

# 24. Results Dashboard

The MVP dashboard should include:

## Current Mobility Portfolio

- owned vehicles;
- subscriptions;
- estimated annual mobility cost;
- annual travel time;
- comfort;
- car km;
- optional CO2.

## Recommended Portfolios

Cards for:

### Cheapest
### Balanced
### Fastest / Most Comfortable

Each card should show:

```text
portfolio composition
annual cost
difference vs current
annual time
difference vs current
comfort
confidence
```

## Recommendation Explanation

Example:

> Your second car costs approximately €4,300/year but appears essential on only 28–40 days/year.

> Replacing it with car sharing, taxi and occasional rental could save approximately €2,100/year.

Explanations are essential.

The system must remain transparent.

---

# 25. What-if Simulator

Design for a future interactive what-if section from the beginning.

Possible controls:

- work from home days/week;
- PT subscription price;
- fuel price;
- parking cost;
- car mileage;
- e-bike subsidy;
- car ownership;
- taxi usage;
- car sharing availability;
- holiday travel;
- household size.

Changing a parameter should recompute portfolios.

Example:

```text
Smart working: 0 → 2 days/week
```

Then update:

```text
annual cost
recommended portfolio
car ownership convenience
travel time
CO2
```

---

# 26. Suggested Technical Architecture

The project should be simple to run locally.

Suggested stack:

## Frontend

- React
- Vite
- TypeScript

## Backend

- Python
- FastAPI
- Pydantic

## Data / Persistence

Initial:

- local JSON / YAML / SQLite

Later:

- PostgreSQL
- PostGIS

Do not require PostGIS for MVP.

## Suggested repository structure

```text
mobimix/
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── forms/
│   │   ├── charts/
│   │   └── api/
│   └── ...
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── demand/
│   │   │   ├── costs/
│   │   │   ├── feasibility/
│   │   │   ├── portfolios/
│   │   │   ├── optimizer/
│   │   │   ├── scoring/
│   │   │   └── statistics/
│   │   ├── data/
│   │   └── main.py
│   │
│   └── tests/
│
├── docs/
│
├── data/
│   ├── mobility_options/
│   ├── default_profiles/
│   ├── tariffs/
│   └── geographic_context/
│
└── README.md
```

---

# 27. Important Modularity Requirement

Each major modelling component must be replaceable.

Define interfaces such as:

```python
class DemandEstimator:
    def estimate(profile) -> MobilityDemand:
        ...

class CostModel:
    def calculate(option, usage) -> CostResult:
        ...

class PortfolioGenerator:
    def generate(profile, demand) -> list[Portfolio]:
        ...

class FeasibilityChecker:
    def check(portfolio, demand) -> FeasibilityResult:
        ...

class PortfolioOptimizer:
    def optimize(portfolio, demand) -> Assignment:
        ...

class PortfolioEvaluator:
    def evaluate(portfolio, assignment) -> PortfolioResult:
        ...
```

This is critical because the first implementation will use simple assumptions.

Later modules may be replaced with:

- real routing;
- city-specific tariffs;
- rich mobility surveys;
- machine learning;
- MILP;
- household scheduling;
- real-time data.

---

# 28. Initial Algorithm

High-level pseudocode:

```python
profile = collect_user_profile()

demand = demand_estimator.estimate(profile)

current_portfolio = build_current_portfolio(profile)

candidate_portfolios = portfolio_generator.generate(
    profile=profile,
    demand=demand
)

results = []

for portfolio in candidate_portfolios:

    feasibility = feasibility_checker.check(
        portfolio,
        demand
    )

    if not feasibility.is_feasible:
        continue

    assignment = optimizer.assign(
        portfolio,
        demand
    )

    result = evaluator.evaluate(
        portfolio,
        assignment,
        profile.preferences
    )

    results.append(result)

pareto = calculate_pareto_frontier(results)

recommendations = recommendation_engine.compare(
    current=current_portfolio,
    candidates=pareto,
    preferences=profile.preferences
)
```

---

# 29. MVP Simplifications

The MVP should deliberately avoid overengineering.

Initial simplifications are acceptable if clearly documented.

Use:

- generic vehicle categories;
- generic depreciation;
- simple PT tariff;
- simple taxi tariff;
- simple car sharing tariff;
- generic average speeds;
- simple comfort scores;
- approximate weekend mobility;
- static geographic context;
- limited candidate portfolio set;
- rule-based feasibility;
- simple optimization.

Avoid initially:

- full routing engine;
- GTFS ingestion;
- real-time traffic;
- real-time MaaS availability;
- machine learning;
- detailed emissions lifecycle modelling;
- bank / GPS integration;
- ticket purchasing;
- booking;
- complex household activity scheduling.

The priority is to make the full end-to-end logic visible and testable quickly.

---

# 30. Synthetic Demo Profiles

Create several fixed test households.

At minimum:

## Profile A — Urban Single

```text
1 adult
city center
no children
commute 5 km
1 car
PT available
```

## Profile B — Urban Couple

```text
2 adults
1 car
different commuting patterns
good PT
```

## Profile C — Family With Two Cars

```text
2 adults
2 children
2 cars
suburban
significant weekend travel
```

## Profile D — Peripheral Household

```text
2 adults
1 child
poor PT
long commute
```

## Profile E — Car-Free Household

```text
2 adults
city center
PT + bike + taxi
```

These profiles should be used for regression testing of recommendations.

---

# 31. Validation Philosophy

Do not validate only that code runs.

Validate whether recommendations are plausible.

For each test household, document expected behaviour.

Example:

```text
Profile C should not recommend 0 cars if family weekend travel and simultaneous commuting make the configuration unrealistic.
```

Tests should cover:

- feasibility;
- cost calculation;
- subscription break-even;
- car ownership break-even;
- recommendation stability;
- missing-data estimation;
- uncertainty.

---

# 32. Future Data Enrichment

After the MVP works, improve one module at a time.

Suggested progression:

## Phase 1

Manual generic assumptions.

## Phase 2

Italian national data:

- ISTAT;
- ACI;
- Audimob / mobility surveys;
- generic national vehicle costs;
- PT tariffs.

## Phase 3

City-specific data:

- Milan public transport tariffs;
- taxi prices;
- sharing tariffs;
- parking;
- Area B / Area C;
- bike sharing;
- car sharing;
- local accessibility.

## Phase 4

Routing:

- car;
- bicycle;
- e-bike;
- walking;
- PT.

## Phase 5

Detailed household scheduling.

## Phase 6

Observed user data / behavioural calibration.

Each phase must preserve backward compatibility with the core model where possible.

---

# 33. MobiMix City — Future Extension

MobiMix Personal should be designed so its model can later be used at city scale.

**MobiMix City** would answer:

> “How would city mobility change if residents and city users adopted the mobility portfolios suggested by MobiMix?”

MobiMix City would use:

```text
public statistics
+ synthetic population
+ MobiMix Personal behavioural models
+ city mobility supply
```

to construct synthetic households.

Example synthetic household:

```text
2 adults
1 child
1 car
middle income
residential zone X
worker A commute 8 km
worker B commute 4 km
```

Run MobiMix for each household.

Aggregate changes such as:

```text
private cars owned
vehicle-km
PT trips
cycling km
sharing trips
taxi demand
car rental demand
parking demand
CO2
household mobility expenditure
travel time
```

---

# 34. MobiMix Personal → MobiMix City Feedback Loop

Data voluntarily collected through MobiMix Personal can improve MobiMix City.

This should influence architecture from the beginning.

MobiMix Personal can provide aggregated calibration data about:

- real annual mobility;
- household vehicle ownership;
- travel frequencies;
- weekend mobility;
- subscriptions;
- comfort preferences;
- willingness to change;
- reactions to recommendations.

Conceptually:

```text
PUBLIC DATA
    ↓
initial synthetic population
    ↓
MOBIMIX CITY
    ↓
prior mobility distributions
    ↓
MOBIMIX PERSONAL
    ↓
observed / declared real behaviour
    ↓
CALIBRATION
    ↓
improved MOBIMIX CITY
```

Never require personally identifiable data for this purpose.

Future calibration should use:

- anonymized data;
- aggregated statistics;
- consent;
- privacy-preserving design.

---

# 35. Adoption Model for MobiMix City

Do not assume that every user automatically adopts the theoretically best portfolio.

Future City simulations should include:

```text
P(adoption) =
    f(
        annual_saving,
        extra_travel_time,
        comfort_loss,
        change_magnitude,
        household_profile,
        territorial_context
    )
```

Possible scenarios:

```text
THEORETICAL MAXIMUM
100% adoption

HIGH ADOPTION
70%

BEHAVIOURAL
model-based adoption probability

CONSERVATIVE
20%
```

MobiMix Personal usage data could eventually calibrate this function.

---

# 36. MobiMix City Policy Simulation

Future City scenarios could test:

- PT fare reductions;
- e-bike incentives;
- parking cost changes;
- fuel price changes;
- car sharing expansion;
- new PT infrastructure;
- road pricing;
- EV incentives;
- bike infrastructure;
- work-from-home adoption.

Example question:

> What e-bike subsidy would cause 10% of households to abandon their second car?

This is not part of the Personal MVP, but the data model should allow this later.

---

# 37. Privacy

Use privacy-by-design.

The MVP should avoid unnecessary personal data.

Do not store:

- exact identity;
- unnecessary exact addresses;
- sensitive data not needed by the model.

Prefer:

- age ranges;
- zones / coarse geography;
- household categories;
- anonymized profiles.

Exact origin / destination data may be useful later for routing but should be optional and handled separately.

The architecture should distinguish:

```text
user account data
mobility profile data
anonymous modelling data
aggregated calibration data
```

---

# 38. Explainability

Every recommendation must be explainable.

Never output only:

> Recommended portfolio: 1 car + e-bike.

Instead explain:

> Your second car represents approximately €4,200/year in fixed and variable costs.

> Based on your estimated mobility needs, a second private car is essential only on approximately 35 days/year.

> Taxi, car sharing and rental could cover these cases for an estimated €1,900–€2,300/year.

> Estimated saving: €1,900–€2,300/year.

This explainability is essential for trust and future validation.

---

# 39. Initial UI Pages

Suggested initial implementation:

## `/`

Landing / description.

## `/profile`

Adaptive questionnaire.

Sections:

```text
About you
Household
Work / study
Vehicles
Subscriptions
Typical mobility
Weekend / holidays
Preferences
```

## `/results`

Summary dashboard.

Show:

```text
Current
Cheapest
Balanced
Fastest
```

## `/scenario`

What-if analysis.

Initial MVP can support a small set of editable inputs.

## `/methodology`

Explain assumptions and calculation logic.

This page is important for transparency.

---

# 40. API Suggestions

Possible endpoints:

```text
POST /api/profile/estimate-demand

POST /api/portfolios/generate

POST /api/portfolios/evaluate

POST /api/recommendations

POST /api/scenario

GET /api/reference/mobility-options

GET /api/reference/assumptions
```

A simpler MVP may expose only:

```text
POST /api/analyze
```

with internal modular services.

---

# 41. Core Data Entities

Suggested domain objects:

```text
Person
Household
UserProfile
MobilityMission
MobilityDemand
MobilityOption
OwnedAsset
Subscription
Portfolio
ModeAssignment
PortfolioEvaluation
Recommendation
ModelParameter
DataSourceMetadata
```

Keep domain models separate from frontend form models.

---

# 42. First Definition of Done

The first working MobiMix Personal prototype is complete when a user can:

1. open the web page;
2. answer a short questionnaire;
3. describe a current mobility portfolio;
4. obtain an estimated annual mobility demand;
5. obtain an estimated annual cost of the current portfolio;
6. generate multiple alternative portfolios;
7. reject clearly infeasible alternatives;
8. compare alternatives by cost, time, and comfort;
9. see:
   - cheapest;
   - balanced;
   - fastest / most comfortable;
10. understand why each recommendation was generated;
11. modify at least a few assumptions in a what-if view;
12. rerun the analysis immediately.

The MVP does **not** need to be scientifically complete.

It must make the full MobiMix concept testable.

---

# 43. First Implementation Order

Claude Code should implement in this sequence.

## Step 1 — Project Skeleton

Create:

- React/Vite frontend;
- FastAPI backend;
- basic repository structure;
- local development instructions.

## Step 2 — Domain Models

Implement:

```text
UserProfile
Household
MobilityMission
MobilityDemand
MobilityOption
Portfolio
PortfolioEvaluation
```

## Step 3 — Static MVP Data

Create simple editable JSON/YAML datasets for:

- mobility options;
- costs;
- speeds;
- comfort;
- default statistical mobility profiles.

## Step 4 — Questionnaire

Create the first user input form.

## Step 5 — Demand Estimator

Convert profile answers into annual mobility missions.

Use simple rules.

## Step 6 — Current Portfolio Cost

Calculate annual current mobility cost.

## Step 7 — Portfolio Generator

Generate a limited set of plausible alternatives.

## Step 8 — Feasibility

Reject impossible / implausible alternatives.

## Step 9 — Evaluation

Calculate:

```text
cost
time
comfort
flexibility
```

## Step 10 — Recommendation

Produce:

```text
current
cheapest
balanced
fastest
```

## Step 11 — Results UI

Build clear cards and comparison charts.

## Step 12 — What-if

Allow editing a few core parameters.

---

# 44. Development Principles

When implementing:

1. **Prefer working end-to-end logic over model sophistication.**
2. **Do not bury assumptions in code.**
3. Put assumptions in editable configuration files.
4. Every model value should be replaceable later.
5. Keep calculation modules independent from UI.
6. Document formulas.
7. Write tests for economic calculations.
8. Avoid premature AI / ML.
9. Avoid premature GIS / routing integration.
10. Preserve future compatibility with MobiMix City.
11. Keep recommendation logic transparent.
12. Explicitly track uncertainty and data provenance.

---

# 45. Immediate Product Hypothesis

The first prototype should test whether users find value in this interaction:

> “Tell MobiMix roughly how you and your household move.”

Then:

> “Your current mobility is estimated to cost €X/year.”

Then:

> “Here are three realistic alternatives.”

And finally:

> “You could save €Y/year, but this would cost you approximately Z additional hours and reduce comfort by N.”

If this interaction is useful and understandable, deeper modelling can then be justified.

---

# 46. Working Name and Positioning

Product name:

# MobiMix

Possible descriptor:

> **Personal Mobility Portfolio Advisor**

Possible promise:

> **Find the right mobility mix for your life.**

Alternative conceptual description:

> A personal consultant that evaluates whether your current mobility setup is already efficient or whether another combination of vehicles, subscriptions, and mobility services would better fit your needs.

Possible future product family:

```text
MobiMix Personal
MobiMix City
```

---

# 47. Final Principle

The implementation should always preserve this distinction:

```text
MOBILITY NEED
    ≠
MOBILITY MODE
    ≠
MOBILITY PORTFOLIO
```

MobiMix models the first, chooses among the second, and recommends the third.

That is the core of the project.
