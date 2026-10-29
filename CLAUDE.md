# CLAUDE.md — MobiMix

## Project Identity

This repository contains **MobiMix Personal**, a web application that acts as a **personal mobility portfolio advisor**.

MobiMix does not optimize a single trip.

Its purpose is to answer:

> Given the way a person or household actually lives and moves, what combination of privately owned vehicles, subscriptions, public transport and pay-per-use mobility services best fits their needs?

The project should eventually support two related products:

- **MobiMix Personal** — recommendations for individuals and households;
- **MobiMix City** — city-scale simulation using synthetic populations and aggregated behavioural models.

Before making architectural or modelling decisions, read:

- `MOBIMIX_PROJECT.md`

Treat that document as the main product and modelling brief.

This file defines **how Claude Code should work on the repository**.

---

# 1. Primary Development Goal

The first objective is **not** to build a scientifically complete transport model.

The first objective is to create a working end-to-end prototype that demonstrates the full MobiMix logic:

```text
User profile
→ mobility demand
→ current portfolio
→ candidate portfolios
→ feasibility
→ mode assignment
→ cost/time/comfort evaluation
→ recommendations
→ user-facing explanation
```

Prefer:

> a simple model that works from start to finish

over:

> a sophisticated isolated module that prevents the prototype from being usable.

The MVP must remain easy to improve later.

---

# 2. Developer Context

The main developer is technically comfortable with:

- Python;
- FastAPI;
- PostgreSQL;
- PostGIS;
- Docker / Docker Compose;
- VS Code;
- QGIS;
- data analysis;
- GIS;
- transport modelling;
- optimization models;
- React / Vite at application level.

Do not unnecessarily hide implementation details behind heavy abstractions.

Prefer code that is:

- readable;
- explicit;
- inspectable;
- testable;
- easy to modify manually.

The developer is comfortable reading Python, SQL, JSON, YAML and TypeScript.

When choosing between a large framework and a smaller transparent implementation, prefer the smaller one unless there is a clear technical reason not to.

---

# 3. Preferred Technology Stack

Unless the repository already establishes a different stack, prefer:

## Backend

- Python 3.12+
- FastAPI
- Pydantic
- pytest

## Frontend

- React
- Vite
- TypeScript

## Data

For the first prototype:

- JSON;
- YAML;
- CSV;
- SQLite only if persistence is actually useful.

Later:

- PostgreSQL;
- PostGIS.

Do **not** introduce PostgreSQL/PostGIS just because they are familiar technologies.

Use them when spatial queries, shared persistence, larger datasets or structured production storage justify them.

## Deployment

Prefer:

- Docker;
- Docker Compose;

but the project should also be runnable locally without Docker when practical.

---

# 4. Operating Environment

Assume development may happen on:

- Windows 11;
- VS Code;
- PowerShell;
- Docker Desktop.

When writing setup instructions:

- provide commands compatible with PowerShell where relevant;
- avoid assuming Linux-only shell syntax unless clearly marked;
- use `.env.example`;
- avoid hard-coded absolute paths;
- avoid platform-specific filesystem assumptions.

---

# 5. Core Modelling Principle

Always preserve the distinction:

```text
MOBILITY NEED
≠
MOBILITY MODE
≠
MOBILITY PORTFOLIO
```

Definitions:

## Mobility Need

A trip requirement or aggregated recurring mobility requirement.

Example:

```text
Commute:
8 km each way
180 days/year
1 person
arrival time important
```

## Mobility Mode

A way to satisfy a mobility need.

Examples:

- car;
- public transport;
- bicycle;
- e-bike;
- taxi;
- car sharing;
- rail.

## Mobility Portfolio

The set of mobility resources available to a household.

Examples:

```text
1 car
2 public transport subscriptions
1 e-bike
car sharing pay-per-use
```

Do not collapse these concepts into one object.

---

# 6. Feasibility Before Optimization

This is a hard project rule.

Never rank a portfolio before checking whether it can reasonably satisfy the mobility demand.

Processing order must conceptually remain:

```text
generate portfolio
→ check feasibility
→ assign missions to modes
→ evaluate
→ rank
```

Do not allow the optimizer to recommend a cheap portfolio that cannot satisfy the household's actual needs.

Example:

A family that regularly travels 180 km with two children and luggage cannot simply be assigned bicycles because they are cheap.

---

# 7. Neutrality

MobiMix is not an anti-car application.

MobiMix is not a MaaS sales funnel.

MobiMix is not a public transport promotion tool.

Recommendations must be neutral.

The correct recommendation may be:

- keep two cars;
- keep one car;
- sell one car;
- buy an e-bike;
- buy a scooter;
- buy a car;
- subscribe to public transport;
- cancel a public transport subscription;
- use taxi more often;
- use rental cars for long trips.

Never bias scoring to force sustainable modes to win.

Environmental metrics may be shown separately.

---

# 8. Three Main User Criteria

The application must explicitly compare portfolios according to:

1. **Cost**
2. **Travel time**
3. **Comfort / convenience**

Additional dimensions may exist:

- flexibility;
- reliability;
- CO2;
- car independence;
- magnitude of behavioural change.

But cost, time and comfort are the primary product dimensions.

---

# 9. Recommended Results

Do not return only one recommendation.

The default result set should include:

```text
CURRENT
CHEAPEST
BALANCED
FASTEST / MOST CONVENIENT
```

If some results are identical, deduplicate them.

The result screen should make trade-offs obvious.

Example:

```text
Balanced portfolio

1 car
1 e-bike
2 PT subscriptions

€6,400/year
-€1,650 vs current

455 h/year
+45 h vs current

Comfort
7.4 / 10
```

---

# 10. Current Portfolio Is the Baseline

The current setup must always be evaluated explicitly.

For every recommended alternative calculate differences against the current portfolio:

```text
delta_cost
delta_time
delta_comfort
delta_flexibility
delta_car_km
delta_co2
```

Where meaningful also calculate:

```text
saving_per_extra_hour
```

Example:

```text
Annual saving: €2,800
Additional travel time: 35 h/year

Saving per additional travel hour:
€80/h
```

This is an important MobiMix metric.

---

# 11. Avoid False Precision

Many inputs will be estimated.

The model must track provenance and confidence.

Every estimated input should support:

```text
value
source
confidence
```

Suggested sources:

```text
DECLARED_EXACT
DECLARED_APPROXIMATE
INFERRED
STATISTICAL_ESTIMATE
DEFAULT
OBSERVED
```

Do not present:

```text
€7,683.24
```

when the underlying inputs are uncertain.

Prefer:

```text
approximately €7,400–€8,100/year
```

or:

```text
€7,700/year
medium confidence
```

---

# 12. Missing Data Is Normal

The user should not be expected to know:

- exact annual kilometres;
- exact number of taxi trips;
- exact weekend distance;
- exact public transport trips.

The application must work with partial information.

If data are missing:

1. infer what can be derived from other answers;
2. use statistical defaults;
3. record that the value is estimated;
4. expose uncertainty;
5. optionally ask a follow-up question if it materially improves the result.

Do not force the user through a large questionnaire.

---

# 13. Adaptive Questionnaire

The questionnaire should be short by default.

Target:

- approximately 8–12 questions in the quick flow.

Ask more only when relevant.

Examples:

If:

```text
cars_owned = 0
```

do not ask annual car mileage.

If:

```text
cars_owned >= 2
```

ask:

> How often are two cars needed at the same time?

If:

```text
annual_car_km = unknown
```

offer ranges or estimate from mobility missions.

Avoid unnecessary demographic questions unless they improve the model.

---

# 14. Household Logic

A household is not simply a collection of independent people.

Vehicle availability can conflict.

Future full models should support:

```text
person
time
vehicle
mission
```

and detect overlaps.

The MVP may simplify this using categorical inputs such as:

```text
simultaneous_car_need:
never
rarely
sometimes
often
daily
```

But keep domain models compatible with future explicit schedules.

---

# 15. Mobility Missions

Represent annual mobility using missions.

Suggested mission categories:

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

A mission should support fields such as:

```text
distance
frequency
passengers
luggage
children
time criticality
time window
weather sensitivity
```

Do not model everything only as:

```text
annual_km
```

because:

```text
1000 km commuting
```

and:

```text
1000 km family holidays
```

are not equivalent mobility needs.

---

# 16. Cost Model

Keep cost calculations in a dedicated module.

Private vehicle costs should use **Total Cost of Ownership**.

Typical car cost:

```text
depreciation
+ insurance
+ taxes
+ maintenance
+ tyres
+ fuel/electricity
+ parking
+ tolls
```

The MVP can simplify this to:

```text
annual_fixed_cost
+ variable_cost_per_km * annual_km
```

but the structure must allow richer formulas later.

Do not scatter cost constants throughout business logic.

All costs should come from configuration / reference data.

---

# 17. Configuration and Assumptions

Model assumptions must be visible.

Prefer:

```text
data/
  mobility_options.yaml
  tariffs.yaml
  default_profiles.yaml
  comfort_scores.yaml
  model_parameters.yaml
```

over constants embedded in Python code.

Every important parameter should ideally support metadata:

```text
value
unit
source
geographic_scope
valid_from
valid_to
confidence
notes
```

The first values may be placeholders.

Clearly label placeholders.

---

# 18. Geographic Model

MVP geography should remain simple.

Do not build a routing engine initially.

Possible first geographic inputs:

```text
municipality
zone
urban / suburban / peripheral
Car Independence Index
PT quality class
sharing availability class
```

The **Car Independence Index** can be used as a contextual prior.

Do not use it as a deterministic rule.

Wrong:

```python
if cii > 6:
    recommend_no_car()
```

Better:

```python
car_free_feasibility = f(
    cii,
    household,
    mobility_needs,
    available_services
)
```

Future versions may replace CII with direct multimodal accessibility and routing.

---

# 19. Future Personal Car Independence Index

Keep room for a future user-specific indicator.

Concept:

```text
Personal Car Independence Index
```

Possible interpretation:

> Percentage of the household's ordinary mobility needs that can be reasonably satisfied without a private car.

Possible output:

```text
Car Independence: 82 / 100

91% of ordinary mobility needs
can be satisfied without a private car
with less than 12 minutes average additional travel time.
```

Do not implement this prematurely unless useful for the MVP.

---

# 20. Candidate Portfolio Generation

The first implementation should use a controlled set of plausible portfolios.

Examples:

```text
2 cars

1 car

1 car + PT

1 car + e-bike

1 car + scooter

1 car + PT + e-bike

0 cars + PT

0 cars + PT + e-bike

0 cars + PT + car sharing

0 cars + PT + taxi + rental
```

Do not attempt unrestricted combinatorial enumeration in the first version.

The generator must be modular so more combinations can be introduced later.

---

# 21. Optimization Strategy

Do not introduce MILP, OR-Tools or advanced solvers until the simple engine becomes limiting.

Initial approach may use:

- rule-based assignment;
- exhaustive evaluation over a small candidate set;
- deterministic scoring.

Later candidates:

- MILP;
- constraint programming;
- OR-Tools;
- multi-objective optimization;
- stochastic models.

Keep the optimizer behind an interface so implementation can change.

---

# 22. Change Penalty

Do not recommend major lifestyle changes for negligible gains.

The recommendation engine should consider a **change penalty**.

Examples of changes:

```text
selling a vehicle
buying a vehicle
adding transfers
changing commute habits
depending on car sharing
reducing flexibility
adding weather exposure
```

Example:

Saving:

```text
€350/year
```

while requiring:

```text
sell second car
buy e-bike
change commute
```

should probably result in:

```text
KEEP CURRENT
```

or:

```text
SMALL POTENTIAL IMPROVEMENT
```

not:

```text
STRONGLY RECOMMENDED
```

---

# 23. Recommendation Levels

Prefer explicit recommendation categories:

```text
KEEP CURRENT

OPTIMIZE USAGE

CHANGE SUBSCRIPTION

ADD ASSET

REPLACE VEHICLE

REDUCE VEHICLES

CONSIDER PORTFOLIO CHANGE

STRONG CHANGE OPPORTUNITY
```

The reason must be explained.

---

# 24. Explainability

Every result must include human-readable reasons.

Bad:

```text
Recommended:
1 car + 1 e-bike
```

Good:

```text
Your second car contributes approximately €4,200/year
to your mobility costs.

Based on your mobility profile, a second private car
appears essential only about 30–40 days/year.

Car sharing, taxi and occasional rental can cover
most of those cases for approximately €2,000/year.

Estimated saving:
€1,900–€2,300/year.
```

Recommendation explanations should come from structured facts produced by the model.

Do not fabricate explanations independently from calculated results.

---

# 25. Frontend UX

The web application should feel like a consumer product, not a transport modelling tool.

Avoid exposing technical jargon such as:

```text
generalized cost
Pareto frontier
MILP
utility function
```

unless on the methodology page.

Use plain language:

```text
Cheapest
Best balance
Fastest
Most comfortable
```

Visual priorities:

- current vs alternative;
- annual saving;
- additional time;
- comfort difference;
- owned vehicles;
- subscriptions;
- confidence.

---

# 26. Results Visualization

Prefer simple comparison charts.

Useful visualizations:

- annual cost bars;
- annual travel time bars;
- comfort score;
- portfolio composition;
- savings vs additional hours;
- car kilometres;
- confidence.

Avoid complex dashboards with many charts in the MVP.

The main user question should remain obvious:

> Should I change my mobility setup?

---

# 27. What-if Simulator

Architecture should support rapid recomputation.

Useful scenario parameters:

```text
remote work days
fuel cost
parking cost
PT price
annual car km
e-bike subsidy
number of cars
car sharing availability
holiday distance
```

The MVP only needs a few of these.

Do not build a generic simulation framework before basic recommendations work.

---

# 28. API Design

Prefer a simple API first.

An initial endpoint can be:

```text
POST /api/analyze
```

Input:

```text
UserProfile
```

Output:

```text
AnalysisResult
```

Internally keep services modular.

Later endpoints may include:

```text
POST /api/profile/estimate-demand
POST /api/portfolios/generate
POST /api/portfolios/evaluate
POST /api/scenario
```

Do not create unnecessary REST fragmentation during the MVP.

---

# 29. Suggested Backend Modules

Prefer a structure similar to:

```text
backend/app/
│
├── api/
├── models/
├── services/
│   ├── demand/
│   ├── costs/
│   ├── feasibility/
│   ├── portfolios/
│   ├── optimizer/
│   ├── scoring/
│   ├── recommendations/
│   └── statistics/
│
├── data/
└── main.py
```

Keep:

```text
models
business logic
reference data
API
```

separate.

---

# 30. Suggested Core Interfaces

Maintain conceptual interfaces similar to:

```python
class DemandEstimator:
    def estimate(self, profile) -> MobilityDemand:
        ...

class CostModel:
    def calculate(self, option, usage) -> CostResult:
        ...

class PortfolioGenerator:
    def generate(self, profile, demand) -> list[Portfolio]:
        ...

class FeasibilityChecker:
    def check(self, portfolio, demand) -> FeasibilityResult:
        ...

class PortfolioOptimizer:
    def assign(self, portfolio, demand) -> ModeAssignment:
        ...

class PortfolioEvaluator:
    def evaluate(self, portfolio, assignment, profile) -> PortfolioEvaluation:
        ...

class RecommendationEngine:
    def recommend(self, current, alternatives, profile) -> RecommendationSet:
        ...
```

Do not over-abstract beyond what is needed to keep these modules replaceable.

---

# 31. Testing Priorities

Tests are particularly important for calculation logic.

Prioritize:

## Cost tests

- depreciation;
- fixed costs;
- variable cost per km;
- subscription break-even;
- taxi / sharing cost;
- portfolio total.

## Feasibility tests

- impossible long-distance bike-only scenario;
- household with simultaneous car needs;
- car-free scenario with rental for holidays;
- public transport unavailable.

## Recommendation tests

- current setup already optimal;
- obvious second-car removal case;
- tiny savings should not trigger major change;
- large savings with low penalty should trigger recommendation.

## Missing-data tests

- unknown annual car km;
- incomplete weekend mobility;
- estimated values receive lower confidence.

---

# 32. Demo Households

Maintain fixed demo profiles.

At minimum:

```text
urban_single
urban_couple
family_two_cars
peripheral_family
car_free_household
```

These profiles should be stored as test fixtures.

They should be easy to load into the frontend during development.

Use them for regression testing.

---

# 33. Data Enrichment Strategy

The project is intentionally designed so model quality can improve gradually.

Do not block MVP implementation while searching for perfect datasets.

Progression:

```text
generic assumptions
→ Italian national datasets
→ Milan-specific datasets
→ routing
→ household scheduling
→ observed Personal data
```

Potential sources later:

- ISTAT;
- Audimob / ISFORT;
- ACI;
- municipal open data;
- public transport tariffs;
- GTFS;
- mobility sharing data;
- parking;
- Area B / Area C;
- accessibility indicators;
- Car Independence Index.

When replacing data, keep interfaces stable where possible.

---

# 34. GIS and Routing

The main developer has strong GIS skills, but do not let GIS dominate the initial architecture.

MVP:

```text
distance provided by user
or
simple estimated distance
```

Later:

```text
origin/destination
→ multimodal routing
→ travel time
→ generalized accessibility
```

Possible future stack may include:

- PostGIS;
- pgRouting;
- external routing engines;
- GTFS-based PT routing.

Do not implement these unless explicitly requested.

---

# 35. MobiMix City Compatibility

MobiMix Personal must not be designed as a disposable standalone app.

Future MobiMix City should be able to call the same core model repeatedly on synthetic households.

Therefore:

- avoid UI-specific logic inside model services;
- make the analysis callable programmatically;
- keep profiles serializable;
- keep model parameters external;
- make random/statistical estimation reproducible with seeds where relevant;
- keep outputs structured and aggregatable.

Conceptually MobiMix City will do:

```python
for household in synthetic_population:
    result = mobimix.analyze(household)
    aggregate(result)
```

Design core services so this becomes possible.

---

# 36. Personal → City Calibration

Future voluntarily provided MobiMix Personal data may improve City realism.

Potential aggregate calibration variables:

```text
vehicle ownership
annual kilometres
trip frequency
weekend mobility
subscription ownership
comfort preferences
willingness to change
recommendation adoption
```

Do not implement collection infrastructure now.

But avoid schemas that would prevent later aggregation.

Keep statistical data separate from personally identifiable account data.

---

# 37. Privacy-by-Design

Collect only what the model needs.

Prefer:

```text
age band
zone
household size
mobility characteristics
```

over unnecessary exact personal details.

Do not require:

- full identity;
- exact home address;
- exact workplace address;

for the MVP.

Future exact routing locations should be optional.

Keep conceptual separation between:

```text
account
mobility profile
analysis
anonymous aggregate data
```

---

# 38. No Premature AI

Do not introduce LLMs or ML simply because the project is data-driven.

The first model should be deterministic and auditable.

Potential future uses of AI:

- natural language intake;
- extracting mobility habits from free text;
- estimating missing values;
- recommendation explanations;
- behavioural models.

But the core recommendation should remain inspectable.

---

# 39. No Premature Real-Time Integrations

The MVP does not need:

- ticket purchasing;
- live traffic;
- live sharing vehicle positions;
- booking;
- payment;
- account connections.

Use static reference values first.

The core hypothesis is the portfolio recommendation, not MaaS integration.

---

# 40. Documentation

When adding modelling logic, document:

- formula;
- assumptions;
- units;
- source;
- known limitations.

Prefer a short methodological note close to the relevant module.

Maintain:

```text
docs/
  methodology.md
  data_sources.md
  assumptions.md
```

as the model matures.

Do not allow undocumented “magic numbers”.

---

# 41. Code Style

Prefer:

- typed Python;
- small functions;
- dataclasses/Pydantic models where appropriate;
- explicit variable names;
- simple control flow;
- comments explaining modelling assumptions, not obvious syntax.

Avoid:

- deep inheritance trees;
- metaprogramming;
- opaque generic frameworks;
- unnecessary design patterns;
- hidden global state.

---

# 42. SQL Style

When PostgreSQL is introduced:

- use explicit schemas;
- write readable SQL;
- document SRIDs;
- use indexes intentionally;
- avoid ORM-only logic for spatial operations where SQL/PostGIS is clearer.

The developer is comfortable inspecting SQL directly.

Prefer transparent SQL for analytical and GIS-heavy operations.

---

# 43. Docker

If Docker is used:

Provide:

```text
docker-compose.yml
.env.example
README instructions
```

Keep services minimal.

Do not introduce:

- Kubernetes;
- message brokers;
- distributed workers;

unless a future requirement clearly justifies them.

---

# 44. Error Handling

User-facing errors should explain what is missing or inconsistent.

Example:

Bad:

```text
Optimization failed.
```

Better:

```text
We could not find a feasible car-free portfolio
because your household requires simultaneous long-distance travel
on several days per week.
```

Backend errors should remain technically useful in logs.

---

# 45. Development Workflow

When asked to implement a feature:

1. inspect existing code;
2. identify the smallest module affected;
3. preserve current interfaces where sensible;
4. implement;
5. add/update tests;
6. run relevant tests;
7. summarize:
   - what changed;
   - assumptions introduced;
   - files changed;
   - remaining limitations.

Do not rewrite large parts of the project unless necessary.

---

# 46. When Requirements Are Ambiguous

When a modelling choice is uncertain:

Prefer a simple documented assumption.

Example:

```text
For MVP, assume average e-bike speed = X km/h.
This value is configurable in mobility_options.yaml.
```

Do not stop implementation for every uncertain parameter.

Flag assumptions clearly so they can be replaced later.

---

# 47. Product Questions to Preserve

The implementation should remain capable of answering questions such as:

```text
Is my current mobility setup efficient?

Should I keep my car?

Should I sell my second car?

Should I buy an e-bike?

Would a PT subscription save money?

Would car sharing + rental replace my second car?

How much did my mobility really cost last year?

What would last year have cost with another mobility portfolio?

How much money can I save?

How much extra travel time would I accept for that saving?

What is the cheapest feasible portfolio?

What is the fastest portfolio?

What is the best compromise?
```

If an architectural decision would make these questions harder to answer later, reconsider it.

---

# 48. MVP Definition of Done

The MVP is ready when a user can:

1. open the web app;
2. answer a short questionnaire;
3. describe current vehicles and subscriptions;
4. obtain an estimated annual mobility demand;
5. see estimated current annual mobility cost;
6. receive several feasible alternative portfolios;
7. compare:
   - cost;
   - time;
   - comfort;
8. see current / cheapest / balanced / fastest;
9. understand why the recommendation was generated;
10. modify selected assumptions and rerun the analysis.

Scientific completeness is **not** required for MVP completion.

---

# 49. Immediate Implementation Priority

Unless instructed otherwise, work in this order:

```text
1. repository skeleton
2. domain models
3. editable reference data
4. questionnaire
5. demand estimator
6. current cost model
7. candidate portfolio generator
8. feasibility checker
9. assignment logic
10. evaluator
11. recommendation engine
12. results UI
13. what-if controls
14. tests and methodology documentation
```

Do not jump directly to advanced optimization.

---

# 50. Final Project Rule

Whenever unsure about a technical or modelling decision, return to this principle:

> MobiMix should be simple enough to prototype quickly, transparent enough to trust, modular enough to improve, and rigorous enough that its recommendations can later evolve into a credible personal and city-scale mobility model.

